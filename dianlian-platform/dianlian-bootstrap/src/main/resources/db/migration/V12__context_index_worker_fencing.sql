-- Harden the authority-to-projection boundary introduced by V11.
--
-- This migration intentionally stores only authority metadata and projection jobs in
-- dianlian_business. Retrieval chunks and vectors belong to the rebuildable projection
-- store and must not be added to the business schema.

ALTER TABLE dianlian_business.context_index_job
    ADD COLUMN lease_epoch BIGINT NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
    ADD COLUMN index_profile_version VARCHAR(100) NOT NULL DEFAULT 'context-default-v1'
        CHECK (BTRIM(index_profile_version) <> '');

-- V11 used an unnamed unique constraint, whose generated name is PostgreSQL-version
-- dependent after identifier truncation. Resolve it by its ordered columns instead of
-- relying on that generated name, then make the projection profile part of idempotency.
DO $migration$
DECLARE
    legacy_constraint_name TEXT;
    matching_constraint_count INTEGER;
BEGIN
    SELECT COUNT(*), MIN(candidate.conname)
      INTO matching_constraint_count, legacy_constraint_name
      FROM (
          SELECT constraint_row.conname::TEXT AS conname
            FROM pg_constraint constraint_row
           WHERE constraint_row.conrelid = 'dianlian_business.context_index_job'::REGCLASS
             AND constraint_row.contype = 'u'
             AND (
                 SELECT ARRAY_AGG(attribute.attname::TEXT ORDER BY key_column.ordinality)
                   FROM UNNEST(constraint_row.conkey) WITH ORDINALITY
                       AS key_column(attnum, ordinality)
                   JOIN pg_attribute attribute
                     ON attribute.attrelid = constraint_row.conrelid
                    AND attribute.attnum = key_column.attnum
             ) = ARRAY[
                 'tenant_id', 'resource_type', 'resource_id', 'resource_version',
                 'event_sequence', 'index_target', 'operation'
             ]::TEXT[]
      ) candidate;

    IF matching_constraint_count <> 1 THEN
        RAISE EXCEPTION
            'expected exactly one V11 context index job idempotency constraint, found %',
            matching_constraint_count;
    END IF;

    EXECUTE FORMAT(
        'ALTER TABLE dianlian_business.context_index_job DROP CONSTRAINT %I',
        legacy_constraint_name
    );
END;
$migration$;

ALTER TABLE dianlian_business.context_index_job
    ADD CONSTRAINT uq_context_index_job_projection_profile
        UNIQUE NULLS NOT DISTINCT
        (tenant_id, resource_type, resource_id, resource_version, event_sequence,
         index_target, index_profile_version, operation);

CREATE INDEX idx_context_index_job_expired_running_dispatch
    ON dianlian_business.context_index_job (lease_expires_at, event_sequence, job_id)
    WHERE status = 'RUNNING';

DROP INDEX dianlian_business.idx_context_index_job_resource_latest;
CREATE INDEX idx_context_index_job_resource_latest
    ON dianlian_business.context_index_job
        (resource_type, resource_id, index_target, index_profile_version,
         event_sequence DESC, resource_version DESC);

COMMENT ON COLUMN dianlian_business.context_index_job.lease_epoch IS
    'Monotonic fencing token incremented on every claim, including takeover of an expired RUNNING lease.';
COMMENT ON COLUMN dianlian_business.context_index_job.index_profile_version IS
    'Stable projection profile identity covering chunking, normalization and embedding configuration.';

ALTER TABLE dianlian_business.knowledge_document_version
    ADD COLUMN normalized_text_hash VARCHAR(64),
    ADD COLUMN normalization_profile_version VARCHAR(100),
    ADD COLUMN normalized_at TIMESTAMPTZ;

-- V11 could enqueue a knowledge UPSERT while the parser had not produced text. Quarantine
-- only those actionable jobs whose authority row is still active but incomplete. Historical
-- events and authority rows stay untouched, and no replacement event or job is fabricated.
UPDATE dianlian_business.context_index_job job
   SET status = 'DEAD_LETTER',
       lease_owner = NULL,
       lease_expires_at = NULL,
       last_error_code = 'KNOWLEDGE_NORMALIZATION_MISSING',
       last_error_message = 'V12 quarantined an UPSERT queued before knowledge normalization completed',
       updated_at = CURRENT_TIMESTAMP
 WHERE job.resource_type = 'KNOWLEDGE_DOCUMENT_VERSION'
   AND job.operation = 'UPSERT'
   AND job.status IN ('PENDING', 'RUNNING', 'FAILED')
   AND EXISTS (
       SELECT 1
         FROM dianlian_business.knowledge_document_version version
        WHERE version.document_version_id = job.resource_id
          AND version.tenant_id IS NOT DISTINCT FROM job.tenant_id
          AND version.status = 'PUBLISHED'
          AND version.access_state = 'ACTIVE'
          AND (
              version.normalized_text IS NULL
              OR version.normalized_text_hash IS NULL
              OR version.normalization_profile_version IS NULL
              OR version.normalized_at IS NULL
          )
   );

-- NOT VALID preserves upgradeability for any V11 row whose normalized_text was inserted
-- directly before these metadata columns existed. PostgreSQL still enforces both checks for
-- every new or updated row. Such a legacy row must be completed with a real hash/profile/time;
-- this migration never invents parsed text, hashes, publication events or projection jobs.
ALTER TABLE dianlian_business.knowledge_document_version
    ADD CONSTRAINT ck_knowledge_version_normalization_snapshot
        CHECK (
            (normalized_text IS NULL
                AND normalized_text_hash IS NULL
                AND normalization_profile_version IS NULL
                AND normalized_at IS NULL)
            OR
            (normalized_text IS NOT NULL
                AND BTRIM(normalized_text) <> ''
                AND normalized_text_hash ~ '^[0-9a-f]{64}$'
                AND BTRIM(normalization_profile_version) <> ''
                AND normalized_at IS NOT NULL
                AND normalized_at >= created_at)
        ) NOT VALID,
    ADD CONSTRAINT ck_knowledge_version_non_draft_normalized
        CHECK (
            status = 'DRAFT'
            OR access_state = 'DELETED'
            OR (
                normalized_text IS NOT NULL
                AND normalized_text_hash IS NOT NULL
                AND normalization_profile_version IS NOT NULL
                AND normalized_at IS NOT NULL
            )
        ) NOT VALID;

CREATE OR REPLACE FUNCTION dianlian_business.protect_knowledge_version_content()
RETURNS TRIGGER AS
$$
DECLARE
    old_normalization_metadata_empty BOOLEAN;
    new_normalization_snapshot_complete BOOLEAN;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'knowledge document versions use deletion tombstones';
    END IF;

    IF NEW.document_version_id IS DISTINCT FROM OLD.document_version_id
        OR NEW.document_id IS DISTINCT FROM OLD.document_id
        OR NEW.space_id IS DISTINCT FROM OLD.space_id
        OR NEW.version_no IS DISTINCT FROM OLD.version_no
        OR NEW.object_key IS DISTINCT FROM OLD.object_key
        OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
        OR NEW.mime_type IS DISTINCT FROM OLD.mime_type
        OR NEW.byte_size IS DISTINCT FROM OLD.byte_size
        OR NEW.metadata IS DISTINCT FROM OLD.metadata
        OR NEW.created_by IS DISTINCT FROM OLD.created_by
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
        OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
        OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key THEN
        RAISE EXCEPTION 'knowledge document version identity and source snapshot are immutable';
    END IF;

    old_normalization_metadata_empty := OLD.normalized_text_hash IS NULL
        AND OLD.normalization_profile_version IS NULL
        AND OLD.normalized_at IS NULL;
    new_normalization_snapshot_complete := NEW.normalized_text IS NOT NULL
        AND BTRIM(NEW.normalized_text) <> ''
        AND NEW.normalized_text_hash ~ '^[0-9a-f]{64}$'
        AND NEW.normalization_profile_version IS NOT NULL
        AND BTRIM(NEW.normalization_profile_version) <> ''
        AND NEW.normalized_at IS NOT NULL
        AND NEW.normalized_at >= NEW.created_at;

    IF OLD.normalized_text IS NULL AND NEW.normalized_text IS NULL THEN
        IF NEW.normalized_text_hash IS NOT NULL
            OR NEW.normalization_profile_version IS NOT NULL
            OR NEW.normalized_at IS NOT NULL THEN
            RAISE EXCEPTION 'normalization metadata cannot exist before normalized knowledge text';
        END IF;
    ELSIF OLD.normalized_text IS NULL AND NEW.normalized_text IS NOT NULL THEN
        IF NOT old_normalization_metadata_empty
            OR NOT new_normalization_snapshot_complete
            OR NEW.status <> 'PUBLISHED'
            OR NEW.access_state <> 'ACTIVE'
            OR NEW.index_state <> 'PENDING' THEN
            RAISE EXCEPTION
                'normalized knowledge text must be fixed once with hash, profile, publication and pending index state';
        END IF;
    ELSIF OLD.normalized_text IS NOT NULL AND NEW.normalized_text IS NULL THEN
        IF NEW.access_state <> 'DELETED'
            OR NEW.purged_at IS NULL
            OR NEW.normalized_text_hash IS NOT NULL
            OR NEW.normalization_profile_version IS NOT NULL
            OR NEW.normalized_at IS NOT NULL THEN
            RAISE EXCEPTION 'normalized knowledge text and metadata can only be purged after deletion';
        END IF;
    ELSE
        IF NEW.normalized_text IS DISTINCT FROM OLD.normalized_text THEN
            RAISE EXCEPTION 'normalized knowledge text is immutable after it is fixed';
        END IF;

        -- Compatibility path for a pre-V12 row that already contains genuine normalized
        -- text. It permits one metadata completion, but never changes the text or source hash.
        IF old_normalization_metadata_empty THEN
            IF NOT new_normalization_snapshot_complete
                OR NEW.status <> 'PUBLISHED'
                OR NEW.access_state <> 'ACTIVE' THEN
                RAISE EXCEPTION 'legacy normalized knowledge text requires one complete metadata snapshot';
            END IF;
        ELSIF NEW.normalized_text_hash IS DISTINCT FROM OLD.normalized_text_hash
            OR NEW.normalization_profile_version IS DISTINCT FROM OLD.normalization_profile_version
            OR NEW.normalized_at IS DISTINCT FROM OLD.normalized_at THEN
            RAISE EXCEPTION 'knowledge normalization metadata is immutable after it is fixed';
        END IF;
    END IF;

    IF OLD.access_state = 'DELETED' AND NEW.access_state <> 'DELETED' THEN
        RAISE EXCEPTION 'deleted knowledge versions cannot be restored';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION dianlian_business.assert_knowledge_publish_event_ready()
RETURNS TRIGGER AS
$$
BEGIN
    IF NEW.aggregate_type = 'DOCUMENT_VERSION'
        AND NEW.event_type = 'KNOWLEDGE_DOCUMENT_VERSION_PUBLISHED'
        AND NOT EXISTS (
            SELECT 1
              FROM dianlian_business.knowledge_document_version version
             WHERE version.document_version_id = NEW.aggregate_id
               AND version.tenant_id IS NOT DISTINCT FROM NEW.tenant_id
               AND version.status = 'PUBLISHED'
               AND version.access_state = 'ACTIVE'
               AND version.resource_version = NEW.resource_version
               AND version.normalized_text IS NOT NULL
               AND version.normalized_text_hash IS NOT NULL
               AND version.normalization_profile_version IS NOT NULL
               AND version.normalized_at IS NOT NULL
        ) THEN
        RAISE EXCEPTION 'knowledge publication event requires a completed normalization snapshot';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_knowledge_event_publish_ready
    BEFORE INSERT ON dianlian_business.knowledge_event
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_knowledge_publish_event_ready();

CREATE OR REPLACE FUNCTION dianlian_business.assert_knowledge_index_job_ready()
RETURNS TRIGGER AS
$$
BEGIN
    IF NEW.resource_type = 'KNOWLEDGE_DOCUMENT_VERSION'
        AND NEW.operation = 'UPSERT'
        AND NOT EXISTS (
            SELECT 1
              FROM dianlian_business.knowledge_document_version version
             WHERE version.document_version_id = NEW.resource_id
               AND version.tenant_id IS NOT DISTINCT FROM NEW.tenant_id
               AND (
                   (NEW.authority_scope = 'PLATFORM' AND version.tenant_id IS NULL)
                   OR
                   (NEW.authority_scope = 'TENANT' AND version.tenant_id IS NOT NULL)
               )
               AND version.status = 'PUBLISHED'
               AND version.access_state = 'ACTIVE'
               AND version.resource_version = NEW.resource_version
               AND version.event_sequence <= NEW.event_sequence
               AND version.normalized_text IS NOT NULL
               AND version.normalized_text_hash IS NOT NULL
               AND version.normalization_profile_version IS NOT NULL
               AND version.normalized_at IS NOT NULL
        ) THEN
        RAISE EXCEPTION 'knowledge UPSERT projection requires a completed current authority snapshot';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_context_index_job_knowledge_ready
    BEFORE INSERT OR UPDATE OF tenant_id, authority_scope, resource_type, resource_id,
        resource_version, event_sequence, index_target, index_profile_version, operation
    ON dianlian_business.context_index_job
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_knowledge_index_job_ready();

COMMENT ON COLUMN dianlian_business.knowledge_document_version.normalized_text_hash IS
    'Lowercase SHA-256 of the immutable normalized text; supplied by the trusted parser in the same authority transaction.';
COMMENT ON COLUMN dianlian_business.knowledge_document_version.normalization_profile_version IS
    'Stable parser and normalization profile used to produce normalized_text.';
COMMENT ON COLUMN dianlian_business.knowledge_document_version.normalized_at IS
    'Authority timestamp when normalized text, hash and profile were fixed atomically.';
COMMENT ON CONSTRAINT ck_knowledge_version_non_draft_normalized
    ON dianlian_business.knowledge_document_version IS
    'Published and superseded active authority rows require a complete normalization snapshot. Existing V11 rows remain readable until explicitly normalized or retired.';

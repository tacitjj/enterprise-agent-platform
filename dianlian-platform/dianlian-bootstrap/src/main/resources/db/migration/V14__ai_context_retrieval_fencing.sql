-- Bind every model call to the exact authority snapshot and evidence that was
-- revalidated immediately before the provider request. Historical snapshots are
-- append-only; lease takeover creates a new row instead of rewriting the old one.

ALTER TABLE dianlian_business.ai_context_snapshot
    DROP CONSTRAINT IF EXISTS ai_context_snapshot_invocation_id_key;

ALTER TABLE dianlian_business.ai_context_snapshot
    ADD COLUMN schema_version VARCHAR(32) NOT NULL DEFAULT 'legacy-v1',
    ADD COLUMN attempt_no INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN lease_epoch BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN access_membership_version BIGINT,
    ADD COLUMN history_floor_sequence_no BIGINT,
    ADD COLUMN authorization_snapshot_hash VARCHAR(64),
    ADD COLUMN retrieval_request_id UUID,
    ADD COLUMN retrieval_snapshot_id VARCHAR(200),
    ADD COLUMN retrieval_trace JSONB NOT NULL DEFAULT '{}'::JSONB,
    ADD COLUMN evidence_refs JSONB NOT NULL DEFAULT '[]'::JSONB,
    ADD COLUMN knowledge_reason_code VARCHAR(128),
    ADD COLUMN memory_reason_code VARCHAR(128),
    ADD COLUMN fenced_at TIMESTAMPTZ;

ALTER TABLE dianlian_business.ai_context_snapshot
    ADD CONSTRAINT chk_ai_context_snapshot_attempt
        CHECK (attempt_no >= 0 AND lease_epoch >= 0),
    ADD CONSTRAINT chk_ai_context_snapshot_trace
        CHECK (JSONB_TYPEOF(retrieval_trace) = 'object'),
    ADD CONSTRAINT chk_ai_context_snapshot_evidence
        CHECK (JSONB_TYPEOF(evidence_refs) = 'array'),
    ADD CONSTRAINT chk_ai_context_snapshot_retrieval_v1
        CHECK (
            schema_version <> 'context-retrieval-v1'
            OR (
                attempt_no > 0
                AND lease_epoch > 0
                AND access_membership_version > 0
                AND history_floor_sequence_no >= 0
                AND authorization_snapshot_hash ~ '^[0-9a-f]{64}$'
                AND retrieval_request_id IS NOT NULL
                AND retrieval_snapshot_id IS NOT NULL
                AND LENGTH(BTRIM(retrieval_snapshot_id)) BETWEEN 1 AND 200
                AND fenced_at IS NOT NULL
            )
        ),
    ADD CONSTRAINT uq_ai_context_snapshot_invocation_lease
        UNIQUE (invocation_id, attempt_no, lease_epoch);

CREATE INDEX idx_ai_context_snapshot_invocation_created
    ON dianlian_business.ai_context_snapshot (invocation_id, created_at DESC);

CREATE OR REPLACE FUNCTION dianlian_business.assert_ai_context_snapshot_partition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM dianlian_business.ai_invocation invocation
         WHERE invocation.invocation_id = NEW.invocation_id
           AND invocation.tenant_id = NEW.tenant_id
           AND invocation.enterprise_agent_id = NEW.enterprise_agent_id
           AND invocation.agent_version_id = NEW.agent_version_id
           AND invocation.configuration_version_id = NEW.configuration_version_id
    ) THEN
        RAISE EXCEPTION 'AI context snapshot execution identity does not match its invocation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_ai_context_snapshot_partition
    BEFORE INSERT ON dianlian_business.ai_context_snapshot
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_ai_context_snapshot_partition();

CREATE OR REPLACE FUNCTION dianlian_business.reject_ai_context_snapshot_change()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'AI context snapshots are append-only';
END;
$$;

CREATE TRIGGER trg_ai_context_snapshot_append_only
    BEFORE UPDATE OR DELETE ON dianlian_business.ai_context_snapshot
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.reject_ai_context_snapshot_change();

ALTER TABLE dianlian_business.ai_invocation
    ADD COLUMN context_snapshot_id UUID,
    ADD CONSTRAINT uq_ai_invocation_context_snapshot UNIQUE (context_snapshot_id),
    ADD CONSTRAINT fk_ai_invocation_context_snapshot
        FOREIGN KEY (context_snapshot_id)
        REFERENCES dianlian_business.ai_context_snapshot (context_snapshot_id)
        DEFERRABLE INITIALLY DEFERRED;

CREATE OR REPLACE FUNCTION dianlian_business.assert_ai_invocation_context_snapshot()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.context_snapshot_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
          FROM dianlian_business.ai_context_snapshot snapshot
         WHERE snapshot.context_snapshot_id = NEW.context_snapshot_id
           AND snapshot.invocation_id = NEW.invocation_id
           AND snapshot.tenant_id = NEW.tenant_id
    ) THEN
        RAISE EXCEPTION 'AI invocation context snapshot does not belong to the invocation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE CONSTRAINT TRIGGER trg_ai_invocation_context_snapshot
    AFTER INSERT OR UPDATE OF context_snapshot_id ON dianlian_business.ai_invocation
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_ai_invocation_context_snapshot();

COMMENT ON COLUMN dianlian_business.ai_invocation.context_snapshot_id IS
    'The immutable, lease-fenced context snapshot actually used for the provider request.';
COMMENT ON COLUMN dianlian_business.ai_context_snapshot.evidence_refs IS
    'Exact knowledge and memory evidence references used in the prompt; never stores hidden reasoning or secrets.';

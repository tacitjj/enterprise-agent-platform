-- Purpose: create fenced lexical knowledge and memory projections.
-- Scope: derived data only in dianlian_context; no business-authority tables are touched.
-- Idempotency: the migration ledger guarantees one application per checksum.
-- Rollback: deploy the previous runtime first; table removal requires an explicit reviewed migration.

CREATE TABLE dianlian_context.projection_fence
(
    fence_id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    authority_scope     VARCHAR(16)  NOT NULL CHECK (authority_scope IN ('PLATFORM', 'TENANT')),
    tenant_id           UUID,
    resource_type       VARCHAR(40)  NOT NULL CHECK (resource_type IN (
        'KNOWLEDGE_DOCUMENT_VERSION', 'MEMORY_ITEM_VERSION'
    )),
    resource_id         UUID         NOT NULL,
    index_profile       VARCHAR(100) NOT NULL CHECK (index_profile ~ '^[a-z0-9][a-z0-9._-]{0,99}$'),
    last_event_sequence BIGINT       NOT NULL CHECK (last_event_sequence >= 0),
    last_operation      VARCHAR(16)  NOT NULL CHECK (last_operation IN ('UPSERT', 'DELETE')),
    last_payload_hash   CHAR(64)     CHECK (
        last_payload_hash IS NULL OR last_payload_hash ~ '^[0-9a-f]{64}$'
    ),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_context_projection_fence_identity
        UNIQUE NULLS NOT DISTINCT
        (authority_scope, tenant_id, resource_type, resource_id, index_profile),
    CHECK (
        (authority_scope = 'PLATFORM' AND tenant_id IS NULL
            AND resource_type = 'KNOWLEDGE_DOCUMENT_VERSION')
        OR
        (authority_scope = 'TENANT' AND tenant_id IS NOT NULL)
    ),
    CHECK (
        (last_operation = 'DELETE' AND last_payload_hash IS NULL)
        OR
        (last_operation = 'UPSERT' AND last_payload_hash IS NOT NULL)
        OR
        (last_event_sequence = 0 AND last_payload_hash IS NULL)
    )
);

CREATE TABLE dianlian_context.lexical_chunk
(
    chunk_id                  CHAR(64)     PRIMARY KEY CHECK (chunk_id ~ '^[0-9a-f]{64}$'),
    fence_id                  BIGINT       NOT NULL REFERENCES dianlian_context.projection_fence (fence_id),
    authority_scope           VARCHAR(16)  NOT NULL CHECK (authority_scope IN ('PLATFORM', 'TENANT')),
    tenant_id                 UUID,
    resource_type             VARCHAR(40)  NOT NULL CHECK (resource_type IN (
        'KNOWLEDGE_DOCUMENT_VERSION', 'MEMORY_ITEM_VERSION'
    )),
    resource_id               UUID         NOT NULL,
    source_id                 UUID         NOT NULL,
    source_version            VARCHAR(200) NOT NULL,
    index_profile             VARCHAR(100) NOT NULL,
    event_sequence            BIGINT       NOT NULL CHECK (event_sequence > 0),
    chunk_ordinal             INTEGER      NOT NULL CHECK (chunk_ordinal >= 0),
    title                     VARCHAR(300) NOT NULL CHECK (BTRIM(title) <> ''),
    content                   TEXT         NOT NULL CHECK (BTRIM(content) <> ''),
    source_content_hash       VARCHAR(128) CHECK (
        source_content_hash IS NULL OR source_content_hash ~ '^[0-9a-f]{64,128}$'
    ),
    normalized_text_hash      CHAR(64)     NOT NULL CHECK (normalized_text_hash ~ '^[0-9a-f]{64}$'),
    normalization_profile_version VARCHAR(100) NOT NULL CHECK (
        normalization_profile_version ~ '^[a-z0-9][a-z0-9._-]{0,99}$'
    ),
    citation                  VARCHAR(1000) NOT NULL CHECK (BTRIM(citation) <> ''),
    enterprise_agent_id       UUID,
    memory_scope_type         VARCHAR(16)  CHECK (
        memory_scope_type IS NULL OR memory_scope_type IN ('AGENT', 'USER_AGENT', 'GROUP_AGENT')
    ),
    memory_scope_id           UUID,
    source_message_sequence_no BIGINT CHECK (source_message_sequence_no >= 0),
    search_document           TSVECTOR GENERATED ALWAYS AS (
        TO_TSVECTOR('simple', COALESCE(title, '') || ' ' || COALESCE(content, ''))
    ) STORED,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (fence_id, chunk_ordinal),
    CHECK (
        (resource_type = 'KNOWLEDGE_DOCUMENT_VERSION'
            AND source_content_hash IS NOT NULL
            AND enterprise_agent_id IS NULL
            AND memory_scope_type IS NULL
            AND memory_scope_id IS NULL
            AND source_message_sequence_no IS NULL)
        OR
        (resource_type = 'MEMORY_ITEM_VERSION'
            AND authority_scope = 'TENANT'
            AND tenant_id IS NOT NULL
            AND enterprise_agent_id IS NOT NULL
            AND memory_scope_type IS NOT NULL
            AND memory_scope_id IS NOT NULL)
    )
);

CREATE INDEX idx_context_lexical_chunk_search
    ON dianlian_context.lexical_chunk USING GIN (search_document);

CREATE INDEX idx_context_lexical_chunk_knowledge_allowlist
    ON dianlian_context.lexical_chunk
        (source_id, source_version, index_profile, authority_scope, tenant_id)
    WHERE resource_type = 'KNOWLEDGE_DOCUMENT_VERSION';

CREATE INDEX idx_context_lexical_chunk_memory_scope
    ON dianlian_context.lexical_chunk
        (tenant_id, enterprise_agent_id, memory_scope_type, memory_scope_id, index_profile)
    WHERE resource_type = 'MEMORY_ITEM_VERSION';

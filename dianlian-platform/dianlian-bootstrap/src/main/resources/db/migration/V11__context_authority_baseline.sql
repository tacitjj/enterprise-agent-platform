-- Knowledge and long-term-memory authority facts.
-- Retrieval indexes are rebuildable projections; these tables remain the source of truth.

INSERT INTO dianlian_business.iam_permission (permission_code, display_name, status)
VALUES
    ('platform.knowledge.read', '查看平台知识空间', 'ACTIVE'),
    ('platform.knowledge.manage', '管理平台知识空间', 'ACTIVE'),
    ('enterprise.knowledge.read', '查看企业授权知识', 'ACTIVE'),
    ('enterprise.knowledge.manage', '管理企业知识空间', 'ACTIVE'),
    ('memory.candidate.propose', '提出长期记忆候选', 'ACTIVE'),
    ('memory.recall', '召回已确认长期记忆', 'ACTIVE'),
    ('memory.self.manage', '管理个人与数字员工长期记忆', 'ACTIVE'),
    ('memory.group.manage', '管理群聊与数字员工长期记忆', 'ACTIVE'),
    ('enterprise.memory.govern', '治理企业数字员工长期记忆', 'ACTIVE')
ON CONFLICT (permission_code) DO NOTHING;

-- V7 created this unnamed CHECK with a PostgreSQL-truncated identifier. V8
-- attempted to drop the untruncated name, so existing databases can retain a
-- second constraint that still permits only NONE. Keep historical migrations
-- immutable and remove the exact legacy identifier here before knowledge
-- scopes become authoritative.
ALTER TABLE dianlian_business.enterprise_agent_configuration_version
    DROP CONSTRAINT IF EXISTS enterprise_agent_configuration_versi_knowledge_scope_mode_check;

CREATE SEQUENCE dianlian_business.context_event_sequence AS BIGINT START WITH 1;

ALTER TABLE dianlian_business.conversation_agent_binding
    ADD CONSTRAINT uq_conversation_agent_binding_tenant_identity
        UNIQUE (tenant_id, conversation_id, enterprise_agent_id);

CREATE OR REPLACE FUNCTION dianlian_business.protect_context_state_advance()
RETURNS TRIGGER AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'context authority facts use tombstones and cannot be deleted';
    END IF;
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
        RAISE EXCEPTION 'context authority tenant identity is immutable';
    END IF;
    IF NEW.state_version <> OLD.state_version + 1
        OR NEW.resource_version <> OLD.resource_version + 1 THEN
        RAISE EXCEPTION 'context authority state and resource versions must advance exactly once';
    END IF;
    IF NEW.event_sequence <= OLD.event_sequence THEN
        RAISE EXCEPTION 'context authority event sequence must increase';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION dianlian_business.reject_context_event_change()
RETURNS TRIGGER AS
$$
BEGIN
    RAISE EXCEPTION 'context events are append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TABLE dianlian_business.knowledge_space
(
    space_id          UUID         PRIMARY KEY,
    owner_scope       VARCHAR(16)  NOT NULL CHECK (owner_scope IN ('PLATFORM', 'TENANT')),
    tenant_id         UUID         REFERENCES dianlian_business.tenant (tenant_id),
    space_type        VARCHAR(32)  NOT NULL CHECK (space_type IN ('PLATFORM_TEMPLATE', 'ENTERPRISE')),
    space_code        VARCHAR(64)  NOT NULL CHECK (space_code ~ '^[A-Za-z][A-Za-z0-9._-]{0,63}$'),
    name              VARCHAR(200) NOT NULL CHECK (BTRIM(name) <> ''),
    description       VARCHAR(2000),
    status            VARCHAR(16)  NOT NULL CHECK (status IN ('DRAFT', 'ACTIVE', 'REVOKED', 'DELETED')),
    state_version     BIGINT       NOT NULL CHECK (state_version > 0),
    resource_version  BIGINT       NOT NULL CHECK (resource_version > 0),
    event_sequence    BIGINT       NOT NULL DEFAULT NEXTVAL('dianlian_business.context_event_sequence')
        CHECK (event_sequence > 0),
    created_by        UUID         NOT NULL REFERENCES dianlian_business.user_account (user_id),
    request_hash      VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key   VARCHAR(200) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at        TIMESTAMPTZ,
    deleted_at        TIMESTAMPTZ,
    deletion_reason   VARCHAR(500),
    UNIQUE (tenant_id, space_id),
    CHECK (
        (owner_scope = 'PLATFORM' AND tenant_id IS NULL AND space_type = 'PLATFORM_TEMPLATE')
        OR
        (owner_scope = 'TENANT' AND tenant_id IS NOT NULL AND space_type = 'ENTERPRISE')
    ),
    CHECK (
        (status IN ('DRAFT', 'ACTIVE') AND revoked_at IS NULL AND deleted_at IS NULL AND deletion_reason IS NULL)
        OR
        (status = 'REVOKED' AND revoked_at IS NOT NULL AND deleted_at IS NULL AND deletion_reason IS NOT NULL)
        OR
        (status = 'DELETED' AND deleted_at IS NOT NULL AND deletion_reason IS NOT NULL)
    )
);

CREATE UNIQUE INDEX uq_knowledge_space_platform_code
    ON dianlian_business.knowledge_space (space_code)
    WHERE owner_scope = 'PLATFORM';
CREATE UNIQUE INDEX uq_knowledge_space_tenant_code
    ON dianlian_business.knowledge_space (tenant_id, space_code)
    WHERE owner_scope = 'TENANT';
CREATE UNIQUE INDEX uq_knowledge_space_platform_idempotency
    ON dianlian_business.knowledge_space (created_by, idempotency_key)
    WHERE owner_scope = 'PLATFORM';
CREATE UNIQUE INDEX uq_knowledge_space_tenant_idempotency
    ON dianlian_business.knowledge_space (tenant_id, created_by, idempotency_key)
    WHERE owner_scope = 'TENANT';
CREATE INDEX idx_knowledge_space_tenant_status
    ON dianlian_business.knowledge_space (tenant_id, status, name, space_id);

CREATE TRIGGER trg_knowledge_space_state_advance
    BEFORE UPDATE OR DELETE ON dianlian_business.knowledge_space
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_context_state_advance();

CREATE TABLE dianlian_business.knowledge_document
(
    document_id        UUID         PRIMARY KEY,
    space_id           UUID         NOT NULL REFERENCES dianlian_business.knowledge_space (space_id),
    tenant_id          UUID         REFERENCES dianlian_business.tenant (tenant_id),
    title              VARCHAR(500) NOT NULL CHECK (BTRIM(title) <> ''),
    source_type        VARCHAR(32)  NOT NULL CHECK (source_type IN ('UPLOAD', 'URL', 'API', 'ADMIN_IMPORT')),
    external_source_key VARCHAR(500),
    status             VARCHAR(16)  NOT NULL CHECK (status IN ('DRAFT', 'PROCESSING', 'READY', 'REVOKED', 'DELETED')),
    current_version_id UUID,
    state_version      BIGINT       NOT NULL CHECK (state_version > 0),
    resource_version   BIGINT       NOT NULL CHECK (resource_version > 0),
    event_sequence     BIGINT       NOT NULL DEFAULT NEXTVAL('dianlian_business.context_event_sequence')
        CHECK (event_sequence > 0),
    created_by         UUID         NOT NULL REFERENCES dianlian_business.user_account (user_id),
    request_hash       VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key    VARCHAR(200) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at         TIMESTAMPTZ,
    deleted_at         TIMESTAMPTZ,
    deletion_reason    VARCHAR(500),
    UNIQUE (space_id, document_id),
    UNIQUE (tenant_id, document_id),
    CHECK (
        (status IN ('DRAFT', 'PROCESSING', 'READY') AND revoked_at IS NULL AND deleted_at IS NULL)
        OR
        (status = 'REVOKED' AND revoked_at IS NOT NULL AND deleted_at IS NULL AND deletion_reason IS NOT NULL)
        OR
        (status = 'DELETED' AND deleted_at IS NOT NULL AND deletion_reason IS NOT NULL)
    )
);

CREATE INDEX idx_knowledge_document_space_status
    ON dianlian_business.knowledge_document (space_id, status, updated_at DESC, document_id);
CREATE UNIQUE INDEX uq_knowledge_document_external_source
    ON dianlian_business.knowledge_document (space_id, external_source_key)
    WHERE external_source_key IS NOT NULL AND status <> 'DELETED';
CREATE UNIQUE INDEX uq_knowledge_document_platform_idempotency
    ON dianlian_business.knowledge_document (created_by, idempotency_key)
    WHERE tenant_id IS NULL;
CREATE UNIQUE INDEX uq_knowledge_document_tenant_idempotency
    ON dianlian_business.knowledge_document (tenant_id, created_by, idempotency_key)
    WHERE tenant_id IS NOT NULL;

CREATE OR REPLACE FUNCTION dianlian_business.assert_knowledge_document_partition()
RETURNS TRIGGER AS
$$
DECLARE
    target_tenant UUID;
BEGIN
    SELECT tenant_id INTO target_tenant
      FROM dianlian_business.knowledge_space
     WHERE space_id = NEW.space_id;
    IF NOT FOUND OR NEW.tenant_id IS DISTINCT FROM target_tenant THEN
        RAISE EXCEPTION 'knowledge document tenant must match its space owner';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_knowledge_document_partition
    BEFORE INSERT OR UPDATE OF space_id, tenant_id ON dianlian_business.knowledge_document
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_knowledge_document_partition();
CREATE TRIGGER trg_knowledge_document_state_advance
    BEFORE UPDATE OR DELETE ON dianlian_business.knowledge_document
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_context_state_advance();

CREATE TABLE dianlian_business.knowledge_document_version
(
    document_version_id UUID          PRIMARY KEY,
    document_id         UUID          NOT NULL,
    space_id            UUID          NOT NULL,
    tenant_id           UUID          REFERENCES dianlian_business.tenant (tenant_id),
    version_no          BIGINT        NOT NULL CHECK (version_no > 0),
    object_key          VARCHAR(1024) NOT NULL CHECK (BTRIM(object_key) <> ''),
    content_hash        VARCHAR(128)  NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64,128}$'),
    normalized_text     TEXT,
    mime_type           VARCHAR(200)  NOT NULL CHECK (BTRIM(mime_type) <> ''),
    byte_size           BIGINT        NOT NULL CHECK (byte_size >= 0),
    metadata            JSONB         NOT NULL DEFAULT '{}'::JSONB CHECK (JSONB_TYPEOF(metadata) = 'object'),
    status              VARCHAR(16)   NOT NULL CHECK (status IN ('DRAFT', 'PUBLISHED', 'SUPERSEDED')),
    access_state        VARCHAR(16)   NOT NULL CHECK (access_state IN ('ACTIVE', 'REVOKED', 'DELETED')),
    index_state         VARCHAR(24)   NOT NULL CHECK (index_state IN (
        'PENDING', 'INDEXING', 'READY', 'FAILED', 'DELETE_PENDING', 'DELETED'
    )),
    state_version       BIGINT        NOT NULL CHECK (state_version > 0),
    resource_version    BIGINT        NOT NULL CHECK (resource_version > 0),
    event_sequence      BIGINT        NOT NULL DEFAULT NEXTVAL('dianlian_business.context_event_sequence')
        CHECK (event_sequence > 0),
    created_by          UUID          NOT NULL REFERENCES dianlian_business.user_account (user_id),
    request_hash        VARCHAR(128)  NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key     VARCHAR(200)  NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    purged_at           TIMESTAMPTZ,
    FOREIGN KEY (space_id, document_id)
        REFERENCES dianlian_business.knowledge_document (space_id, document_id),
    UNIQUE (document_id, version_no),
    UNIQUE (document_id, document_version_id),
    UNIQUE (tenant_id, document_version_id),
    CHECK (
        (access_state <> 'DELETED' AND purged_at IS NULL)
        OR
        (access_state = 'DELETED' AND purged_at IS NOT NULL AND normalized_text IS NULL)
    ),
    CHECK (
        (access_state = 'ACTIVE' AND index_state IN ('PENDING', 'INDEXING', 'READY', 'FAILED'))
        OR
        (access_state = 'REVOKED' AND index_state IN ('DELETE_PENDING', 'DELETED'))
        OR
        (access_state = 'DELETED' AND index_state = 'DELETED')
    )
);

CREATE INDEX idx_knowledge_document_version_document
    ON dianlian_business.knowledge_document_version (document_id, version_no DESC);
CREATE INDEX idx_knowledge_document_version_index_queue
    ON dianlian_business.knowledge_document_version (index_state, event_sequence)
    WHERE index_state IN ('PENDING', 'FAILED', 'DELETE_PENDING');
CREATE UNIQUE INDEX uq_knowledge_document_version_platform_idempotency
    ON dianlian_business.knowledge_document_version (created_by, idempotency_key)
    WHERE tenant_id IS NULL;
CREATE UNIQUE INDEX uq_knowledge_document_version_tenant_idempotency
    ON dianlian_business.knowledge_document_version (tenant_id, created_by, idempotency_key)
    WHERE tenant_id IS NOT NULL;

CREATE OR REPLACE FUNCTION dianlian_business.assert_knowledge_document_version_partition()
RETURNS TRIGGER AS
$$
DECLARE
    document_tenant UUID;
BEGIN
    SELECT tenant_id INTO document_tenant
      FROM dianlian_business.knowledge_document
     WHERE document_id = NEW.document_id
       AND space_id = NEW.space_id;
    IF NOT FOUND OR NEW.tenant_id IS DISTINCT FROM document_tenant THEN
        RAISE EXCEPTION 'knowledge document version tenant must match its document';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_knowledge_document_version_partition
    BEFORE INSERT OR UPDATE OF document_id, space_id, tenant_id
    ON dianlian_business.knowledge_document_version
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_knowledge_document_version_partition();
CREATE TRIGGER trg_knowledge_document_version_state_advance
    BEFORE UPDATE OR DELETE ON dianlian_business.knowledge_document_version
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_context_state_advance();

ALTER TABLE dianlian_business.knowledge_document
    ADD CONSTRAINT fk_knowledge_document_current_version
        FOREIGN KEY (document_id, current_version_id)
        REFERENCES dianlian_business.knowledge_document_version (document_id, document_version_id)
        DEFERRABLE INITIALLY DEFERRED;

CREATE OR REPLACE FUNCTION dianlian_business.protect_knowledge_version_content()
RETURNS TRIGGER AS
$$
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
    IF NEW.normalized_text IS DISTINCT FROM OLD.normalized_text
        AND NOT (OLD.normalized_text IS NOT NULL
            AND NEW.normalized_text IS NULL
            AND NEW.access_state = 'DELETED'
            AND NEW.purged_at IS NOT NULL) THEN
        RAISE EXCEPTION 'normalized knowledge text can only be purged after deletion';
    END IF;
    IF OLD.access_state = 'DELETED' AND NEW.access_state <> 'DELETED' THEN
        RAISE EXCEPTION 'deleted knowledge versions cannot be restored';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_knowledge_document_version_content
    BEFORE UPDATE OR DELETE ON dianlian_business.knowledge_document_version
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_knowledge_version_content();

CREATE TABLE dianlian_business.knowledge_acl
(
    acl_id           UUID         PRIMARY KEY,
    space_id         UUID         NOT NULL REFERENCES dianlian_business.knowledge_space (space_id),
    tenant_id        UUID         NOT NULL REFERENCES dianlian_business.tenant (tenant_id),
    audience_type    VARCHAR(16)  NOT NULL CHECK (audience_type IN ('TENANT', 'USER')),
    audience_id      UUID         NOT NULL,
    access_level     VARCHAR(16)  NOT NULL CHECK (access_level IN ('READ', 'MANAGE')),
    status           VARCHAR(16)  NOT NULL CHECK (status IN ('ACTIVE', 'REVOKED')),
    state_version    BIGINT       NOT NULL CHECK (state_version > 0),
    resource_version BIGINT       NOT NULL CHECK (resource_version > 0),
    event_sequence   BIGINT       NOT NULL DEFAULT NEXTVAL('dianlian_business.context_event_sequence')
        CHECK (event_sequence > 0),
    request_hash     VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key  VARCHAR(200) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    granted_by       UUID         NOT NULL REFERENCES dianlian_business.user_account (user_id),
    granted_at       TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valid_until      TIMESTAMPTZ,
    revoked_by       UUID         REFERENCES dianlian_business.user_account (user_id),
    revoked_at       TIMESTAMPTZ,
    UNIQUE (tenant_id, granted_by, idempotency_key),
    UNIQUE (tenant_id, acl_id),
    CHECK ((audience_type = 'TENANT' AND audience_id = tenant_id) OR audience_type = 'USER'),
    CHECK (valid_until IS NULL OR valid_until > granted_at),
    CHECK (
        (status = 'ACTIVE' AND revoked_by IS NULL AND revoked_at IS NULL)
        OR
        (status = 'REVOKED' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX uq_knowledge_acl_active
    ON dianlian_business.knowledge_acl (space_id, tenant_id, audience_type, audience_id, access_level)
    WHERE status = 'ACTIVE';
CREATE INDEX idx_knowledge_acl_audience_active
    ON dianlian_business.knowledge_acl (tenant_id, audience_type, audience_id, space_id)
    WHERE status = 'ACTIVE';

CREATE OR REPLACE FUNCTION dianlian_business.assert_knowledge_acl_partition()
RETURNS TRIGGER AS
$$
DECLARE
    owner_tenant UUID;
BEGIN
    SELECT tenant_id INTO owner_tenant
      FROM dianlian_business.knowledge_space
     WHERE space_id = NEW.space_id;
    IF NOT FOUND OR (owner_tenant IS NOT NULL AND owner_tenant <> NEW.tenant_id) THEN
        RAISE EXCEPTION 'tenant-owned knowledge cannot be granted across tenants';
    END IF;
    IF NEW.audience_type = 'USER' AND NOT EXISTS (
        SELECT 1
          FROM dianlian_business.tenant_member member
         WHERE member.tenant_id = NEW.tenant_id
           AND member.user_id = NEW.audience_id
    ) THEN
        RAISE EXCEPTION 'knowledge user audience must belong to the grantee tenant';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_knowledge_acl_partition
    BEFORE INSERT OR UPDATE OF space_id, tenant_id, audience_type, audience_id
    ON dianlian_business.knowledge_acl
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_knowledge_acl_partition();
CREATE TRIGGER trg_knowledge_acl_state_advance
    BEFORE UPDATE OR DELETE ON dianlian_business.knowledge_acl
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_context_state_advance();

CREATE TABLE dianlian_business.agent_version_knowledge_space
(
    binding_id       UUID         PRIMARY KEY,
    tenant_id        UUID         CHECK (tenant_id IS NULL),
    agent_template_id UUID        NOT NULL,
    agent_version_id UUID         NOT NULL,
    space_id         UUID         NOT NULL REFERENCES dianlian_business.knowledge_space (space_id),
    status           VARCHAR(16)  NOT NULL CHECK (status IN ('ACTIVE', 'REVOKED')),
    state_version    BIGINT       NOT NULL CHECK (state_version > 0),
    resource_version BIGINT       NOT NULL CHECK (resource_version > 0),
    event_sequence   BIGINT       NOT NULL DEFAULT NEXTVAL('dianlian_business.context_event_sequence')
        CHECK (event_sequence > 0),
    request_hash     VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key  VARCHAR(200) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    created_by       UUID         NOT NULL REFERENCES dianlian_business.user_account (user_id),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at       TIMESTAMPTZ,
    FOREIGN KEY (agent_template_id, agent_version_id)
        REFERENCES dianlian_business.agent_version (agent_template_id, agent_version_id),
    UNIQUE (created_by, idempotency_key),
    CHECK ((status = 'ACTIVE' AND revoked_at IS NULL) OR (status = 'REVOKED' AND revoked_at IS NOT NULL))
);

CREATE UNIQUE INDEX uq_agent_version_knowledge_space_active
    ON dianlian_business.agent_version_knowledge_space (agent_version_id, space_id)
    WHERE status = 'ACTIVE';

CREATE OR REPLACE FUNCTION dianlian_business.assert_platform_knowledge_binding()
RETURNS TRIGGER AS
$$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM dianlian_business.knowledge_space space
         WHERE space.space_id = NEW.space_id
           AND space.owner_scope = 'PLATFORM'
           AND space.tenant_id IS NULL
    ) THEN
        RAISE EXCEPTION 'agent template versions can only bind platform knowledge spaces';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_agent_version_knowledge_space_partition
    BEFORE INSERT OR UPDATE OF space_id ON dianlian_business.agent_version_knowledge_space
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_platform_knowledge_binding();
CREATE TRIGGER trg_agent_version_knowledge_space_state_advance
    BEFORE UPDATE OR DELETE ON dianlian_business.agent_version_knowledge_space
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_context_state_advance();

CREATE TABLE dianlian_business.enterprise_agent_configuration_knowledge_space
(
    binding_id               UUID         PRIMARY KEY,
    tenant_id                UUID         NOT NULL REFERENCES dianlian_business.tenant (tenant_id),
    enterprise_agent_id      UUID         NOT NULL,
    configuration_version_id UUID         NOT NULL,
    space_id                 UUID         NOT NULL,
    status                   VARCHAR(16)  NOT NULL CHECK (status IN ('ACTIVE', 'REVOKED')),
    state_version            BIGINT       NOT NULL CHECK (state_version > 0),
    resource_version         BIGINT       NOT NULL CHECK (resource_version > 0),
    event_sequence           BIGINT       NOT NULL DEFAULT NEXTVAL('dianlian_business.context_event_sequence')
        CHECK (event_sequence > 0),
    request_hash             VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key          VARCHAR(200) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    created_by               UUID         NOT NULL,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at               TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, enterprise_agent_id, configuration_version_id)
        REFERENCES dianlian_business.enterprise_agent_configuration_version
            (tenant_id, enterprise_agent_id, configuration_version_id),
    FOREIGN KEY (tenant_id, space_id)
        REFERENCES dianlian_business.knowledge_space (tenant_id, space_id),
    FOREIGN KEY (tenant_id, created_by)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    UNIQUE (tenant_id, created_by, idempotency_key),
    UNIQUE (tenant_id, binding_id),
    CHECK ((status = 'ACTIVE' AND revoked_at IS NULL) OR (status = 'REVOKED' AND revoked_at IS NOT NULL))
);

CREATE UNIQUE INDEX uq_enterprise_configuration_knowledge_space_active
    ON dianlian_business.enterprise_agent_configuration_knowledge_space
        (tenant_id, enterprise_agent_id, configuration_version_id, space_id)
    WHERE status = 'ACTIVE';

CREATE TRIGGER trg_enterprise_configuration_knowledge_space_state_advance
    BEFORE UPDATE OR DELETE ON dianlian_business.enterprise_agent_configuration_knowledge_space
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_context_state_advance();

CREATE TABLE dianlian_business.knowledge_event
(
    event_sequence   BIGINT       PRIMARY KEY DEFAULT NEXTVAL('dianlian_business.context_event_sequence'),
    event_id         UUID         NOT NULL UNIQUE,
    tenant_id        UUID         REFERENCES dianlian_business.tenant (tenant_id),
    aggregate_type   VARCHAR(48)  NOT NULL CHECK (aggregate_type IN (
        'SPACE', 'DOCUMENT', 'DOCUMENT_VERSION', 'ACL',
        'AGENT_VERSION_BINDING', 'ENTERPRISE_CONFIGURATION_BINDING'
    )),
    aggregate_id     UUID         NOT NULL,
    event_type       VARCHAR(64)  NOT NULL CHECK (BTRIM(event_type) <> ''),
    resource_version BIGINT       NOT NULL CHECK (resource_version > 0),
    actor_id         UUID         NOT NULL REFERENCES dianlian_business.user_account (user_id),
    request_hash     VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key  VARCHAR(200) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    payload          JSONB        NOT NULL CHECK (JSONB_TYPEOF(payload) = 'object'),
    occurred_at      TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, actor_id, event_type, idempotency_key),
    UNIQUE (aggregate_type, aggregate_id, resource_version)
);

CREATE INDEX idx_knowledge_event_aggregate
    ON dianlian_business.knowledge_event (aggregate_type, aggregate_id, event_sequence);
CREATE TRIGGER trg_knowledge_event_immutable
    BEFORE UPDATE OR DELETE ON dianlian_business.knowledge_event
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.reject_context_event_change();

CREATE UNIQUE INDEX uq_knowledge_event_platform_idempotency
    ON dianlian_business.knowledge_event (actor_id, event_type, idempotency_key)
    WHERE tenant_id IS NULL;

CREATE TABLE dianlian_business.ai_memory_candidate
(
    candidate_id                UUID         PRIMARY KEY,
    tenant_id                   UUID         NOT NULL REFERENCES dianlian_business.tenant (tenant_id),
    enterprise_agent_id         UUID         NOT NULL,
    scope_type                  VARCHAR(16)  NOT NULL CHECK (scope_type IN ('AGENT', 'USER_AGENT', 'GROUP_AGENT')),
    scope_id                    UUID         NOT NULL,
    content                     TEXT         NOT NULL CHECK (BTRIM(content) <> '' AND CHAR_LENGTH(content) <= 8000),
    semantic_key                VARCHAR(200),
    source_conversation_id      UUID,
    source_message_id           UUID,
    status                      VARCHAR(16)  NOT NULL CHECK (status IN ('PENDING', 'CONFIRMED', 'REJECTED')),
    request_hash                VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key             VARCHAR(160) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    proposed_by                 UUID         NOT NULL,
    proposed_at                 TIMESTAMPTZ  NOT NULL,
    decided_by                  UUID,
    decided_at                  TIMESTAMPTZ,
    decision_reason             VARCHAR(1000),
    decision_request_hash       VARCHAR(128),
    decision_idempotency_key    VARCHAR(160),
    confirmed_memory_id         UUID,
    state_version               BIGINT       NOT NULL DEFAULT 1 CHECK (state_version > 0),
    resource_version            BIGINT       NOT NULL DEFAULT 1 CHECK (resource_version > 0),
    event_sequence              BIGINT       NOT NULL DEFAULT NEXTVAL('dianlian_business.context_event_sequence')
        CHECK (event_sequence > 0),
    updated_at                  TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id, enterprise_agent_id)
        REFERENCES dianlian_business.enterprise_agent (tenant_id, enterprise_agent_id),
    FOREIGN KEY (tenant_id, proposed_by)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    FOREIGN KEY (tenant_id, decided_by)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    FOREIGN KEY (tenant_id, source_conversation_id, source_message_id)
        REFERENCES dianlian_business.conversation_message (tenant_id, conversation_id, message_id),
    UNIQUE (tenant_id, candidate_id),
    UNIQUE (tenant_id, proposed_by, idempotency_key),
    CHECK (source_message_id IS NULL OR source_conversation_id IS NOT NULL),
    CHECK (
        (status = 'PENDING'
            AND decided_by IS NULL AND decided_at IS NULL AND decision_reason IS NULL
            AND decision_request_hash IS NULL AND decision_idempotency_key IS NULL
            AND confirmed_memory_id IS NULL)
        OR
        (status = 'CONFIRMED'
            AND decided_by IS NOT NULL AND decided_at IS NOT NULL
            AND decision_request_hash IS NOT NULL AND decision_idempotency_key IS NOT NULL
            AND confirmed_memory_id IS NOT NULL)
        OR
        (status = 'REJECTED'
            AND decided_by IS NOT NULL AND decided_at IS NOT NULL AND decision_reason IS NOT NULL
            AND decision_request_hash IS NOT NULL AND decision_idempotency_key IS NOT NULL
            AND confirmed_memory_id IS NULL)
    )
);

CREATE UNIQUE INDEX uq_ai_memory_candidate_decision_idempotency
    ON dianlian_business.ai_memory_candidate (tenant_id, decided_by, decision_idempotency_key)
    WHERE decision_idempotency_key IS NOT NULL;
CREATE INDEX idx_ai_memory_candidate_pending
    ON dianlian_business.ai_memory_candidate (tenant_id, enterprise_agent_id, scope_type, scope_id, proposed_at)
    WHERE status = 'PENDING';

CREATE OR REPLACE FUNCTION dianlian_business.assert_ai_memory_scope()
RETURNS TRIGGER AS
$$
BEGIN
    IF NEW.scope_type = 'AGENT' THEN
        IF NEW.scope_id <> NEW.enterprise_agent_id THEN
            RAISE EXCEPTION 'AGENT memory scope must identify the same enterprise agent';
        END IF;
    ELSIF NEW.scope_type = 'USER_AGENT' THEN
        IF NOT EXISTS (
            SELECT 1 FROM dianlian_business.tenant_member member
             WHERE member.tenant_id = NEW.tenant_id
               AND member.user_id = NEW.scope_id
        ) THEN
            RAISE EXCEPTION 'USER_AGENT memory scope must identify a member of the same tenant';
        END IF;
    ELSIF NEW.scope_type = 'GROUP_AGENT' THEN
        IF NOT EXISTS (
            SELECT 1 FROM dianlian_business.conversation_agent_binding binding
             WHERE binding.tenant_id = NEW.tenant_id
               AND binding.conversation_id = NEW.scope_id
               AND binding.enterprise_agent_id = NEW.enterprise_agent_id
               AND binding.status = 'ACTIVE'
        ) THEN
            RAISE EXCEPTION 'GROUP_AGENT memory scope requires an active same-tenant conversation binding';
        END IF;
    ELSE
        RAISE EXCEPTION 'unsupported active long-term memory scope';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ai_memory_candidate_scope
    BEFORE INSERT OR UPDATE OF tenant_id, enterprise_agent_id, scope_type, scope_id
    ON dianlian_business.ai_memory_candidate
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_ai_memory_scope();

CREATE OR REPLACE FUNCTION dianlian_business.protect_ai_memory_candidate()
RETURNS TRIGGER AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'memory candidate facts cannot be deleted';
    END IF;
    IF OLD.status <> 'PENDING' OR NEW.status NOT IN ('CONFIRMED', 'REJECTED')
        OR NEW.candidate_id IS DISTINCT FROM OLD.candidate_id
        OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
        OR NEW.enterprise_agent_id IS DISTINCT FROM OLD.enterprise_agent_id
        OR NEW.scope_type IS DISTINCT FROM OLD.scope_type
        OR NEW.scope_id IS DISTINCT FROM OLD.scope_id
        OR NEW.content IS DISTINCT FROM OLD.content
        OR NEW.semantic_key IS DISTINCT FROM OLD.semantic_key
        OR NEW.source_conversation_id IS DISTINCT FROM OLD.source_conversation_id
        OR NEW.source_message_id IS DISTINCT FROM OLD.source_message_id
        OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
        OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
        OR NEW.proposed_by IS DISTINCT FROM OLD.proposed_by
        OR NEW.proposed_at IS DISTINCT FROM OLD.proposed_at THEN
        RAISE EXCEPTION 'memory candidate can only transition once from pending to a terminal decision';
    END IF;
    NEW.state_version := OLD.state_version + 1;
    NEW.resource_version := OLD.resource_version + 1;
    NEW.event_sequence := NEXTVAL('dianlian_business.context_event_sequence');
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ai_memory_candidate_immutable
    BEFORE UPDATE OR DELETE ON dianlian_business.ai_memory_candidate
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_ai_memory_candidate();

CREATE TABLE dianlian_business.ai_memory_item
(
    memory_id              UUID         PRIMARY KEY,
    tenant_id              UUID         NOT NULL REFERENCES dianlian_business.tenant (tenant_id),
    enterprise_agent_id    UUID         NOT NULL,
    scope_type             VARCHAR(16)  NOT NULL CHECK (scope_type IN ('AGENT', 'USER_AGENT', 'GROUP_AGENT')),
    scope_id               UUID         NOT NULL,
    status                 VARCHAR(16)  NOT NULL CHECK (status IN ('ACTIVE', 'FORGOTTEN')),
    current_version        BIGINT       NOT NULL CHECK (current_version > 0),
    created_by             UUID         NOT NULL,
    created_at             TIMESTAMPTZ  NOT NULL,
    updated_at             TIMESTAMPTZ  NOT NULL,
    forgotten_by           UUID,
    forgotten_at           TIMESTAMPTZ,
    forget_reason          VARCHAR(1000),
    forget_request_hash    VARCHAR(128),
    forget_idempotency_key VARCHAR(160),
    state_version          BIGINT       NOT NULL DEFAULT 1 CHECK (state_version > 0),
    resource_version       BIGINT       NOT NULL DEFAULT 1 CHECK (resource_version > 0),
    event_sequence         BIGINT       NOT NULL DEFAULT NEXTVAL('dianlian_business.context_event_sequence')
        CHECK (event_sequence > 0),
    FOREIGN KEY (tenant_id, enterprise_agent_id)
        REFERENCES dianlian_business.enterprise_agent (tenant_id, enterprise_agent_id),
    FOREIGN KEY (tenant_id, created_by)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    FOREIGN KEY (tenant_id, forgotten_by)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    UNIQUE (tenant_id, memory_id),
    CHECK (
        (status = 'ACTIVE' AND forgotten_by IS NULL AND forgotten_at IS NULL
            AND forget_reason IS NULL AND forget_request_hash IS NULL AND forget_idempotency_key IS NULL)
        OR
        (status = 'FORGOTTEN' AND forgotten_by IS NOT NULL AND forgotten_at IS NOT NULL
            AND forget_reason IS NOT NULL AND forget_request_hash IS NOT NULL AND forget_idempotency_key IS NOT NULL)
    )
);

CREATE UNIQUE INDEX uq_ai_memory_item_forget_idempotency
    ON dianlian_business.ai_memory_item (tenant_id, forgotten_by, forget_idempotency_key)
    WHERE forget_idempotency_key IS NOT NULL;
CREATE INDEX idx_ai_memory_item_recall
    ON dianlian_business.ai_memory_item
        (tenant_id, enterprise_agent_id, scope_type, scope_id, updated_at DESC, memory_id)
    WHERE status = 'ACTIVE';

CREATE TRIGGER trg_ai_memory_item_scope
    BEFORE INSERT OR UPDATE OF tenant_id, enterprise_agent_id, scope_type, scope_id
    ON dianlian_business.ai_memory_item
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_ai_memory_scope();

CREATE OR REPLACE FUNCTION dianlian_business.protect_ai_memory_item()
RETURNS TRIGGER AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'memory items use forgotten tombstones and cannot be deleted';
    END IF;
    IF NEW.memory_id IS DISTINCT FROM OLD.memory_id
        OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
        OR NEW.enterprise_agent_id IS DISTINCT FROM OLD.enterprise_agent_id
        OR NEW.scope_type IS DISTINCT FROM OLD.scope_type
        OR NEW.scope_id IS DISTINCT FROM OLD.scope_id
        OR NEW.created_by IS DISTINCT FROM OLD.created_by
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'memory item identity is immutable';
    END IF;
    IF OLD.status = 'ACTIVE' AND NEW.status = 'ACTIVE' THEN
        IF NEW.current_version <> OLD.current_version + 1
            OR NEW.forgotten_by IS NOT NULL OR NEW.forgotten_at IS NOT NULL THEN
            RAISE EXCEPTION 'active memory updates must advance exactly one content version';
        END IF;
    ELSIF OLD.status = 'ACTIVE' AND NEW.status = 'FORGOTTEN' THEN
        IF NEW.current_version <> OLD.current_version
            OR NEW.forgotten_by IS NULL OR NEW.forgotten_at IS NULL
            OR NEW.forget_reason IS NULL OR NEW.forget_request_hash IS NULL
            OR NEW.forget_idempotency_key IS NULL THEN
            RAISE EXCEPTION 'forgetting memory requires a complete tombstone without changing content version';
        END IF;
    ELSE
        RAISE EXCEPTION 'forgotten memory cannot be changed or restored';
    END IF;
    NEW.state_version := OLD.state_version + 1;
    NEW.resource_version := OLD.resource_version + 1;
    NEW.event_sequence := NEXTVAL('dianlian_business.context_event_sequence');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ai_memory_item_immutable
    BEFORE UPDATE OR DELETE ON dianlian_business.ai_memory_item
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_ai_memory_item();

CREATE TABLE dianlian_business.ai_memory_version
(
    memory_id          UUID         NOT NULL,
    tenant_id          UUID         NOT NULL,
    version_no         BIGINT       NOT NULL CHECK (version_no > 0),
    content            TEXT         NOT NULL CHECK (BTRIM(content) <> '' AND CHAR_LENGTH(content) <= 8000),
    semantic_key       VARCHAR(200),
    source_candidate_id UUID,
    change_type        VARCHAR(16)  NOT NULL CHECK (change_type IN ('CONFIRMED', 'CORRECTED')),
    reason             VARCHAR(1000) CHECK (reason IS NULL OR BTRIM(reason) <> ''),
    request_hash       VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key    VARCHAR(160) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    created_by         UUID         NOT NULL,
    created_at         TIMESTAMPTZ  NOT NULL,
    resource_version   BIGINT       NOT NULL DEFAULT 1 CHECK (resource_version > 0),
    event_sequence     BIGINT       NOT NULL DEFAULT NEXTVAL('dianlian_business.context_event_sequence')
        CHECK (event_sequence > 0),
    PRIMARY KEY (memory_id, version_no),
    FOREIGN KEY (tenant_id, memory_id)
        REFERENCES dianlian_business.ai_memory_item (tenant_id, memory_id),
    FOREIGN KEY (tenant_id, source_candidate_id)
        REFERENCES dianlian_business.ai_memory_candidate (tenant_id, candidate_id),
    FOREIGN KEY (tenant_id, created_by)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    UNIQUE (tenant_id, memory_id, version_no),
    UNIQUE (tenant_id, created_by, change_type, idempotency_key),
    CHECK ((change_type = 'CONFIRMED' AND version_no = 1 AND source_candidate_id IS NOT NULL)
        OR (change_type = 'CORRECTED' AND version_no > 1 AND reason IS NOT NULL))
);

CREATE INDEX idx_ai_memory_version_history
    ON dianlian_business.ai_memory_version (tenant_id, memory_id, version_no DESC);

ALTER TABLE dianlian_business.ai_memory_item
    ADD CONSTRAINT fk_ai_memory_item_current_version
        FOREIGN KEY (tenant_id, memory_id, current_version)
        REFERENCES dianlian_business.ai_memory_version (tenant_id, memory_id, version_no)
        DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE dianlian_business.ai_memory_candidate
    ADD CONSTRAINT fk_ai_memory_candidate_confirmed_memory
        FOREIGN KEY (tenant_id, confirmed_memory_id)
        REFERENCES dianlian_business.ai_memory_item (tenant_id, memory_id)
        DEFERRABLE INITIALLY DEFERRED;

CREATE TRIGGER trg_ai_memory_version_immutable
    BEFORE UPDATE OR DELETE ON dianlian_business.ai_memory_version
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.reject_context_event_change();

CREATE TABLE dianlian_business.ai_memory_event
(
    event_sequence      BIGINT       NOT NULL DEFAULT NEXTVAL('dianlian_business.context_event_sequence'),
    event_id            UUID         PRIMARY KEY,
    tenant_id           UUID         NOT NULL REFERENCES dianlian_business.tenant (tenant_id),
    enterprise_agent_id UUID         NOT NULL,
    scope_type          VARCHAR(16)  NOT NULL CHECK (scope_type IN ('AGENT', 'USER_AGENT', 'GROUP_AGENT')),
    scope_id            UUID         NOT NULL,
    event_type          VARCHAR(32)  NOT NULL CHECK (event_type IN (
        'CANDIDATE_PROPOSED', 'CANDIDATE_CONFIRMED', 'CANDIDATE_REJECTED',
        'MEMORY_CORRECTED', 'MEMORY_FORGOTTEN'
    )),
    candidate_id        UUID,
    memory_id           UUID,
    resulting_version   BIGINT,
    from_status         VARCHAR(16),
    to_status           VARCHAR(16),
    reason              VARCHAR(1000),
    request_hash        VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key     VARCHAR(160) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    actor_id            UUID         NOT NULL,
    occurred_at         TIMESTAMPTZ  NOT NULL,
    resource_version    BIGINT       GENERATED ALWAYS AS (COALESCE(resulting_version, 1)) STORED,
    payload             JSONB        NOT NULL DEFAULT '{}'::JSONB CHECK (JSONB_TYPEOF(payload) = 'object'),
    FOREIGN KEY (tenant_id, enterprise_agent_id)
        REFERENCES dianlian_business.enterprise_agent (tenant_id, enterprise_agent_id),
    FOREIGN KEY (tenant_id, candidate_id)
        REFERENCES dianlian_business.ai_memory_candidate (tenant_id, candidate_id),
    FOREIGN KEY (tenant_id, memory_id)
        REFERENCES dianlian_business.ai_memory_item (tenant_id, memory_id),
    FOREIGN KEY (tenant_id, actor_id)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    UNIQUE (event_sequence),
    UNIQUE (tenant_id, actor_id, event_type, idempotency_key)
);

CREATE INDEX idx_ai_memory_event_scope
    ON dianlian_business.ai_memory_event
        (tenant_id, enterprise_agent_id, scope_type, scope_id, event_sequence);
CREATE TRIGGER trg_ai_memory_event_scope
    BEFORE INSERT ON dianlian_business.ai_memory_event
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_ai_memory_scope();
CREATE TRIGGER trg_ai_memory_event_immutable
    BEFORE UPDATE OR DELETE ON dianlian_business.ai_memory_event
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.reject_context_event_change();

CREATE TABLE dianlian_business.context_index_job
(
    job_id            UUID          PRIMARY KEY,
    tenant_id         UUID          REFERENCES dianlian_business.tenant (tenant_id),
    authority_scope   VARCHAR(16)   NOT NULL CHECK (authority_scope IN ('PLATFORM', 'TENANT')),
    resource_type     VARCHAR(40)   NOT NULL CHECK (resource_type IN (
        'KNOWLEDGE_DOCUMENT_VERSION', 'MEMORY_ITEM_VERSION'
    )),
    resource_id       UUID          NOT NULL,
    resource_version  BIGINT        NOT NULL CHECK (resource_version > 0),
    event_sequence    BIGINT        NOT NULL CHECK (event_sequence > 0),
    index_target      VARCHAR(32)   NOT NULL CHECK (index_target IN (
        'LEXICAL', 'VECTOR', 'GRAPH', 'CACHE', 'EXTERNAL_PROVIDER'
    )),
    operation         VARCHAR(16)   NOT NULL CHECK (operation IN ('UPSERT', 'DELETE', 'VERIFY')),
    status            VARCHAR(16)   NOT NULL CHECK (status IN (
        'PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'DEAD_LETTER'
    )),
    attempt_count     INTEGER       NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at   TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lease_owner       VARCHAR(160),
    lease_expires_at  TIMESTAMPTZ,
    last_error_code   VARCHAR(100),
    last_error_message VARCHAR(2000),
    remote_receipt    JSONB         CHECK (remote_receipt IS NULL OR JSONB_TYPEOF(remote_receipt) = 'object'),
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at      TIMESTAMPTZ,
    UNIQUE NULLS NOT DISTINCT
        (tenant_id, resource_type, resource_id, resource_version, event_sequence, index_target, operation),
    CHECK (
        (authority_scope = 'PLATFORM' AND tenant_id IS NULL AND resource_type = 'KNOWLEDGE_DOCUMENT_VERSION')
        OR
        (authority_scope = 'TENANT' AND tenant_id IS NOT NULL)
    ),
    CHECK (
        (status = 'RUNNING' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR
        (status <> 'RUNNING' AND lease_owner IS NULL AND lease_expires_at IS NULL)
    ),
    CHECK ((status = 'SUCCEEDED' AND completed_at IS NOT NULL) OR (status <> 'SUCCEEDED' AND completed_at IS NULL))
);

CREATE INDEX idx_context_index_job_dispatch
    ON dianlian_business.context_index_job (status, next_attempt_at, event_sequence, job_id)
    WHERE status IN ('PENDING', 'FAILED');
CREATE INDEX idx_context_index_job_resource_latest
    ON dianlian_business.context_index_job
        (resource_type, resource_id, index_target, event_sequence DESC, resource_version DESC);

COMMENT ON TABLE dianlian_business.context_index_job IS
    'Bounded persistent projection queue. Workers must re-read authority state/version before any UPSERT and prefer a later DELETE event.';
COMMENT ON TABLE dianlian_business.ai_memory_item IS
    'V1 active long-term memory supports only AGENT, USER_AGENT and GROUP_AGENT. PROJECT, TENANT and CONVERSATION are intentionally not accepted.';
COMMENT ON COLUMN dianlian_business.knowledge_document_version.event_sequence IS
    'Monotonic authority cursor copied into projection jobs and outbox payloads to prevent stale UPSERT resurrection.';

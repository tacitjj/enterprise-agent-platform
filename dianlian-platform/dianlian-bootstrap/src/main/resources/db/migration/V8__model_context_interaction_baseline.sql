-- Configurable model routing and unified human/AI internal conversations.
-- Secrets are never stored here; credential_ref only points to a runtime secret.

INSERT INTO dianlian_business.iam_permission (permission_code, display_name, status)
VALUES
    ('platform.model.read', '查看平台模型配置', 'ACTIVE'),
    ('platform.model.manage', '管理平台模型配置与路由', 'ACTIVE'),
    ('enterprise.employee.model.configure', '配置企业数字员工模型路由', 'ACTIVE'),
    ('conversation.read', '查看内部会话', 'ACTIVE'),
    ('conversation.create', '创建内部会话', 'ACTIVE'),
    ('conversation.message.send', '发送内部会话消息', 'ACTIVE'),
    ('conversation.agent.invoke', '在会话中调用数字员工', 'ACTIVE')
ON CONFLICT (permission_code) DO NOTHING;

ALTER TABLE dianlian_business.enterprise_agent_configuration_version
    DROP CONSTRAINT IF EXISTS enterprise_agent_configuration_version_model_policy_mode_check;
ALTER TABLE dianlian_business.enterprise_agent_configuration_version
    ADD CONSTRAINT chk_enterprise_agent_configuration_model_policy_mode
        CHECK (model_policy_mode IN ('PLATFORM_DEFAULT', 'AGENT_ROUTE'));

ALTER TABLE dianlian_business.enterprise_agent_configuration_version
    DROP CONSTRAINT IF EXISTS enterprise_agent_configuration_version_knowledge_scope_mode_check;
ALTER TABLE dianlian_business.enterprise_agent_configuration_version
    ADD CONSTRAINT chk_enterprise_agent_configuration_knowledge_scope_mode
        CHECK (knowledge_scope_mode IN ('NONE', 'ENTERPRISE_AUTHORIZED', 'ENTERPRISE_REQUIRED'));

CREATE TABLE dianlian_business.point_reservation_settlement
(
    settlement_id      UUID         PRIMARY KEY,
    tenant_id          UUID         NOT NULL,
    reservation_id     UUID         NOT NULL,
    captured_amount    BIGINT       NOT NULL CHECK (captured_amount >= 0),
    released_amount    BIGINT       NOT NULL CHECK (released_amount >= 0),
    reservation_status VARCHAR(32)  NOT NULL CHECK (reservation_status IN ('CAPTURED', 'RELEASED')),
    idempotency_key    VARCHAR(160) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    request_hash       VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    reason_code        VARCHAR(64)  NOT NULL CHECK (BTRIM(reason_code) <> ''),
    settled_by         UUID         NOT NULL REFERENCES dianlian_business.user_account (user_id),
    settled_at         TIMESTAMPTZ  NOT NULL,
    UNIQUE (tenant_id, settlement_id),
    UNIQUE (tenant_id, idempotency_key),
    UNIQUE (tenant_id, reservation_id),
    FOREIGN KEY (tenant_id, reservation_id)
        REFERENCES dianlian_business.point_reservation (tenant_id, reservation_id),
    CHECK (captured_amount + released_amount > 0)
);

CREATE OR REPLACE FUNCTION dianlian_business.reject_point_settlement_change()
RETURNS TRIGGER AS
$$
BEGIN
    RAISE EXCEPTION 'point settlement facts are immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_point_reservation_settlement_immutable
    BEFORE UPDATE OR DELETE ON dianlian_business.point_reservation_settlement
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.reject_point_settlement_change();

CREATE TABLE dianlian_business.model_definition
(
    model_definition_id UUID          PRIMARY KEY,
    model_code          VARCHAR(64)   NOT NULL CHECK (model_code ~ '^[A-Z][A-Z0-9_.-]{1,63}$'),
    configuration_version BIGINT      NOT NULL CHECK (configuration_version > 0),
    display_name        VARCHAR(100)  NOT NULL CHECK (BTRIM(display_name) <> ''),
    provider_code       VARCHAR(64)   NOT NULL CHECK (provider_code ~ '^[A-Z][A-Z0-9_.-]{1,63}$'),
    protocol            VARCHAR(64)   NOT NULL CHECK (protocol = 'OPENAI_COMPATIBLE'),
    base_url            VARCHAR(2048) NOT NULL CHECK (base_url ~ '^https://'),
    provider_model_name VARCHAR(100)  NOT NULL CHECK (BTRIM(provider_model_name) <> ''),
    credential_ref      VARCHAR(132)  NOT NULL
        CHECK (credential_ref ~ '^env:DIANLIAN_MODEL_[A-Z0-9_]{1,113}$'),
    capability_type     VARCHAR(32)   NOT NULL CHECK (capability_type IN (
        'TEXT_CHAT', 'TEXT_REASONING', 'VISION_UNDERSTANDING', 'IMAGE_GENERATION',
        'IMAGE_EDITING', 'EMBEDDING', 'RERANK', 'OCR'
    )),
    temperature         NUMERIC(3, 2) NOT NULL CHECK (temperature >= 0 AND temperature <= 2),
    max_output_tokens   INTEGER       NOT NULL CHECK (max_output_tokens > 0 AND max_output_tokens <= 131072),
    input_rate_micro_credit_per_million_tokens  BIGINT NOT NULL CHECK (input_rate_micro_credit_per_million_tokens >= 0),
    output_rate_micro_credit_per_million_tokens BIGINT NOT NULL CHECK (output_rate_micro_credit_per_million_tokens >= 0),
    reservation_ceiling_micro_credit BIGINT NOT NULL CHECK (reservation_ceiling_micro_credit > 0),
    status              VARCHAR(16)   NOT NULL CHECK (status IN ('ACTIVE', 'DISABLED')),
    request_hash        VARCHAR(128)  NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key     VARCHAR(200)  NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    created_by          UUID          NOT NULL REFERENCES dianlian_business.user_account (user_id),
    created_at          TIMESTAMPTZ   NOT NULL,
    UNIQUE (model_code, configuration_version),
    UNIQUE (created_by, idempotency_key)
);

CREATE INDEX idx_model_definition_capability_status
    ON dianlian_business.model_definition (capability_type, status, model_code, configuration_version DESC);

CREATE OR REPLACE FUNCTION dianlian_business.protect_model_definition_snapshot()
RETURNS TRIGGER AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'model definitions are append-only';
    END IF;
    IF NEW.model_definition_id IS DISTINCT FROM OLD.model_definition_id
        OR NEW.model_code IS DISTINCT FROM OLD.model_code
        OR NEW.configuration_version IS DISTINCT FROM OLD.configuration_version
        OR NEW.display_name IS DISTINCT FROM OLD.display_name
        OR NEW.provider_code IS DISTINCT FROM OLD.provider_code
        OR NEW.protocol IS DISTINCT FROM OLD.protocol
        OR NEW.base_url IS DISTINCT FROM OLD.base_url
        OR NEW.provider_model_name IS DISTINCT FROM OLD.provider_model_name
        OR NEW.credential_ref IS DISTINCT FROM OLD.credential_ref
        OR NEW.capability_type IS DISTINCT FROM OLD.capability_type
        OR NEW.temperature IS DISTINCT FROM OLD.temperature
        OR NEW.max_output_tokens IS DISTINCT FROM OLD.max_output_tokens
        OR NEW.input_rate_micro_credit_per_million_tokens IS DISTINCT FROM OLD.input_rate_micro_credit_per_million_tokens
        OR NEW.output_rate_micro_credit_per_million_tokens IS DISTINCT FROM OLD.output_rate_micro_credit_per_million_tokens
        OR NEW.reservation_ceiling_micro_credit IS DISTINCT FROM OLD.reservation_ceiling_micro_credit
        OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
        OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
        OR NEW.created_by IS DISTINCT FROM OLD.created_by
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'model definition snapshots are immutable';
    END IF;
    IF OLD.status = 'DISABLED' AND NEW.status <> 'DISABLED' THEN
        RAISE EXCEPTION 'disabled model definitions cannot be reactivated';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_model_definition_snapshot_immutable
    BEFORE UPDATE OR DELETE ON dianlian_business.model_definition
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_model_definition_snapshot();

CREATE TABLE dianlian_business.model_route_binding
(
    route_binding_id    UUID         PRIMARY KEY,
    scope_type          VARCHAR(16)  NOT NULL CHECK (scope_type IN ('PLATFORM', 'AGENT')),
    tenant_id           UUID,
    enterprise_agent_id UUID,
    capability_type     VARCHAR(32)  NOT NULL CHECK (capability_type IN (
        'TEXT_CHAT', 'TEXT_REASONING', 'VISION_UNDERSTANDING', 'IMAGE_GENERATION',
        'IMAGE_EDITING', 'EMBEDDING', 'RERANK', 'OCR'
    )),
    model_definition_id UUID         NOT NULL REFERENCES dianlian_business.model_definition (model_definition_id),
    state_version       BIGINT       NOT NULL CHECK (state_version > 0),
    status              VARCHAR(16)  NOT NULL CHECK (status IN ('ACTIVE', 'SUPERSEDED')),
    request_hash        VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key     VARCHAR(200) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    created_by          UUID         NOT NULL REFERENCES dianlian_business.user_account (user_id),
    created_at          TIMESTAMPTZ  NOT NULL,
    superseded_at       TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, enterprise_agent_id)
        REFERENCES dianlian_business.enterprise_agent (tenant_id, enterprise_agent_id),
    UNIQUE (created_by, idempotency_key),
    UNIQUE (route_binding_id, model_definition_id),
    UNIQUE (scope_type, tenant_id, enterprise_agent_id, capability_type, state_version),
    CHECK (
        (scope_type = 'PLATFORM' AND tenant_id IS NULL AND enterprise_agent_id IS NULL)
        OR
        (scope_type = 'AGENT' AND tenant_id IS NOT NULL AND enterprise_agent_id IS NOT NULL)
    ),
    CHECK ((status = 'ACTIVE' AND superseded_at IS NULL) OR (status = 'SUPERSEDED' AND superseded_at IS NOT NULL))
);

CREATE UNIQUE INDEX uq_model_route_platform_active
    ON dianlian_business.model_route_binding (capability_type)
    WHERE scope_type = 'PLATFORM' AND status = 'ACTIVE';
CREATE UNIQUE INDEX uq_model_route_platform_history
    ON dianlian_business.model_route_binding (capability_type, state_version)
    WHERE scope_type = 'PLATFORM';
CREATE UNIQUE INDEX uq_model_route_agent_active
    ON dianlian_business.model_route_binding (tenant_id, enterprise_agent_id, capability_type)
    WHERE scope_type = 'AGENT' AND status = 'ACTIVE';

CREATE OR REPLACE FUNCTION dianlian_business.protect_model_route_binding()
RETURNS TRIGGER AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'model routes are append-only';
    END IF;
    IF NEW.route_binding_id IS DISTINCT FROM OLD.route_binding_id
        OR NEW.scope_type IS DISTINCT FROM OLD.scope_type
        OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
        OR NEW.enterprise_agent_id IS DISTINCT FROM OLD.enterprise_agent_id
        OR NEW.capability_type IS DISTINCT FROM OLD.capability_type
        OR NEW.model_definition_id IS DISTINCT FROM OLD.model_definition_id
        OR NEW.state_version IS DISTINCT FROM OLD.state_version
        OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
        OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
        OR NEW.created_by IS DISTINCT FROM OLD.created_by
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'model route identity is immutable';
    END IF;
    IF OLD.status = 'SUPERSEDED' OR NEW.status <> 'SUPERSEDED' OR NEW.superseded_at IS NULL THEN
        RAISE EXCEPTION 'model routes can only transition active to superseded';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_model_route_binding_immutable
    BEFORE UPDATE OR DELETE ON dianlian_business.model_route_binding
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_model_route_binding();

CREATE TABLE dianlian_business.conversation
(
    conversation_id   UUID         PRIMARY KEY,
    tenant_id          UUID         NOT NULL REFERENCES dianlian_business.tenant (tenant_id),
    conversation_type VARCHAR(16)  NOT NULL CHECK (conversation_type IN ('DIRECT', 'GROUP')),
    title              VARCHAR(200) NOT NULL CHECK (BTRIM(title) <> ''),
    status             VARCHAR(16)  NOT NULL CHECK (status IN ('ACTIVE', 'DISABLED')),
    history_policy     VARCHAR(32)  NOT NULL CHECK (history_policy = 'NO_PREJOIN_HISTORY'),
    membership_version BIGINT       NOT NULL CHECK (membership_version > 0),
    next_sequence_no  BIGINT       NOT NULL CHECK (next_sequence_no > 0),
    request_hash       VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key    VARCHAR(160) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    created_by         UUID         NOT NULL,
    created_at         TIMESTAMPTZ  NOT NULL,
    updated_at         TIMESTAMPTZ  NOT NULL,
    FOREIGN KEY (tenant_id, created_by)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    UNIQUE (tenant_id, conversation_id),
    UNIQUE (tenant_id, created_by, idempotency_key)
);

ALTER TABLE dianlian_business.enterprise_agent
    ADD CONSTRAINT uq_enterprise_agent_execution_identity
        UNIQUE (tenant_id, enterprise_agent_id, agent_version_id);

CREATE TABLE dianlian_business.conversation_participant
(
    conversation_id   UUID        NOT NULL,
    tenant_id          UUID        NOT NULL,
    user_id            UUID        NOT NULL,
    participant_role   VARCHAR(16) NOT NULL CHECK (participant_role IN ('OWNER', 'MEMBER')),
    status             VARCHAR(16) NOT NULL CHECK (status IN ('ACTIVE', 'LEFT', 'REMOVED')),
    joined_sequence_no BIGINT      NOT NULL CHECK (joined_sequence_no >= 0),
    joined_at          TIMESTAMPTZ NOT NULL,
    ended_at           TIMESTAMPTZ,
    PRIMARY KEY (conversation_id, user_id),
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES dianlian_business.conversation (tenant_id, conversation_id),
    FOREIGN KEY (tenant_id, user_id)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    CHECK ((status = 'ACTIVE' AND ended_at IS NULL) OR (status <> 'ACTIVE' AND ended_at IS NOT NULL))
);

CREATE INDEX idx_conversation_participant_user_active
    ON dianlian_business.conversation_participant (tenant_id, user_id, conversation_id)
    WHERE status = 'ACTIVE';

CREATE TABLE dianlian_business.conversation_agent_binding
(
    conversation_id    UUID        NOT NULL,
    tenant_id           UUID        NOT NULL,
    enterprise_agent_id UUID        NOT NULL,
    status              VARCHAR(16) NOT NULL CHECK (status IN ('ACTIVE', 'REMOVED')),
    bound_sequence_no   BIGINT      NOT NULL CHECK (bound_sequence_no >= 0),
    bound_by            UUID        NOT NULL,
    bound_at            TIMESTAMPTZ NOT NULL,
    removed_at          TIMESTAMPTZ,
    PRIMARY KEY (conversation_id, enterprise_agent_id),
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES dianlian_business.conversation (tenant_id, conversation_id),
    FOREIGN KEY (tenant_id, enterprise_agent_id)
        REFERENCES dianlian_business.enterprise_agent (tenant_id, enterprise_agent_id),
    FOREIGN KEY (tenant_id, bound_by)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    CHECK ((status = 'ACTIVE' AND removed_at IS NULL) OR (status = 'REMOVED' AND removed_at IS NOT NULL))
);

CREATE TABLE dianlian_business.conversation_message
(
    message_id         UUID          PRIMARY KEY,
    tenant_id          UUID          NOT NULL,
    conversation_id    UUID          NOT NULL,
    sequence_no        BIGINT        NOT NULL CHECK (sequence_no > 0),
    sender_type        VARCHAR(16)   NOT NULL CHECK (sender_type IN ('HUMAN', 'AGENT', 'SYSTEM')),
    sender_user_id     UUID,
    sender_agent_id    UUID,
    client_message_id  VARCHAR(160),
    idempotency_key    VARCHAR(160),
    request_hash       VARCHAR(128),
    body_text          TEXT          NOT NULL CHECK (BTRIM(body_text) <> '' AND LENGTH(body_text) <= 100000),
    reply_to_message_id UUID,
    collaboration_mode VARCHAR(32) CHECK (collaboration_mode IN ('SINGLE_TARGET', 'PARALLEL_SEPARATE', 'PRIMARY_SUMMARY')),
    primary_agent_id   UUID,
    status             VARCHAR(16)   NOT NULL CHECK (status IN ('VISIBLE', 'RETRACTED')),
    created_at         TIMESTAMPTZ   NOT NULL,
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES dianlian_business.conversation (tenant_id, conversation_id),
    FOREIGN KEY (tenant_id, conversation_id, reply_to_message_id)
        REFERENCES dianlian_business.conversation_message (tenant_id, conversation_id, message_id),
    FOREIGN KEY (tenant_id, sender_user_id)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    FOREIGN KEY (tenant_id, sender_agent_id)
        REFERENCES dianlian_business.enterprise_agent (tenant_id, enterprise_agent_id),
    FOREIGN KEY (tenant_id, primary_agent_id)
        REFERENCES dianlian_business.enterprise_agent (tenant_id, enterprise_agent_id),
    UNIQUE (conversation_id, sequence_no),
    UNIQUE (tenant_id, conversation_id, message_id),
    UNIQUE (conversation_id, sender_user_id, client_message_id),
    UNIQUE (conversation_id, sender_user_id, idempotency_key),
    CHECK (
        (sender_type = 'HUMAN' AND sender_user_id IS NOT NULL AND sender_agent_id IS NULL
            AND client_message_id IS NOT NULL AND idempotency_key IS NOT NULL AND request_hash IS NOT NULL)
        OR (sender_type = 'AGENT' AND sender_user_id IS NULL AND sender_agent_id IS NOT NULL
            AND client_message_id IS NULL AND idempotency_key IS NULL AND request_hash IS NULL)
        OR (sender_type = 'SYSTEM' AND sender_user_id IS NULL AND sender_agent_id IS NULL
            AND client_message_id IS NULL AND idempotency_key IS NULL AND request_hash IS NULL)
    ),
    CHECK (
        collaboration_mode <> 'PRIMARY_SUMMARY'
        OR primary_agent_id IS NOT NULL
    )
);

CREATE INDEX idx_conversation_message_history
    ON dianlian_business.conversation_message (tenant_id, conversation_id, sequence_no);

CREATE TABLE dianlian_business.message_target
(
    message_target_id   UUID        PRIMARY KEY,
    tenant_id           UUID        NOT NULL,
    conversation_id     UUID        NOT NULL,
    message_id          UUID        NOT NULL,
    enterprise_agent_id UUID        NOT NULL,
    trigger_type        VARCHAR(16) NOT NULL CHECK (trigger_type IN ('DIRECT', 'MENTION', 'SELECTION', 'REPLY')),
    reply_to_message_id UUID,
    created_at          TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES dianlian_business.conversation (tenant_id, conversation_id),
    FOREIGN KEY (tenant_id, conversation_id, message_id)
        REFERENCES dianlian_business.conversation_message (tenant_id, conversation_id, message_id),
    FOREIGN KEY (tenant_id, conversation_id, reply_to_message_id)
        REFERENCES dianlian_business.conversation_message (tenant_id, conversation_id, message_id),
    FOREIGN KEY (tenant_id, enterprise_agent_id)
        REFERENCES dianlian_business.enterprise_agent (tenant_id, enterprise_agent_id),
    UNIQUE (message_id, enterprise_agent_id),
    UNIQUE (tenant_id, conversation_id, message_target_id)
);

CREATE TABLE dianlian_business.message_access_snapshot
(
    message_id             UUID         PRIMARY KEY,
    tenant_id               UUID         NOT NULL,
    conversation_id         UUID         NOT NULL,
    membership_version      BIGINT       NOT NULL CHECK (membership_version > 0),
    history_floor_sequence_no BIGINT     NOT NULL CHECK (history_floor_sequence_no >= 0),
    audience_user_ids       JSONB        NOT NULL CHECK (JSONB_TYPEOF(audience_user_ids) = 'array'),
    allowed_agent_ids       JSONB        NOT NULL CHECK (JSONB_TYPEOF(allowed_agent_ids) = 'array'),
    knowledge_scope_version VARCHAR(128) NOT NULL,
    policy_version          VARCHAR(64)  NOT NULL,
    created_at              TIMESTAMPTZ  NOT NULL,
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES dianlian_business.conversation (tenant_id, conversation_id),
    FOREIGN KEY (tenant_id, conversation_id, message_id)
        REFERENCES dianlian_business.conversation_message (tenant_id, conversation_id, message_id)
);

CREATE TABLE dianlian_business.ai_invocation
(
    invocation_id          UUID         PRIMARY KEY,
    tenant_id               UUID         NOT NULL,
    conversation_id         UUID         NOT NULL,
    source_message_id       UUID         NOT NULL,
    message_target_id       UUID         NOT NULL,
    requested_by            UUID         NOT NULL,
    enterprise_agent_id     UUID         NOT NULL,
    agent_version_id        UUID         NOT NULL,
    configuration_version_id UUID        NOT NULL,
    role_name_snapshot      VARCHAR(100) NOT NULL,
    platform_profile_snapshot TEXT       NOT NULL,
    enterprise_instructions_snapshot TEXT NOT NULL,
    knowledge_scope_mode_snapshot VARCHAR(32) NOT NULL,
    model_route_binding_id  UUID         NOT NULL REFERENCES dianlian_business.model_route_binding (route_binding_id),
    model_route_state_version BIGINT      NOT NULL CHECK (model_route_state_version > 0),
    model_definition_id     UUID         NOT NULL REFERENCES dianlian_business.model_definition (model_definition_id),
    point_reservation_id    UUID         NOT NULL,
    status                  VARCHAR(32)  NOT NULL CHECK (status IN (
        'QUEUED', 'RUNNING', 'RESPONSE_RECEIVED', 'USAGE_PENDING', 'COMPLETED',
        'BLOCKED_CONTEXT', 'BLOCKED_ACCESS', 'FAILED_PROVIDER', 'FAILED_BILLING'
    )),
    attempt_count           INTEGER      NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    lease_owner             VARCHAR(128),
    lease_epoch             BIGINT       NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
    provider_response_text  TEXT,
    provider_request_id     VARCHAR(256),
    response_message_id     UUID UNIQUE REFERENCES dianlian_business.conversation_message (message_id),
    input_tokens            INTEGER      NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens           INTEGER      NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    usage_status            VARCHAR(16)  NOT NULL DEFAULT 'PENDING'
        CHECK (usage_status IN ('PENDING', 'CONFIRMED')),
    captured_micro_credit   BIGINT       NOT NULL DEFAULT 0 CHECK (captured_micro_credit >= 0),
    error_code              VARCHAR(128),
    next_attempt_at         TIMESTAMPTZ  NOT NULL,
    lease_until             TIMESTAMPTZ,
    created_at              TIMESTAMPTZ  NOT NULL,
    updated_at              TIMESTAMPTZ  NOT NULL,
    completed_at            TIMESTAMPTZ,
    FOREIGN KEY (tenant_id, conversation_id)
        REFERENCES dianlian_business.conversation (tenant_id, conversation_id),
    FOREIGN KEY (tenant_id, conversation_id, source_message_id)
        REFERENCES dianlian_business.conversation_message (tenant_id, conversation_id, message_id),
    FOREIGN KEY (tenant_id, conversation_id, message_target_id)
        REFERENCES dianlian_business.message_target (tenant_id, conversation_id, message_target_id),
    FOREIGN KEY (tenant_id, requested_by)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    FOREIGN KEY (tenant_id, enterprise_agent_id)
        REFERENCES dianlian_business.enterprise_agent (tenant_id, enterprise_agent_id),
    FOREIGN KEY (tenant_id, enterprise_agent_id, agent_version_id)
        REFERENCES dianlian_business.enterprise_agent
            (tenant_id, enterprise_agent_id, agent_version_id),
    FOREIGN KEY (tenant_id, enterprise_agent_id, configuration_version_id)
        REFERENCES dianlian_business.enterprise_agent_configuration_version
            (tenant_id, enterprise_agent_id, configuration_version_id),
    FOREIGN KEY (model_route_binding_id, model_definition_id)
        REFERENCES dianlian_business.model_route_binding
            (route_binding_id, model_definition_id),
    FOREIGN KEY (tenant_id, point_reservation_id)
        REFERENCES dianlian_business.point_reservation (tenant_id, reservation_id),
    UNIQUE (message_target_id)
);

ALTER TABLE dianlian_business.ai_invocation
    ADD CONSTRAINT chk_ai_invocation_lease
        CHECK (
            (lease_owner IS NULL AND lease_until IS NULL)
            OR (lease_owner IS NOT NULL AND lease_until IS NOT NULL)
        );

CREATE INDEX idx_ai_invocation_worker
    ON dianlian_business.ai_invocation (status, next_attempt_at, created_at)
    WHERE status IN ('QUEUED', 'RESPONSE_RECEIVED', 'RUNNING');

CREATE TABLE dianlian_business.ai_context_snapshot
(
    context_snapshot_id    UUID         PRIMARY KEY,
    invocation_id          UUID         NOT NULL UNIQUE REFERENCES dianlian_business.ai_invocation (invocation_id),
    tenant_id               UUID         NOT NULL,
    enterprise_agent_id     UUID         NOT NULL,
    agent_version_id        UUID         NOT NULL,
    configuration_version_id UUID        NOT NULL,
    memory_scopes           JSONB        NOT NULL CHECK (JSONB_TYPEOF(memory_scopes) = 'array'),
    knowledge_state         VARCHAR(16)  NOT NULL CHECK (knowledge_state IN ('READY', 'EMPTY', 'UNAVAILABLE', 'FORBIDDEN')),
    memory_state            VARCHAR(16)  NOT NULL CHECK (memory_state IN ('READY', 'EMPTY', 'UNAVAILABLE', 'FORBIDDEN')),
    context_hash            VARCHAR(128) NOT NULL,
    created_at              TIMESTAMPTZ  NOT NULL,
    FOREIGN KEY (tenant_id, enterprise_agent_id)
        REFERENCES dianlian_business.enterprise_agent (tenant_id, enterprise_agent_id)
);

CREATE TABLE dianlian_business.provider_attempt
(
    provider_attempt_id UUID         PRIMARY KEY,
    invocation_id       UUID         NOT NULL REFERENCES dianlian_business.ai_invocation (invocation_id),
    attempt_no           INTEGER      NOT NULL CHECK (attempt_no > 0),
    model_definition_id  UUID         NOT NULL REFERENCES dianlian_business.model_definition (model_definition_id),
    status               VARCHAR(16)  NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED')),
    provider_request_id  VARCHAR(256),
    input_tokens         INTEGER      NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens        INTEGER      NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    usage_status         VARCHAR(16)  NOT NULL CHECK (usage_status IN ('PENDING', 'CONFIRMED')),
    error_code           VARCHAR(128),
    started_at           TIMESTAMPTZ  NOT NULL,
    completed_at         TIMESTAMPTZ  NOT NULL,
    UNIQUE (invocation_id, attempt_no)
);

COMMENT ON COLUMN dianlian_business.model_definition.credential_ref IS
    'Secret reference only, for example env:DIANLIAN_MODEL_DASHSCOPE_API_KEY. Secret values must not enter the database.';
COMMENT ON TABLE dianlian_business.ai_context_snapshot IS
    'Records context source versions and scope boundaries, not model hidden reasoning.';
COMMENT ON COLUMN dianlian_business.ai_invocation.configuration_version_id IS
    'Freezes the enterprise digital employee identity used for this reply.';

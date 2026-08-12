-- Enterprise employee configuration is append-only. Activation binds one immutable
-- configuration snapshot to the employee and advances the employee state version.

INSERT INTO dianlian_business.iam_permission (permission_code, display_name, status)
VALUES
    ('enterprise.employee.configure', '配置企业数字员工', 'ACTIVE'),
    ('enterprise.employee.activate', '激活企业数字员工', 'ACTIVE')
ON CONFLICT (permission_code) DO NOTHING;

ALTER TABLE dianlian_business.enterprise_agent
    ADD COLUMN state_version BIGINT NOT NULL DEFAULT 0 CHECK (state_version >= 0),
    ADD COLUMN active_configuration_version_id UUID,
    ADD COLUMN activated_by UUID,
    ADD COLUMN activated_at TIMESTAMPTZ;

CREATE TABLE dianlian_business.enterprise_agent_configuration_version
(
    configuration_version_id       UUID          PRIMARY KEY,
    tenant_id                       UUID          NOT NULL,
    enterprise_agent_id             UUID          NOT NULL,
    revision                        BIGINT        NOT NULL CHECK (revision > 0),
    display_name_snapshot           VARCHAR(100)  NOT NULL CHECK (BTRIM(display_name_snapshot) <> ''),
    profile                         VARCHAR(2000) NOT NULL CHECK (BTRIM(profile) <> ''),
    enterprise_instructions         TEXT          NOT NULL CHECK (CHAR_LENGTH(enterprise_instructions) <= 20000),
    model_policy_mode               VARCHAR(32)   NOT NULL CHECK (model_policy_mode = 'PLATFORM_DEFAULT'),
    knowledge_scope_mode            VARCHAR(32)   NOT NULL CHECK (knowledge_scope_mode = 'NONE'),
    visibility_scope                VARCHAR(32)   NOT NULL CHECK (visibility_scope = 'TENANT'),
    status                          VARCHAR(16)   NOT NULL
        CHECK (status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED')),
    create_request_hash             VARCHAR(128) NOT NULL CHECK (BTRIM(create_request_hash) <> ''),
    create_idempotency_key          VARCHAR(200) NOT NULL CHECK (BTRIM(create_idempotency_key) <> ''),
    created_by                      UUID         NOT NULL,
    created_at                      TIMESTAMPTZ  NOT NULL,
    create_result_state_version     BIGINT       NOT NULL CHECK (create_result_state_version > 0),
    activation_request_hash         VARCHAR(128),
    activation_idempotency_key      VARCHAR(200),
    activated_by                    UUID,
    activated_at                    TIMESTAMPTZ,
    activation_result_state_version BIGINT,
    updated_at                      TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_id, enterprise_agent_id)
        REFERENCES dianlian_business.enterprise_agent (tenant_id, enterprise_agent_id),
    FOREIGN KEY (created_by)
        REFERENCES dianlian_business.user_account (user_id),
    FOREIGN KEY (tenant_id, created_by)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    UNIQUE (tenant_id, enterprise_agent_id, configuration_version_id),
    UNIQUE (tenant_id, enterprise_agent_id, revision),
    UNIQUE (tenant_id, created_by, create_idempotency_key),
    CHECK (
        (status = 'ACTIVE'
            AND activation_request_hash IS NOT NULL
            AND activation_idempotency_key IS NOT NULL
            AND activated_by IS NOT NULL
            AND activated_at IS NOT NULL
            AND activation_result_state_version IS NOT NULL)
        OR
        (status = 'DRAFT'
            AND activation_request_hash IS NULL
            AND activation_idempotency_key IS NULL
            AND activated_by IS NULL
            AND activated_at IS NULL
            AND activation_result_state_version IS NULL)
        OR
        (status = 'SUPERSEDED'
            AND (
                (activation_request_hash IS NULL
                    AND activation_idempotency_key IS NULL
                    AND activated_by IS NULL
                    AND activated_at IS NULL
                    AND activation_result_state_version IS NULL)
                OR
                (activation_request_hash IS NOT NULL
                    AND activation_idempotency_key IS NOT NULL
                    AND activated_by IS NOT NULL
                    AND activated_at IS NOT NULL
                    AND activation_result_state_version IS NOT NULL)
            ))
    )
);

CREATE UNIQUE INDEX uk_enterprise_agent_configuration_activation_idempotency
    ON dianlian_business.enterprise_agent_configuration_version
        (tenant_id, activated_by, activation_idempotency_key)
    WHERE activation_idempotency_key IS NOT NULL;

CREATE INDEX idx_enterprise_agent_configuration_latest
    ON dianlian_business.enterprise_agent_configuration_version
        (tenant_id, enterprise_agent_id, revision DESC);

CREATE TABLE dianlian_business.enterprise_agent_state_event
(
    event_id                 UUID         PRIMARY KEY,
    tenant_id                UUID         NOT NULL,
    enterprise_agent_id      UUID         NOT NULL,
    state_version            BIGINT       NOT NULL CHECK (state_version >= 0),
    event_type               VARCHAR(40)  NOT NULL
        CHECK (event_type IN (
            'HIRED',
            'CONFIGURATION_CREATED',
            'ACTIVATED',
            'LEGACY_CONFIGURATION_ACTIVATED'
        )),
    from_status              VARCHAR(16),
    to_status                VARCHAR(16)  NOT NULL
        CHECK (to_status IN ('DRAFT', 'ACTIVE', 'RESTRICTED', 'DISABLED')),
    configuration_version_id UUID,
    request_hash             VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    idempotency_key          VARCHAR(200) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    actor_id                 UUID         NOT NULL,
    occurred_at              TIMESTAMPTZ  NOT NULL,
    FOREIGN KEY (tenant_id, enterprise_agent_id)
        REFERENCES dianlian_business.enterprise_agent (tenant_id, enterprise_agent_id),
    FOREIGN KEY (tenant_id, enterprise_agent_id, configuration_version_id)
        REFERENCES dianlian_business.enterprise_agent_configuration_version
            (tenant_id, enterprise_agent_id, configuration_version_id),
    FOREIGN KEY (actor_id)
        REFERENCES dianlian_business.user_account (user_id),
    FOREIGN KEY (tenant_id, actor_id)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    UNIQUE (tenant_id, enterprise_agent_id, state_version),
    UNIQUE (tenant_id, actor_id, event_type, idempotency_key)
);

CREATE INDEX idx_enterprise_agent_state_event_timeline
    ON dianlian_business.enterprise_agent_state_event
        (tenant_id, enterprise_agent_id, state_version);

CREATE OR REPLACE FUNCTION dianlian_business.protect_enterprise_agent_state_event()
RETURNS TRIGGER AS
$$
BEGIN
    RAISE EXCEPTION 'enterprise agent state events are append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_enterprise_agent_state_event_append_only
    BEFORE UPDATE OR DELETE ON dianlian_business.enterprise_agent_state_event
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_enterprise_agent_state_event();

-- Preserve already-running development data without silently downgrading employees.
-- The deterministic identifier makes the one-off compatibility snapshot auditable.
INSERT INTO dianlian_business.enterprise_agent_configuration_version
    (configuration_version_id, tenant_id, enterprise_agent_id, revision,
     display_name_snapshot, profile, enterprise_instructions,
     model_policy_mode, knowledge_scope_mode, visibility_scope, status,
     create_request_hash, create_idempotency_key, created_by, created_at,
     create_result_state_version, activation_request_hash, activation_idempotency_key,
     activated_by, activated_at, activation_result_state_version, updated_at)
SELECT
    MD5('dianlian-v7-legacy-config:' || a.enterprise_agent_id::TEXT)::UUID,
    a.tenant_id,
    a.enterprise_agent_id,
    1,
    a.display_name,
    v.template_description,
    '',
    'PLATFORM_DEFAULT',
    'NONE',
    'TENANT',
    'ACTIVE',
    'legacy-v7-create:' || MD5(a.enterprise_agent_id::TEXT),
    'legacy-v7-create:' || a.enterprise_agent_id::TEXT,
    a.hired_by,
    a.hired_at,
    GREATEST(a.state_version, 1),
    'legacy-v7-activate:' || MD5(a.enterprise_agent_id::TEXT),
    'legacy-v7-activate:' || a.enterprise_agent_id::TEXT,
    a.hired_by,
    a.hired_at,
    GREATEST(a.state_version, 1),
    CURRENT_TIMESTAMP
FROM dianlian_business.enterprise_agent a
JOIN dianlian_business.agent_version v
  ON v.agent_version_id = a.agent_version_id
WHERE a.status IN ('ACTIVE', 'RESTRICTED', 'DISABLED');

UPDATE dianlian_business.enterprise_agent a
SET active_configuration_version_id =
        MD5('dianlian-v7-legacy-config:' || a.enterprise_agent_id::TEXT)::UUID,
    activated_by = a.hired_by,
    activated_at = a.hired_at,
    state_version = GREATEST(a.state_version, 1),
    updated_at = CURRENT_TIMESTAMP
WHERE a.status IN ('ACTIVE', 'RESTRICTED', 'DISABLED');

INSERT INTO dianlian_business.enterprise_agent_state_event
    (event_id, tenant_id, enterprise_agent_id, state_version, event_type,
     from_status, to_status, configuration_version_id, request_hash,
     idempotency_key, actor_id, occurred_at)
SELECT
    MD5('dianlian-v7-legacy-event:' || a.enterprise_agent_id::TEXT)::UUID,
    a.tenant_id,
    a.enterprise_agent_id,
    a.state_version,
    'LEGACY_CONFIGURATION_ACTIVATED',
    NULL,
    a.status,
    a.active_configuration_version_id,
    'legacy-v7-activate:' || MD5(a.enterprise_agent_id::TEXT),
    'legacy-v7-activate:' || a.enterprise_agent_id::TEXT,
    a.hired_by,
    a.hired_at
FROM dianlian_business.enterprise_agent a
WHERE a.status IN ('ACTIVE', 'RESTRICTED', 'DISABLED');

ALTER TABLE dianlian_business.enterprise_agent
    ADD CONSTRAINT fk_enterprise_agent_active_configuration
        FOREIGN KEY (tenant_id, enterprise_agent_id, active_configuration_version_id)
        REFERENCES dianlian_business.enterprise_agent_configuration_version
            (tenant_id, enterprise_agent_id, configuration_version_id),
    ADD CONSTRAINT fk_enterprise_agent_activated_by
        FOREIGN KEY (activated_by)
        REFERENCES dianlian_business.user_account (user_id),
    ADD CONSTRAINT fk_enterprise_agent_tenant_activated_by
        FOREIGN KEY (tenant_id, activated_by)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    ADD CONSTRAINT ck_enterprise_agent_configuration_lifecycle
        CHECK (
            (status = 'DRAFT'
                AND active_configuration_version_id IS NULL
                AND activated_by IS NULL
                AND activated_at IS NULL)
            OR
            (status IN ('ACTIVE', 'RESTRICTED', 'DISABLED')
                AND active_configuration_version_id IS NOT NULL
                AND activated_by IS NOT NULL
                AND activated_at IS NOT NULL)
        );

CREATE OR REPLACE FUNCTION dianlian_business.protect_enterprise_agent_configuration_version()
RETURNS TRIGGER AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'enterprise agent configuration versions are append-only';
    END IF;

    IF NEW.configuration_version_id IS DISTINCT FROM OLD.configuration_version_id
        OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
        OR NEW.enterprise_agent_id IS DISTINCT FROM OLD.enterprise_agent_id
        OR NEW.revision IS DISTINCT FROM OLD.revision
        OR NEW.display_name_snapshot IS DISTINCT FROM OLD.display_name_snapshot
        OR NEW.profile IS DISTINCT FROM OLD.profile
        OR NEW.enterprise_instructions IS DISTINCT FROM OLD.enterprise_instructions
        OR NEW.model_policy_mode IS DISTINCT FROM OLD.model_policy_mode
        OR NEW.knowledge_scope_mode IS DISTINCT FROM OLD.knowledge_scope_mode
        OR NEW.visibility_scope IS DISTINCT FROM OLD.visibility_scope
        OR NEW.create_request_hash IS DISTINCT FROM OLD.create_request_hash
        OR NEW.create_idempotency_key IS DISTINCT FROM OLD.create_idempotency_key
        OR NEW.created_by IS DISTINCT FROM OLD.created_by
        OR NEW.created_at IS DISTINCT FROM OLD.created_at
        OR NEW.create_result_state_version IS DISTINCT FROM OLD.create_result_state_version THEN
        RAISE EXCEPTION 'enterprise agent configuration snapshots are immutable';
    END IF;

    IF OLD.status = 'DRAFT' AND NEW.status NOT IN ('ACTIVE', 'SUPERSEDED') THEN
        RAISE EXCEPTION 'draft configuration can only activate or be superseded';
    END IF;
    IF OLD.status = 'ACTIVE' AND NEW.status NOT IN ('ACTIVE', 'SUPERSEDED') THEN
        RAISE EXCEPTION 'active configuration can only remain active or be superseded';
    END IF;
    IF OLD.status = 'SUPERSEDED' AND NEW.status <> 'SUPERSEDED' THEN
        RAISE EXCEPTION 'terminal configuration status cannot change';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_enterprise_agent_configuration_version_immutable
    BEFORE UPDATE OR DELETE ON dianlian_business.enterprise_agent_configuration_version
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_enterprise_agent_configuration_version();

CREATE OR REPLACE FUNCTION dianlian_business.protect_enterprise_agent_version_binding()
RETURNS TRIGGER AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'enterprise employees cannot be physically deleted';
    END IF;

    IF NEW.enterprise_agent_id IS DISTINCT FROM OLD.enterprise_agent_id
        OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
        OR NEW.agent_template_id IS DISTINCT FROM OLD.agent_template_id
        OR NEW.agent_version_id IS DISTINCT FROM OLD.agent_version_id
        OR NEW.employee_code IS DISTINCT FROM OLD.employee_code
        OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
        OR NEW.hire_idempotency_key IS DISTINCT FROM OLD.hire_idempotency_key
        OR NEW.hired_by IS DISTINCT FROM OLD.hired_by
        OR NEW.hired_at IS DISTINCT FROM OLD.hired_at
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'enterprise agent version binding and hiring facts are immutable';
    END IF;

    IF NEW.state_version <> OLD.state_version + 1 THEN
        RAISE EXCEPTION 'enterprise agent updates must advance state_version exactly once';
    END IF;
    IF NEW.active_configuration_version_id IS DISTINCT FROM OLD.active_configuration_version_id THEN
        IF NEW.active_configuration_version_id IS NULL THEN
            RAISE EXCEPTION 'active configuration binding cannot be cleared';
        END IF;
        IF NOT EXISTS (
            SELECT 1
              FROM dianlian_business.enterprise_agent_configuration_version c
             WHERE c.tenant_id = NEW.tenant_id
               AND c.enterprise_agent_id = NEW.enterprise_agent_id
               AND c.configuration_version_id = NEW.active_configuration_version_id
               AND c.status = 'ACTIVE'
               AND c.display_name_snapshot = NEW.display_name
        ) THEN
            RAISE EXCEPTION 'active configuration must reference an active snapshot for this employee';
        END IF;
    ELSIF NEW.activated_by IS DISTINCT FROM OLD.activated_by
        OR NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
        RAISE EXCEPTION 'activation audit can only change with the active configuration binding';
    END IF;
    IF OLD.status = 'DRAFT' AND NEW.status NOT IN ('DRAFT', 'ACTIVE') THEN
        RAISE EXCEPTION 'draft employee can only remain draft or activate';
    END IF;
    IF OLD.status = 'ACTIVE' AND NEW.status NOT IN ('ACTIVE', 'RESTRICTED', 'DISABLED') THEN
        RAISE EXCEPTION 'active employee transition is invalid';
    END IF;
    IF OLD.status = 'RESTRICTED' AND NEW.status NOT IN ('RESTRICTED', 'ACTIVE', 'DISABLED') THEN
        RAISE EXCEPTION 'restricted employee transition is invalid';
    END IF;
    IF OLD.status = 'DISABLED' AND NEW.status <> 'DISABLED' THEN
        RAISE EXCEPTION 'disabled employee cannot be reactivated';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER trg_enterprise_agent_version_binding_immutable
    ON dianlian_business.enterprise_agent;

CREATE TRIGGER trg_enterprise_agent_version_binding_immutable
    BEFORE UPDATE OR DELETE ON dianlian_business.enterprise_agent
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_enterprise_agent_version_binding();

COMMENT ON TABLE dianlian_business.enterprise_agent_configuration_version IS
    'Append-only enterprise-specific employee configuration. Prompts are snapshotted into tasks only after activation.';

COMMENT ON COLUMN dianlian_business.enterprise_agent.state_version IS
    'Strong ETag source. Every mutable employee transition must increment this value exactly once.';

COMMENT ON TABLE dianlian_business.enterprise_agent_state_event IS
    'Append-only state-transition audit. Application transactions write one event for every employee state_version.';

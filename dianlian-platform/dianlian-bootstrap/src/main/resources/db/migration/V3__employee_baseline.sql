-- Generic digital-employee baseline. Role-specific behavior belongs in versioned capability data.

INSERT INTO dianlian_business.iam_permission (permission_code, display_name, status)
VALUES
    ('platform.employee.template.publish', '发布数字员工模板版本', 'ACTIVE'),
    ('enterprise.employee.hire', '招聘企业数字员工', 'ACTIVE'),
    ('enterprise.employee.read', '查看可用数字员工', 'ACTIVE'),
    ('enterprise.employee.execute', '使用数字员工执行任务', 'ACTIVE')
ON CONFLICT (permission_code) DO NOTHING;

CREATE TABLE dianlian_business.agent_template
(
    agent_template_id UUID         PRIMARY KEY,
    owner_scope       VARCHAR(16)  NOT NULL DEFAULT 'PLATFORM'
        CHECK (owner_scope = 'PLATFORM'),
    template_code     VARCHAR(64)  NOT NULL
        CHECK (template_code ~ '^[A-Za-z][A-Za-z0-9._-]{0,63}$'),
    status            VARCHAR(16)  NOT NULL
        CHECK (status IN ('ACTIVE', 'RETIRED')),
    created_by        UUID         NOT NULL
        REFERENCES dianlian_business.user_account (user_id),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (template_code)
);

CREATE INDEX idx_agent_template_status
    ON dianlian_business.agent_template (status, template_code);

CREATE TABLE dianlian_business.agent_version
(
    agent_version_id         UUID          PRIMARY KEY,
    owner_scope              VARCHAR(16)   NOT NULL DEFAULT 'PLATFORM'
        CHECK (owner_scope = 'PLATFORM'),
    agent_template_id        UUID          NOT NULL,
    template_name            VARCHAR(100)  NOT NULL CHECK (BTRIM(template_name) <> ''),
    template_description     VARCHAR(500)  NOT NULL CHECK (BTRIM(template_description) <> ''),
    version_label            VARCHAR(32)   NOT NULL CHECK (BTRIM(version_label) <> ''),
    capability_code          VARCHAR(64)   NOT NULL
        CHECK (capability_code ~ '^[A-Z][A-Z0-9_]{1,63}$'),
    input_schema             JSONB         NOT NULL
        CHECK (JSONB_TYPEOF(input_schema) = 'object')
        CHECK ((input_schema ->> 'schemaId') ~ '^[a-z][a-z0-9_.-]{1,127}$'),
    execution_template       JSONB         NOT NULL
        CHECK (JSONB_TYPEOF(execution_template) = 'object'),
    point_estimate           BIGINT        NOT NULL CHECK (point_estimate > 0),
    status                   VARCHAR(16)   NOT NULL
        CHECK (status IN ('PUBLISHED', 'RETIRED')),
    visibility_mode          VARCHAR(16)   NOT NULL
        CHECK (visibility_mode IN ('ALL', 'ALLOWLIST')),
    visible_tenant_ids       JSONB         NOT NULL DEFAULT '[]'::JSONB
        CHECK (JSONB_TYPEOF(visible_tenant_ids) = 'array'),
    request_hash             VARCHAR(128)  NOT NULL CHECK (BTRIM(request_hash) <> ''),
    publish_idempotency_key  VARCHAR(200)  NOT NULL CHECK (BTRIM(publish_idempotency_key) <> ''),
    published_by             UUID          NOT NULL
        REFERENCES dianlian_business.user_account (user_id),
    published_at             TIMESTAMPTZ   NOT NULL,
    created_at               TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at               TIMESTAMPTZ   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_template_id)
        REFERENCES dianlian_business.agent_template (agent_template_id),
    UNIQUE (agent_template_id, version_label),
    UNIQUE (published_by, publish_idempotency_key),
    UNIQUE (agent_template_id, agent_version_id),
    CHECK (
        (visibility_mode = 'ALL' AND JSONB_ARRAY_LENGTH(visible_tenant_ids) = 0)
        OR
        (visibility_mode = 'ALLOWLIST' AND JSONB_ARRAY_LENGTH(visible_tenant_ids) > 0)
    )
);

CREATE INDEX idx_agent_version_template_status
    ON dianlian_business.agent_version
        (agent_template_id, status, published_at DESC);

CREATE INDEX idx_agent_version_capability_status
    ON dianlian_business.agent_version (capability_code, status);

CREATE INDEX idx_agent_version_visible_tenants
    ON dianlian_business.agent_version USING GIN (visible_tenant_ids);

CREATE OR REPLACE FUNCTION dianlian_business.protect_agent_version_snapshot()
RETURNS TRIGGER AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'published agent versions are append-only';
    END IF;

    IF NEW.agent_version_id IS DISTINCT FROM OLD.agent_version_id
        OR NEW.owner_scope IS DISTINCT FROM OLD.owner_scope
        OR NEW.agent_template_id IS DISTINCT FROM OLD.agent_template_id
        OR NEW.template_name IS DISTINCT FROM OLD.template_name
        OR NEW.template_description IS DISTINCT FROM OLD.template_description
        OR NEW.version_label IS DISTINCT FROM OLD.version_label
        OR NEW.capability_code IS DISTINCT FROM OLD.capability_code
        OR NEW.input_schema IS DISTINCT FROM OLD.input_schema
        OR NEW.execution_template IS DISTINCT FROM OLD.execution_template
        OR NEW.point_estimate IS DISTINCT FROM OLD.point_estimate
        OR NEW.visibility_mode IS DISTINCT FROM OLD.visibility_mode
        OR NEW.visible_tenant_ids IS DISTINCT FROM OLD.visible_tenant_ids
        OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
        OR NEW.publish_idempotency_key IS DISTINCT FROM OLD.publish_idempotency_key
        OR NEW.published_by IS DISTINCT FROM OLD.published_by
        OR NEW.published_at IS DISTINCT FROM OLD.published_at
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'published agent version snapshots are immutable';
    END IF;

    IF OLD.status = 'RETIRED' AND NEW.status <> 'RETIRED' THEN
        RAISE EXCEPTION 'retired agent versions cannot be reactivated';
    END IF;
    IF OLD.status = 'PUBLISHED' AND NEW.status NOT IN ('PUBLISHED', 'RETIRED') THEN
        RAISE EXCEPTION 'published agent versions can only remain published or retire';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_agent_version_snapshot_immutable
    BEFORE UPDATE OR DELETE ON dianlian_business.agent_version
    FOR EACH ROW
    WHEN (OLD.status IN ('PUBLISHED', 'RETIRED'))
    EXECUTE FUNCTION dianlian_business.protect_agent_version_snapshot();

CREATE TABLE dianlian_business.enterprise_agent
(
    enterprise_agent_id UUID         PRIMARY KEY,
    tenant_id            UUID         NOT NULL
        REFERENCES dianlian_business.tenant (tenant_id),
    agent_template_id    UUID         NOT NULL,
    agent_version_id     UUID         NOT NULL,
    employee_code        VARCHAR(64)  NOT NULL
        CHECK (employee_code ~ '^[A-Za-z][A-Za-z0-9._-]{0,63}$'),
    display_name         VARCHAR(100) NOT NULL CHECK (BTRIM(display_name) <> ''),
    status               VARCHAR(16)  NOT NULL
        CHECK (status IN ('DRAFT', 'ACTIVE', 'RESTRICTED', 'DISABLED')),
    request_hash         VARCHAR(128) NOT NULL CHECK (BTRIM(request_hash) <> ''),
    hire_idempotency_key VARCHAR(200) NOT NULL CHECK (BTRIM(hire_idempotency_key) <> ''),
    hired_by             UUID         NOT NULL
        REFERENCES dianlian_business.user_account (user_id),
    hired_at             TIMESTAMPTZ  NOT NULL,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_template_id, agent_version_id)
        REFERENCES dianlian_business.agent_version (agent_template_id, agent_version_id),
    FOREIGN KEY (tenant_id, hired_by)
        REFERENCES dianlian_business.tenant_member (tenant_id, user_id),
    UNIQUE (tenant_id, enterprise_agent_id),
    UNIQUE (tenant_id, employee_code),
    UNIQUE (tenant_id, hired_by, hire_idempotency_key)
);

CREATE INDEX idx_enterprise_agent_tenant_status
    ON dianlian_business.enterprise_agent (tenant_id, status, display_name, enterprise_agent_id);

CREATE INDEX idx_enterprise_agent_version
    ON dianlian_business.enterprise_agent (agent_version_id, tenant_id);

CREATE OR REPLACE FUNCTION dianlian_business.assert_enterprise_agent_recruitable()
RETURNS TRIGGER AS
$$
DECLARE
    target_status          VARCHAR(16);
    target_visibility     VARCHAR(16);
    target_visible_tenants JSONB;
BEGIN
    SELECT status, visibility_mode, visible_tenant_ids
      INTO target_status, target_visibility, target_visible_tenants
      FROM dianlian_business.agent_version
     WHERE agent_version_id = NEW.agent_version_id;

    IF target_status IS NULL OR target_status <> 'PUBLISHED' THEN
        RAISE EXCEPTION 'enterprise agents can only hire a published agent version';
    END IF;
    IF target_visibility = 'ALLOWLIST'
        AND NOT (target_visible_tenants @> JSONB_BUILD_ARRAY(NEW.tenant_id::TEXT)) THEN
        RAISE EXCEPTION 'agent version is not visible to the enterprise tenant';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_enterprise_agent_recruitable
    BEFORE INSERT ON dianlian_business.enterprise_agent
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_enterprise_agent_recruitable();

CREATE OR REPLACE FUNCTION dianlian_business.protect_enterprise_agent_version_binding()
RETURNS TRIGGER AS
$$
BEGIN
    IF NEW.enterprise_agent_id IS DISTINCT FROM OLD.enterprise_agent_id
        OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
        OR NEW.agent_template_id IS DISTINCT FROM OLD.agent_template_id
        OR NEW.agent_version_id IS DISTINCT FROM OLD.agent_version_id
        OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
        OR NEW.hire_idempotency_key IS DISTINCT FROM OLD.hire_idempotency_key
        OR NEW.hired_by IS DISTINCT FROM OLD.hired_by
        OR NEW.hired_at IS DISTINCT FROM OLD.hired_at
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'enterprise agent version binding and hiring facts are immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_enterprise_agent_version_binding_immutable
    BEFORE UPDATE ON dianlian_business.enterprise_agent
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.protect_enterprise_agent_version_binding();

COMMENT ON COLUMN dianlian_business.agent_template.owner_scope IS
    'Explicit platform ownership. Platform sessions are tenantless and must never impersonate an enterprise tenant.';

COMMENT ON COLUMN dianlian_business.agent_version.visible_tenant_ids IS
    'Frozen allowlist of enterprise tenant UUID strings; empty only when visibility_mode is ALL.';

COMMENT ON COLUMN dianlian_business.enterprise_agent.agent_version_id IS
    'Frozen version hired by the enterprise. Upgrades create a new explicit configuration/version transition.';

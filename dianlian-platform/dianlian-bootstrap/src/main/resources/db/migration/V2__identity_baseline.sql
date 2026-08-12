CREATE TABLE dianlian_business.tenant
(
    tenant_id          UUID         PRIMARY KEY,
    display_name       VARCHAR(200) NOT NULL CHECK (BTRIM(display_name) <> ''),
    status             VARCHAR(16)  NOT NULL CHECK (status IN ('ACTIVE', 'SUSPENDED', 'CLOSED')),
    permission_version BIGINT       NOT NULL DEFAULT 1 CHECK (permission_version > 0),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE dianlian_business.user_account
(
    user_id            UUID         PRIMARY KEY,
    display_name       VARCHAR(100) NOT NULL CHECK (BTRIM(display_name) <> ''),
    avatar_url         VARCHAR(2048),
    status             VARCHAR(16)  NOT NULL CHECK (status IN ('ACTIVE', 'SUSPENDED')),
    permission_version BIGINT       NOT NULL DEFAULT 1 CHECK (permission_version > 0),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE dianlian_business.tenant_member
(
    member_id          UUID        PRIMARY KEY,
    tenant_id          UUID        NOT NULL REFERENCES dianlian_business.tenant (tenant_id),
    user_id            UUID        NOT NULL REFERENCES dianlian_business.user_account (user_id),
    status             VARCHAR(16) NOT NULL
        CHECK (status IN ('ACTIVE', 'SUSPENDED', 'LEFT', 'REMOVED', 'EXPIRED')),
    permission_version BIGINT      NOT NULL DEFAULT 1 CHECK (permission_version > 0),
    joined_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at         TIMESTAMPTZ,
    ended_at           TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, user_id),
    UNIQUE (member_id, tenant_id, user_id),
    CHECK (expires_at IS NULL OR expires_at > joined_at),
    CHECK (ended_at IS NULL OR ended_at >= joined_at)
);

CREATE INDEX idx_tenant_member_user_status
    ON dianlian_business.tenant_member (user_id, status, tenant_id);

CREATE TABLE dianlian_business.iam_role
(
    role_code    VARCHAR(64)  PRIMARY KEY
        CHECK (role_code ~ '^[A-Z][A-Z0-9_]{1,63}$'),
    display_name VARCHAR(100) NOT NULL CHECK (BTRIM(display_name) <> ''),
    status       VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE dianlian_business.iam_permission
(
    permission_code VARCHAR(128) PRIMARY KEY
        CHECK (permission_code ~ '^[a-z][a-z0-9_.:-]{1,127}$'),
    display_name    VARCHAR(100) NOT NULL CHECK (BTRIM(display_name) <> ''),
    status          VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE dianlian_business.role_permission
(
    role_code      VARCHAR(64)  NOT NULL
        REFERENCES dianlian_business.iam_role (role_code),
    permission_code VARCHAR(128) NOT NULL
        REFERENCES dianlian_business.iam_permission (permission_code),
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (role_code, permission_code)
);

CREATE TABLE dianlian_business.role_grant
(
    grant_id         UUID         PRIMARY KEY,
    subject_user_id  UUID         NOT NULL
        REFERENCES dianlian_business.user_account (user_id),
    tenant_id        UUID,
    tenant_member_id UUID,
    role_code        VARCHAR(64)  NOT NULL
        REFERENCES dianlian_business.iam_role (role_code),
    scope_type       VARCHAR(32)  NOT NULL CHECK (scope_type IN (
        'PLATFORM',
        'TENANT',
        'DEPARTMENT',
        'PROJECT',
        'CONVERSATION',
        'USER_AGENT',
        'GROUP_AGENT',
        'AGENT',
        'OBJECT_GRANT',
        'SUPPORT_SESSION'
    )),
    scope_id         UUID         NOT NULL,
    granted_at       TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at       TIMESTAMPTZ,
    revoked_at       TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenant_member_id, tenant_id, subject_user_id)
        REFERENCES dianlian_business.tenant_member (member_id, tenant_id, user_id),
    CHECK (
        (tenant_id IS NULL AND tenant_member_id IS NULL AND scope_type = 'PLATFORM')
        OR
        (tenant_id IS NOT NULL AND tenant_member_id IS NOT NULL AND scope_type <> 'PLATFORM')
    ),
    CHECK (expires_at IS NULL OR expires_at > granted_at),
    CHECK (revoked_at IS NULL OR revoked_at >= granted_at)
);

CREATE INDEX idx_role_grant_subject_tenant_active
    ON dianlian_business.role_grant (subject_user_id, tenant_id, role_code)
    WHERE revoked_at IS NULL;

CREATE TABLE dianlian_business.web_session
(
    session_id       UUID        PRIMARY KEY,
    user_id          UUID        NOT NULL REFERENCES dianlian_business.user_account (user_id),
    active_tenant_id UUID,
    active_member_id UUID,
    token_digest     VARCHAR(64) NOT NULL UNIQUE
        CHECK (token_digest ~ '^[0-9a-f]{64}$'),
    issued_at        TIMESTAMPTZ NOT NULL,
    expires_at       TIMESTAMPTZ NOT NULL,
    last_seen_at     TIMESTAMPTZ,
    revoked_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (active_member_id, active_tenant_id, user_id)
        REFERENCES dianlian_business.tenant_member (member_id, tenant_id, user_id),
    CHECK ((active_tenant_id IS NULL) = (active_member_id IS NULL)),
    CHECK (expires_at > issued_at),
    CHECK (last_seen_at IS NULL OR last_seen_at >= issued_at),
    CHECK (revoked_at IS NULL OR revoked_at >= issued_at)
);

CREATE INDEX idx_web_session_user_expiry
    ON dianlian_business.web_session (user_id, expires_at)
    WHERE revoked_at IS NULL;

COMMENT ON COLUMN dianlian_business.web_session.token_digest IS
    'SHA-256 lowercase hexadecimal digest. Raw session tokens must never be persisted.';

COMMENT ON COLUMN dianlian_business.tenant.permission_version IS
    'Increment in the same transaction when tenant-wide authorization inputs change.';

COMMENT ON COLUMN dianlian_business.tenant_member.permission_version IS
    'Increment in the same transaction when member-specific authorization inputs change.';

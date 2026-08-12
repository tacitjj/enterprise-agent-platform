-- Multi-client authentication baseline.
-- Existing V2 session rows remain readable; new credentials and refresh tokens are append-only facts.

ALTER TABLE dianlian_business.web_session
    ALTER COLUMN token_digest DROP NOT NULL,
    ADD COLUMN client_type VARCHAR(24) NOT NULL DEFAULT 'WEB'
        CHECK (client_type IN ('WEB', 'MINI_PROGRAM', 'APP', 'DESKTOP')),
    ADD COLUMN device_id VARCHAR(128),
    ADD COLUMN device_name VARCHAR(100);

COMMENT ON COLUMN dianlian_business.web_session.token_digest IS
    'Legacy opaque-session digest retained only for pre-V5 compatibility. New sessions leave it null.';

CREATE TABLE dianlian_business.user_login_identifier
(
    login_identifier_id UUID         PRIMARY KEY,
    user_id              UUID         NOT NULL
        REFERENCES dianlian_business.user_account (user_id),
    identifier_type      VARCHAR(16)  NOT NULL
        CHECK (identifier_type IN ('USERNAME', 'EMAIL', 'PHONE')),
    normalized_identifier VARCHAR(200) NOT NULL
        CHECK (
            BTRIM(normalized_identifier) <> ''
            AND normalized_identifier = BTRIM(normalized_identifier)
            AND normalized_identifier = LOWER(normalized_identifier)
        ),
    status               VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),
    verified_at          TIMESTAMPTZ,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (identifier_type, normalized_identifier),
    UNIQUE (user_id, identifier_type, normalized_identifier)
);

CREATE TABLE dianlian_business.password_credential
(
    user_id               UUID         PRIMARY KEY
        REFERENCES dianlian_business.user_account (user_id),
    password_hash         VARCHAR(100) NOT NULL CHECK (BTRIM(password_hash) <> ''),
    password_algorithm    VARCHAR(16)  NOT NULL DEFAULT 'BCRYPT'
        CHECK (password_algorithm = 'BCRYPT'),
    failed_attempt_count  INTEGER      NOT NULL DEFAULT 0 CHECK (failed_attempt_count >= 0),
    locked_until          TIMESTAMPTZ,
    last_authenticated_at TIMESTAMPTZ,
    password_changed_at   TIMESTAMPTZ  NOT NULL,
    version               BIGINT       NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE dianlian_business.refresh_token
(
    refresh_token_id       UUID        PRIMARY KEY,
    session_id             UUID        NOT NULL
        REFERENCES dianlian_business.web_session (session_id),
    token_digest           VARCHAR(64) NOT NULL UNIQUE
        CHECK (token_digest ~ '^[0-9a-f]{64}$'),
    issued_at              TIMESTAMPTZ NOT NULL,
    expires_at             TIMESTAMPTZ NOT NULL,
    consumed_at            TIMESTAMPTZ,
    revoked_at             TIMESTAMPTZ,
    replaced_by_token_id   UUID,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (replaced_by_token_id)
        REFERENCES dianlian_business.refresh_token (refresh_token_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (expires_at > issued_at),
    CHECK (consumed_at IS NULL OR consumed_at >= issued_at),
    CHECK (revoked_at IS NULL OR revoked_at >= issued_at),
    CHECK (replaced_by_token_id IS NULL OR consumed_at IS NOT NULL)
);

CREATE INDEX idx_refresh_token_session_active
    ON dianlian_business.refresh_token (session_id, expires_at)
    WHERE consumed_at IS NULL AND revoked_at IS NULL;

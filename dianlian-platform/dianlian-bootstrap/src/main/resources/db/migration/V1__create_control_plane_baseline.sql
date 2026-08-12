CREATE SCHEMA IF NOT EXISTS dianlian_business;

CREATE TABLE dianlian_business.task_step_execution
(
    task_step_id         UUID        NOT NULL,
    tenant_id            UUID        NOT NULL,
    execution_generation BIGINT      NOT NULL CHECK (execution_generation > 0),
    runtime_run_id       UUID        NOT NULL,
    status               VARCHAR(32) NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (task_step_id, execution_generation),
    UNIQUE (runtime_run_id)
);

CREATE INDEX idx_task_step_execution_tenant_status
    ON dianlian_business.task_step_execution (tenant_id, status);

CREATE TABLE dianlian_business.outbox_event
(
    event_id       UUID         PRIMARY KEY,
    tenant_id      UUID         NOT NULL,
    aggregate_type VARCHAR(64)  NOT NULL,
    aggregate_id   UUID         NOT NULL,
    event_type     VARCHAR(128) NOT NULL,
    payload        JSONB        NOT NULL,
    occurred_at    TIMESTAMPTZ  NOT NULL,
    published_at   TIMESTAMPTZ,
    attempt_count  INTEGER      NOT NULL DEFAULT 0 CHECK (attempt_count >= 0)
);

CREATE INDEX idx_outbox_event_unpublished
    ON dianlian_business.outbox_event (occurred_at, event_id)
    WHERE published_at IS NULL;

CREATE TABLE dianlian_business.idempotency_record
(
    tenant_id      UUID         NOT NULL,
    actor_id       UUID         NOT NULL,
    operation      VARCHAR(64)  NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL,
    request_hash   VARCHAR(128) NOT NULL,
    resource_type  VARCHAR(64),
    resource_id    UUID,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at     TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (tenant_id, actor_id, operation, idempotency_key),
    CHECK (expires_at > created_at)
);

CREATE INDEX idx_idempotency_record_expiry
    ON dianlian_business.idempotency_record (expires_at);

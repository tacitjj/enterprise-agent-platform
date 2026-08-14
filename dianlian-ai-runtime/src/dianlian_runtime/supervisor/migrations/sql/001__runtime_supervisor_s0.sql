-- Purpose: create the dormant S0 ownership facts for the point-owned Run Supervisor.
-- Scope: PostgreSQL 15+; only the deer_runtime schema is affected.
-- Preconditions: apply through the single dianlian-supervisor-migrate job after 000.
-- Idempotency: the migration ledger applies this immutable file once by checksum.
-- Activation: this migration does not register a RunStore, worker, or application service.
-- Rollback: deploy the previous runtime first; removal requires a reviewed later migration.

CREATE TABLE deer_runtime.runtime_thread
(
    tenant_id               UUID         NOT NULL,
    runtime_thread_id       UUID         NOT NULL,
    task_run_id             UUID         NOT NULL,
    task_step_id            UUID         NOT NULL,
    agent_instance_id       UUID         NOT NULL,
    user_id                 UUID         NOT NULL,
    conversation_id         UUID         NOT NULL,
    source_message_id       UUID,
    runtime_thread_revision BIGINT       NOT NULL DEFAULT 1
        CHECK (runtime_thread_revision > 0),
    runtime_type            VARCHAR(32)  NOT NULL
        CHECK (runtime_type ~ '^[A-Z][A-Z0-9_]{0,31}$'),
    runtime_agent_name      VARCHAR(128) NOT NULL
        CHECK (BTRIM(runtime_agent_name) <> ''),
    capability_version_id   UUID         NOT NULL,
    prompt_version_id       UUID         NOT NULL,
    model_policy_id         UUID         NOT NULL,
    budget_reservation_id   UUID         NOT NULL,
    input_artifact_ids      JSONB        NOT NULL DEFAULT '[]'::JSONB
        CHECK (JSONB_TYPEOF(input_artifact_ids) = 'array'),
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    PRIMARY KEY (tenant_id, runtime_thread_id),
    UNIQUE (tenant_id, runtime_thread_id, task_step_id),
    UNIQUE (tenant_id, task_step_id, runtime_thread_revision)
);

CREATE TABLE deer_runtime.runtime_run
(
    tenant_id                       UUID         NOT NULL,
    runtime_run_id                  UUID         NOT NULL,
    runtime_thread_id               UUID         NOT NULL,
    task_step_id                    UUID         NOT NULL,
    task_execution_generation       BIGINT       NOT NULL
        CHECK (task_execution_generation > 0),
    status                          VARCHAR(32)  NOT NULL,
    operation_kind                  VARCHAR(16)  NOT NULL
        CHECK (operation_kind IN ('START', 'CONTINUE', 'RETRY', 'REPLAN', 'REPLACE')),
    multitask_strategy              VARCHAR(16)  NOT NULL DEFAULT 'REJECT'
        CHECK (multitask_strategy IN ('REJECT', 'SAFE_QUEUE', 'INTERRUPT')),
    request_hash                    CHAR(64)     NOT NULL
        CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    idempotency_key                 VARCHAR(200) NOT NULL
        CHECK (BTRIM(idempotency_key) <> ''),
    predecessor_runtime_run_id      UUID,
    expected_checkpoint_id          VARCHAR(160)
        CHECK (expected_checkpoint_id IS NULL OR BTRIM(expected_checkpoint_id) <> ''),
    current_checkpoint_id           VARCHAR(160)
        CHECK (current_checkpoint_id IS NULL OR BTRIM(current_checkpoint_id) <> ''),
    current_checkpoint_sequence_no  BIGINT
        CHECK (current_checkpoint_sequence_no IS NULL OR current_checkpoint_sequence_no > 0),
    next_event_sequence_no          BIGINT       NOT NULL DEFAULT 1
        CHECK (next_event_sequence_no > 0),
    event_retention_floor_sequence  BIGINT       NOT NULL DEFAULT 1
        CHECK (event_retention_floor_sequence > 0),
    run_version                     BIGINT       NOT NULL DEFAULT 1
        CHECK (run_version > 0),
    terminal_reason                 VARCHAR(64)
        CHECK (terminal_reason IS NULL OR terminal_reason ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    terminal_event_id               UUID,
    lease_owner                     VARCHAR(160)
        CHECK (lease_owner IS NULL OR BTRIM(lease_owner) <> ''),
    lease_until                     TIMESTAMPTZ,
    lease_epoch                     BIGINT       NOT NULL DEFAULT 0
        CHECK (lease_epoch >= 0),
    heartbeat_at                    TIMESTAMPTZ,
    attempt                         INTEGER      NOT NULL DEFAULT 0
        CHECK (attempt >= 0),
    runtime_version                 VARCHAR(128) NOT NULL
        CHECK (BTRIM(runtime_version) <> ''),
    agent_name                      VARCHAR(128) NOT NULL
        CHECK (BTRIM(agent_name) <> ''),
    failure_code                    VARCHAR(64)
        CHECK (failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    cancel_requested_at             TIMESTAMPTZ,
    started_at                      TIMESTAMPTZ,
    terminal_at                     TIMESTAMPTZ,
    created_at                      TIMESTAMPTZ  NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    updated_at                      TIMESTAMPTZ  NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    PRIMARY KEY (tenant_id, runtime_run_id),
    UNIQUE (tenant_id, runtime_run_id, runtime_thread_id),
    UNIQUE (tenant_id, runtime_thread_id, idempotency_key),
    UNIQUE (tenant_id, task_step_id, task_execution_generation),
    FOREIGN KEY (tenant_id, runtime_thread_id, task_step_id)
        REFERENCES deer_runtime.runtime_thread (tenant_id, runtime_thread_id, task_step_id),
    FOREIGN KEY (tenant_id, predecessor_runtime_run_id, runtime_thread_id)
        REFERENCES deer_runtime.runtime_run (tenant_id, runtime_run_id, runtime_thread_id),
    CHECK (
        status IN (
            'QUEUED', 'RUNNING', 'WAITING_USER_INPUT', 'WAITING_AUTH', 'PAUSED',
            'CANCEL_REQUESTED', 'CANCELLING',
            'COMPLETED', 'FAILED', 'CANCELLED', 'CANCEL_OUTCOME_UNKNOWN'
        )
    ),
    CHECK (
        (operation_kind = 'START' AND predecessor_runtime_run_id IS NULL)
        OR (operation_kind <> 'START' AND predecessor_runtime_run_id IS NOT NULL)
    ),
    CHECK (
        predecessor_runtime_run_id IS NULL
        OR predecessor_runtime_run_id <> runtime_run_id
    ),
    CHECK (
        (current_checkpoint_id IS NULL AND current_checkpoint_sequence_no IS NULL)
        OR (current_checkpoint_id IS NOT NULL AND current_checkpoint_sequence_no IS NOT NULL)
    ),
    CHECK (event_retention_floor_sequence <= next_event_sequence_no),
    CHECK (
        (lease_owner IS NULL AND lease_until IS NULL AND heartbeat_at IS NULL)
        OR (lease_owner IS NOT NULL AND lease_until IS NOT NULL AND heartbeat_at IS NOT NULL
            AND lease_epoch > 0 AND lease_until >= heartbeat_at)
    ),
    CHECK (
        status <> 'QUEUED'
        OR (lease_owner IS NULL AND lease_epoch = 0 AND attempt = 0
            AND started_at IS NULL AND terminal_at IS NULL)
    ),
    CHECK (
        status NOT IN (
            'RUNNING', 'WAITING_USER_INPUT', 'WAITING_AUTH', 'PAUSED',
            'CANCEL_REQUESTED', 'CANCELLING'
        )
        OR (lease_owner IS NOT NULL AND lease_epoch > 0 AND started_at IS NOT NULL)
    ),
    CHECK (
        (status IN ('COMPLETED', 'FAILED', 'CANCELLED', 'CANCEL_OUTCOME_UNKNOWN')
            AND lease_owner IS NULL AND terminal_at IS NOT NULL
            AND terminal_reason IS NOT NULL AND terminal_event_id IS NOT NULL)
        OR
        (status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED', 'CANCEL_OUTCOME_UNKNOWN')
            AND terminal_at IS NULL AND terminal_reason IS NULL AND terminal_event_id IS NULL)
    ),
    CHECK (
        cancel_requested_at IS NULL
        OR status IN (
            'CANCEL_REQUESTED', 'CANCELLING', 'COMPLETED', 'FAILED',
            'CANCELLED', 'CANCEL_OUTCOME_UNKNOWN'
        )
    )
);

CREATE UNIQUE INDEX uq_runtime_run_thread_active
    ON deer_runtime.runtime_run (tenant_id, runtime_thread_id)
    WHERE status IN (
        'QUEUED', 'RUNNING', 'WAITING_USER_INPUT', 'WAITING_AUTH', 'PAUSED',
        'CANCEL_REQUESTED', 'CANCELLING'
    );

CREATE INDEX idx_runtime_run_claim
    ON deer_runtime.runtime_run (status, created_at, tenant_id, runtime_run_id)
    WHERE status = 'QUEUED';

CREATE INDEX idx_runtime_run_expired_lease
    ON deer_runtime.runtime_run (lease_until, tenant_id, runtime_run_id)
    WHERE status IN (
        'RUNNING', 'WAITING_USER_INPUT', 'WAITING_AUTH', 'PAUSED',
        'CANCEL_REQUESTED', 'CANCELLING'
    ) AND lease_owner IS NOT NULL;

CREATE TABLE deer_runtime.runtime_run_control
(
    tenant_id            UUID         NOT NULL,
    control_id           UUID         NOT NULL,
    runtime_run_id       UUID         NOT NULL,
    runtime_thread_id    UUID         NOT NULL,
    control_type         VARCHAR(16)  NOT NULL
        CHECK (control_type IN ('PAUSE', 'RESUME', 'CANCEL')),
    actor_id             UUID         NOT NULL,
    reason_code          VARCHAR(64)  NOT NULL
        CHECK (reason_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    expected_run_version BIGINT       NOT NULL CHECK (expected_run_version > 0),
    idempotency_key      VARCHAR(200) NOT NULL CHECK (BTRIM(idempotency_key) <> ''),
    request_hash         CHAR(64)     NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    PRIMARY KEY (tenant_id, control_id),
    UNIQUE (tenant_id, runtime_run_id, idempotency_key),
    FOREIGN KEY (tenant_id, runtime_run_id, runtime_thread_id)
        REFERENCES deer_runtime.runtime_run (tenant_id, runtime_run_id, runtime_thread_id)
);

CREATE TABLE deer_runtime.runtime_run_event
(
    tenant_id         UUID        NOT NULL,
    runtime_run_id    UUID        NOT NULL,
    runtime_thread_id UUID        NOT NULL,
    event_id          UUID        NOT NULL,
    sequence_no       BIGINT      NOT NULL CHECK (sequence_no > 0),
    event_type        VARCHAR(64) NOT NULL
        CHECK (event_type ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    event_version     SMALLINT    NOT NULL DEFAULT 1 CHECK (event_version > 0),
    run_version       BIGINT      NOT NULL CHECK (run_version > 0),
    lease_owner       VARCHAR(160)
        CHECK (lease_owner IS NULL OR BTRIM(lease_owner) <> ''),
    lease_epoch       BIGINT      NOT NULL CHECK (lease_epoch >= 0),
    checkpoint_id     VARCHAR(160)
        CHECK (checkpoint_id IS NULL OR BTRIM(checkpoint_id) <> ''),
    payload           JSONB       NOT NULL DEFAULT '{}'::JSONB
        CHECK (JSONB_TYPEOF(payload) = 'object' AND OCTET_LENGTH(payload::TEXT) <= 65536),
    occurred_at       TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    PRIMARY KEY (tenant_id, runtime_run_id, sequence_no),
    UNIQUE (tenant_id, runtime_run_id, event_id),
    CHECK (
        (lease_epoch = 0 AND lease_owner IS NULL)
        OR (lease_epoch > 0 AND lease_owner IS NOT NULL)
    ),
    FOREIGN KEY (tenant_id, runtime_run_id, runtime_thread_id)
        REFERENCES deer_runtime.runtime_run (tenant_id, runtime_run_id, runtime_thread_id)
);

CREATE INDEX idx_runtime_run_event_replay
    ON deer_runtime.runtime_run_event (tenant_id, runtime_run_id, sequence_no);

CREATE TABLE deer_runtime.runtime_checkpoint_ref
(
    tenant_id                UUID         NOT NULL,
    runtime_run_id           UUID         NOT NULL,
    runtime_thread_id        UUID         NOT NULL,
    checkpoint_id            VARCHAR(160) NOT NULL CHECK (BTRIM(checkpoint_id) <> ''),
    checkpoint_namespace     VARCHAR(160) NOT NULL DEFAULT '',
    sequence_no              BIGINT       NOT NULL CHECK (sequence_no > 0),
    event_id                 UUID         NOT NULL,
    run_version              BIGINT       NOT NULL CHECK (run_version > 0),
    lease_epoch              BIGINT       NOT NULL CHECK (lease_epoch > 0),
    checkpoint_schema_version VARCHAR(64) NOT NULL
        CHECK (BTRIM(checkpoint_schema_version) <> ''),
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    PRIMARY KEY (tenant_id, runtime_run_id, checkpoint_id),
    UNIQUE (tenant_id, runtime_run_id, sequence_no),
    UNIQUE (tenant_id, runtime_run_id, checkpoint_id, sequence_no),
    FOREIGN KEY (tenant_id, runtime_run_id, runtime_thread_id)
        REFERENCES deer_runtime.runtime_run (tenant_id, runtime_run_id, runtime_thread_id),
    FOREIGN KEY (tenant_id, runtime_run_id, event_id)
        REFERENCES deer_runtime.runtime_run_event (tenant_id, runtime_run_id, event_id)
);

ALTER TABLE deer_runtime.runtime_run
    ADD CONSTRAINT fk_runtime_run_current_checkpoint
    FOREIGN KEY (
        tenant_id, runtime_run_id, current_checkpoint_id, current_checkpoint_sequence_no
    )
    REFERENCES deer_runtime.runtime_checkpoint_ref (
        tenant_id, runtime_run_id, checkpoint_id, sequence_no
    )
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE deer_runtime.runtime_run
    ADD CONSTRAINT fk_runtime_run_terminal_event
    FOREIGN KEY (tenant_id, runtime_run_id, terminal_event_id)
    REFERENCES deer_runtime.runtime_run_event (tenant_id, runtime_run_id, event_id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE FUNCTION deer_runtime.reject_append_only_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$function$;

CREATE TRIGGER trg_runtime_thread_append_only
    BEFORE UPDATE OR DELETE ON deer_runtime.runtime_thread
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

CREATE TRIGGER trg_runtime_run_control_append_only
    BEFORE UPDATE OR DELETE ON deer_runtime.runtime_run_control
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

CREATE TRIGGER trg_runtime_run_event_append_only
    BEFORE UPDATE OR DELETE ON deer_runtime.runtime_run_event
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

CREATE TRIGGER trg_runtime_checkpoint_ref_append_only
    BEFORE UPDATE OR DELETE ON deer_runtime.runtime_checkpoint_ref
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

CREATE TRIGGER trg_runtime_thread_no_truncate
    BEFORE TRUNCATE ON deer_runtime.runtime_thread
    FOR EACH STATEMENT EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

CREATE TRIGGER trg_runtime_run_no_truncate
    BEFORE TRUNCATE ON deer_runtime.runtime_run
    FOR EACH STATEMENT EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

CREATE TRIGGER trg_runtime_run_control_no_truncate
    BEFORE TRUNCATE ON deer_runtime.runtime_run_control
    FOR EACH STATEMENT EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

CREATE TRIGGER trg_runtime_run_event_no_truncate
    BEFORE TRUNCATE ON deer_runtime.runtime_run_event
    FOR EACH STATEMENT EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

CREATE TRIGGER trg_runtime_checkpoint_ref_no_truncate
    BEFORE TRUNCATE ON deer_runtime.runtime_checkpoint_ref
    FOR EACH STATEMENT EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

CREATE FUNCTION deer_runtime.protect_runtime_run_identity()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'QUEUED' THEN
            RAISE EXCEPTION 'runtime_run must be admitted as QUEUED'
                USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'runtime_run cannot be deleted' USING ERRCODE = '55000';
    END IF;
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.runtime_run_id IS DISTINCT FROM OLD.runtime_run_id
       OR NEW.runtime_thread_id IS DISTINCT FROM OLD.runtime_thread_id
       OR NEW.task_step_id IS DISTINCT FROM OLD.task_step_id
       OR NEW.task_execution_generation IS DISTINCT FROM OLD.task_execution_generation
       OR NEW.operation_kind IS DISTINCT FROM OLD.operation_kind
       OR NEW.multitask_strategy IS DISTINCT FROM OLD.multitask_strategy
       OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
       OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
       OR NEW.predecessor_runtime_run_id IS DISTINCT FROM OLD.predecessor_runtime_run_id
       OR NEW.expected_checkpoint_id IS DISTINCT FROM OLD.expected_checkpoint_id
       OR NEW.runtime_version IS DISTINCT FROM OLD.runtime_version
       OR NEW.agent_name IS DISTINCT FROM OLD.agent_name
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'runtime_run identity is immutable' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE TRIGGER trg_runtime_run_identity
    BEFORE INSERT OR UPDATE OR DELETE ON deer_runtime.runtime_run
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.protect_runtime_run_identity();

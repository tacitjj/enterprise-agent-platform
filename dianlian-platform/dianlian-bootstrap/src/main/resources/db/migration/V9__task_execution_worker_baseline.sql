-- Durable Java task-step execution, stage artifacts and replayable task events.
-- External model calls happen outside database transactions; leases and epochs fence stale workers.

ALTER TABLE dianlian_business.task_step
    ADD COLUMN executor_type VARCHAR(32),
    ADD COLUMN active_execution_generation BIGINT,
    ADD COLUMN active_runtime_run_id UUID,
    ADD COLUMN blocker_code VARCHAR(128);

UPDATE dianlian_business.task_step
   SET executor_type = CASE
       WHEN human_checkpoint THEN 'HUMAN_CHECKPOINT'
       ELSE 'UNRESOLVED'
   END,
       blocker_code = CASE
       WHEN human_checkpoint THEN 'HUMAN_CONFIRMATION_REQUIRED'
       ELSE 'EXECUTOR_TYPE_UNRESOLVED'
   END
 WHERE executor_type IS NULL;

ALTER TABLE dianlian_business.task_step
    ALTER COLUMN executor_type SET NOT NULL,
    ADD CONSTRAINT chk_task_step_executor_type CHECK (executor_type IN (
        'MODEL', 'RETRIEVAL', 'RULE_ENGINE', 'TOOL', 'HUMAN_CHECKPOINT', 'SUBTASK',
        'UNRESOLVED'
    )),
    ADD CONSTRAINT chk_task_step_active_execution CHECK (
        (active_execution_generation IS NULL AND active_runtime_run_id IS NULL)
        OR
        (active_execution_generation IS NOT NULL AND active_execution_generation > 0
            AND active_runtime_run_id IS NOT NULL)
    ),
    ADD CONSTRAINT uq_task_step_tenant_step UNIQUE (tenant_id, step_id);

ALTER TABLE dianlian_business.task_step_execution
    ADD COLUMN operation_kind VARCHAR(16) NOT NULL DEFAULT 'START',
    ADD COLUMN idempotency_key VARCHAR(200),
    ADD COLUMN request_hash VARCHAR(128),
    ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN lease_owner VARCHAR(160),
    ADD COLUMN lease_until TIMESTAMPTZ,
    ADD COLUMN lease_epoch BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN model_route_binding_id UUID,
    ADD COLUMN model_route_state_version BIGINT,
    ADD COLUMN model_definition_id UUID,
    ADD COLUMN model_reservation_ceiling BIGINT,
    ADD COLUMN provider_response_text TEXT,
    ADD COLUMN provider_request_id VARCHAR(256),
    ADD COLUMN input_tokens INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN output_tokens INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN usage_status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    ADD COLUMN usage_estimated BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN captured_amount BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN failure_code VARCHAR(128),
    ADD COLUMN started_at TIMESTAMPTZ,
    ADD COLUMN terminal_at TIMESTAMPTZ;

UPDATE dianlian_business.task_step_execution
   SET idempotency_key = 'task-step:' || task_step_id || ':' || execution_generation,
       request_hash = md5(task_step_id::text || ':' || execution_generation::text)
 WHERE idempotency_key IS NULL OR request_hash IS NULL;

ALTER TABLE dianlian_business.task_step_execution
    ALTER COLUMN idempotency_key SET NOT NULL,
    ALTER COLUMN request_hash SET NOT NULL,
    ADD CONSTRAINT fk_task_step_execution_step
        FOREIGN KEY (tenant_id, task_step_id)
        REFERENCES dianlian_business.task_step (tenant_id, step_id),
    ADD CONSTRAINT chk_task_step_execution_operation CHECK (operation_kind = 'START'),
    ADD CONSTRAINT chk_task_step_execution_status CHECK (status IN (
        'PREPARED', 'RUNNING', 'RESPONSE_RECEIVED', 'USAGE_PENDING',
        'PROVIDER_FAILED', 'SUCCEEDED', 'FAILED_PROVIDER', 'FAILED_BILLING',
        'BLOCKED_SIDE_EFFECT_RECONCILIATION'
    )),
    ADD CONSTRAINT chk_task_step_execution_lease CHECK (
        (lease_owner IS NULL AND lease_until IS NULL)
        OR (lease_owner IS NOT NULL AND lease_until IS NOT NULL)
    ),
    ADD CONSTRAINT chk_task_step_execution_route CHECK (
        (model_route_binding_id IS NULL AND model_route_state_version IS NULL
            AND model_definition_id IS NULL AND model_reservation_ceiling IS NULL)
        OR
        (model_route_binding_id IS NOT NULL AND model_route_state_version > 0
            AND model_definition_id IS NOT NULL AND model_reservation_ceiling > 0)
    ),
    ADD CONSTRAINT chk_task_step_execution_usage CHECK (
        input_tokens >= 0 AND output_tokens >= 0 AND captured_amount >= 0
        AND usage_status IN ('PENDING', 'CONFIRMED', 'ESTIMATED')
    ),
    ADD CONSTRAINT fk_task_step_execution_model_route
        FOREIGN KEY (model_route_binding_id, model_definition_id)
        REFERENCES dianlian_business.model_route_binding (route_binding_id, model_definition_id);

CREATE INDEX idx_task_step_execution_worker
    ON dianlian_business.task_step_execution (status, next_attempt_at, created_at, runtime_run_id)
    WHERE status IN ('PREPARED', 'RUNNING', 'RESPONSE_RECEIVED', 'PROVIDER_FAILED');

CREATE TABLE dianlian_business.task_artifact_version
(
    artifact_version_id       UUID          PRIMARY KEY,
    tenant_id                 UUID          NOT NULL,
    task_id                   UUID          NOT NULL,
    source_step_id            UUID          NOT NULL,
    execution_generation      BIGINT        NOT NULL,
    artifact_type             VARCHAR(64)   NOT NULL,
    title                     VARCHAR(200)  NOT NULL,
    status                    VARCHAR(16)   NOT NULL,
    content_text              TEXT          NOT NULL,
    content_hash              VARCHAR(128)  NOT NULL,
    parent_artifact_version_id UUID,
    usage_estimated           BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at                TIMESTAMPTZ   NOT NULL,
    UNIQUE (task_id, source_step_id, execution_generation),
    UNIQUE (tenant_id, artifact_version_id),
    FOREIGN KEY (tenant_id, task_id)
        REFERENCES dianlian_business.task_run (tenant_id, task_id),
    FOREIGN KEY (tenant_id, source_step_id)
        REFERENCES dianlian_business.task_step (tenant_id, step_id),
    FOREIGN KEY (parent_artifact_version_id)
        REFERENCES dianlian_business.task_artifact_version (artifact_version_id),
    CHECK (execution_generation > 0),
    CHECK (status IN ('READY', 'STALE')),
    CHECK (BTRIM(content_text) <> ''),
    CHECK (BTRIM(content_hash) <> '')
);

CREATE INDEX idx_task_artifact_task_created
    ON dianlian_business.task_artifact_version (tenant_id, task_id, created_at, artifact_version_id);

CREATE TABLE dianlian_business.task_event
(
    stream_sequence    BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id           UUID         NOT NULL UNIQUE,
    tenant_id          UUID         NOT NULL,
    task_id            UUID         NOT NULL,
    task_version       BIGINT       NOT NULL,
    event_type         VARCHAR(128) NOT NULL,
    visibility_version VARCHAR(128) NOT NULL,
    trace_id           UUID         NOT NULL,
    payload            JSONB        NOT NULL,
    occurred_at        TIMESTAMPTZ  NOT NULL,
    FOREIGN KEY (tenant_id, task_id)
        REFERENCES dianlian_business.task_run (tenant_id, task_id),
    CHECK (task_version > 0),
    CHECK (JSONB_TYPEOF(payload) = 'object')
);

CREATE INDEX idx_task_event_replay
    ON dianlian_business.task_event (tenant_id, task_id, stream_sequence);

CREATE INDEX idx_task_event_version
    ON dianlian_business.task_event (tenant_id, task_id, task_version, stream_sequence);

-- Existing development tasks already have a task.created outbox fact. Backfill it so
-- their snapshot resumeEventId resolves to a durable journal cursor after this migration.
INSERT INTO dianlian_business.task_event
    (event_id, tenant_id, task_id, task_version, event_type, visibility_version,
     trace_id, payload, occurred_at)
SELECT event.event_id,
       event.tenant_id,
       event.aggregate_id,
       CASE
           WHEN event.payload ->> 'taskVersion' ~ '^[1-9][0-9]*$'
               THEN (event.payload ->> 'taskVersion')::BIGINT
           ELSE task.task_version
       END,
       CASE WHEN event.event_type = 'task.created' THEN 'task.started' ELSE event.event_type END,
       'task-participants:v1',
       event.event_id,
       event.payload,
       event.occurred_at
  FROM dianlian_business.outbox_event event
  JOIN dianlian_business.task_run task
    ON task.tenant_id = event.tenant_id AND task.task_id = event.aggregate_id
 WHERE event.aggregate_type = 'TASK'
ON CONFLICT DO NOTHING;

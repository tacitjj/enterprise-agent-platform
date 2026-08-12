-- Point accounting and generic task creation baseline.
-- This migration is append-only: immutable ledger facts are corrected by future reversing entries.

INSERT INTO dianlian_business.iam_permission (permission_code, display_name, status)
VALUES ('task.create', '创建任务并预占智点', 'ACTIVE')
ON CONFLICT (permission_code) DO NOTHING;

CREATE TABLE dianlian_business.point_account
(
    account_id                     UUID        PRIMARY KEY,
    tenant_id                      UUID        NOT NULL,
    ledger_scope_id                UUID        NOT NULL,
    account_type                   VARCHAR(32) NOT NULL,
    unit_code                      VARCHAR(32) NOT NULL,
    status                         VARCHAR(16) NOT NULL,
    available_amount_snapshot      BIGINT      NOT NULL DEFAULT 0,
    reserved_amount_snapshot       BIGINT      NOT NULL DEFAULT 0,
    gross_captured_amount_snapshot BIGINT      NOT NULL DEFAULT 0,
    returned_amount_snapshot       BIGINT      NOT NULL DEFAULT 0,
    net_consumed_amount_snapshot   BIGINT      NOT NULL DEFAULT 0,
    version                        BIGINT      NOT NULL DEFAULT 0,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, account_type),
    UNIQUE (tenant_id, account_id),
    UNIQUE (tenant_id, ledger_scope_id),
    CHECK (account_type = 'MAIN'),
    CHECK (unit_code = 'POINT'),
    CHECK (status IN ('ACTIVE', 'FROZEN', 'CLOSED')),
    CHECK (available_amount_snapshot >= 0),
    CHECK (reserved_amount_snapshot >= 0),
    CHECK (gross_captured_amount_snapshot >= 0),
    CHECK (returned_amount_snapshot >= 0),
    CHECK (net_consumed_amount_snapshot >= 0),
    CHECK (version >= 0)
);

CREATE TABLE dianlian_business.point_lot
(
    lot_id                    UUID         PRIMARY KEY,
    tenant_id                 UUID         NOT NULL,
    account_id                UUID         NOT NULL,
    source_type               VARCHAR(32)  NOT NULL,
    source_id                 VARCHAR(128) NOT NULL,
    total_amount              BIGINT       NOT NULL,
    available_amount_snapshot BIGINT       NOT NULL,
    reserved_amount_snapshot  BIGINT       NOT NULL DEFAULT 0,
    expires_at                TIMESTAMPTZ,
    priority                  INTEGER      NOT NULL DEFAULT 100,
    status                    VARCHAR(16)  NOT NULL,
    created_at                TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, lot_id),
    UNIQUE (tenant_id, source_type, source_id),
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES dianlian_business.point_account (tenant_id, account_id),
    CHECK (source_type IN ('PURCHASE_REF', 'SUBSCRIPTION', 'GRANT', 'CREDIT_RETURN', 'ADJUSTMENT')),
    CHECK (total_amount > 0),
    CHECK (available_amount_snapshot >= 0),
    CHECK (reserved_amount_snapshot >= 0),
    CHECK (available_amount_snapshot + reserved_amount_snapshot <= total_amount),
    CHECK (status IN ('ACTIVE', 'EXHAUSTED', 'EXPIRED'))
);

CREATE INDEX idx_point_lot_reservation_order
    ON dianlian_business.point_lot
        (account_id, status, expires_at, priority, lot_id)
    WHERE available_amount_snapshot > 0;

CREATE TABLE dianlian_business.point_ledger_account
(
    ledger_account_id UUID        PRIMARY KEY,
    tenant_id         UUID        NOT NULL,
    ledger_scope_id   UUID        NOT NULL,
    owner_type        VARCHAR(16) NOT NULL,
    owner_id          UUID        NOT NULL,
    bucket_code       VARCHAR(32) NOT NULL,
    unit_code         VARCHAR(32) NOT NULL,
    status            VARCHAR(16) NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (tenant_id, ledger_scope_id, ledger_account_id),
    UNIQUE (tenant_id, ledger_scope_id, bucket_code),
    CHECK (owner_type IN ('PLATFORM', 'TENANT')),
    CHECK (bucket_code IN ('AVAILABLE', 'RESERVED', 'CONSUMED', 'ISSUANCE', 'EXPIRATION')),
    CHECK (unit_code = 'POINT'),
    CHECK (status IN ('ACTIVE', 'CLOSED'))
);

CREATE TABLE dianlian_business.point_ledger_transaction
(
    transaction_id        UUID         PRIMARY KEY,
    tenant_id             UUID         NOT NULL,
    ledger_scope_id       UUID         NOT NULL,
    transaction_type      VARCHAR(16)  NOT NULL,
    idempotency_key       VARCHAR(200) NOT NULL,
    business_type         VARCHAR(64)  NOT NULL,
    business_id           UUID         NOT NULL,
    original_transaction_id UUID,
    reason_code           VARCHAR(64)  NOT NULL,
    operator_id           UUID         NOT NULL,
    status                VARCHAR(16)  NOT NULL,
    created_at            TIMESTAMPTZ  NOT NULL,
    posted_at             TIMESTAMPTZ  NOT NULL,
    UNIQUE (tenant_id, transaction_id),
    UNIQUE (tenant_id, ledger_scope_id, transaction_id),
    UNIQUE (tenant_id, ledger_scope_id, idempotency_key),
    CHECK (transaction_type IN ('GRANT', 'RESERVE', 'CAPTURE', 'RELEASE', 'REFUND', 'EXPIRE', 'ADJUST')),
    CHECK (status = 'POSTED')
);

CREATE TABLE dianlian_business.point_reservation
(
    reservation_id               UUID         PRIMARY KEY,
    tenant_id                    UUID         NOT NULL,
    account_id                   UUID         NOT NULL,
    business_type                VARCHAR(64)  NOT NULL,
    business_id                  UUID         NOT NULL,
    billing_scope_type           VARCHAR(64)  NOT NULL,
    billing_scope_id             UUID         NOT NULL,
    amount                       BIGINT       NOT NULL,
    captured_amount              BIGINT       NOT NULL DEFAULT 0,
    released_amount              BIGINT       NOT NULL DEFAULT 0,
    status                       VARCHAR(32)  NOT NULL,
    idempotency_key              VARCHAR(200) NOT NULL,
    reserve_ledger_transaction_id UUID        NOT NULL,
    created_by                   UUID         NOT NULL,
    created_at                   TIMESTAMPTZ  NOT NULL,
    updated_at                   TIMESTAMPTZ  NOT NULL,
    UNIQUE (tenant_id, reservation_id),
    UNIQUE (tenant_id, idempotency_key),
    FOREIGN KEY (tenant_id, account_id)
        REFERENCES dianlian_business.point_account (tenant_id, account_id),
    FOREIGN KEY (tenant_id, reserve_ledger_transaction_id)
        REFERENCES dianlian_business.point_ledger_transaction (tenant_id, transaction_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (amount > 0),
    CHECK (captured_amount >= 0),
    CHECK (released_amount >= 0),
    CHECK (captured_amount + released_amount <= amount),
    CHECK (status IN ('ACTIVE', 'PARTIALLY_CAPTURED', 'CAPTURED', 'RELEASED', 'EXPIRED'))
);

CREATE INDEX idx_point_reservation_account_status
    ON dianlian_business.point_reservation (account_id, status, created_at);

CREATE TABLE dianlian_business.point_reservation_allocation
(
    tenant_id      UUID   NOT NULL,
    reservation_id UUID   NOT NULL,
    lot_id          UUID   NOT NULL,
    amount          BIGINT NOT NULL,
    PRIMARY KEY (reservation_id, lot_id),
    FOREIGN KEY (tenant_id, reservation_id)
        REFERENCES dianlian_business.point_reservation (tenant_id, reservation_id),
    FOREIGN KEY (tenant_id, lot_id)
        REFERENCES dianlian_business.point_lot (tenant_id, lot_id),
    CHECK (amount > 0)
);

CREATE TABLE dianlian_business.point_ledger_entry
(
    entry_id          UUID        PRIMARY KEY,
    tenant_id         UUID        NOT NULL,
    ledger_scope_id   UUID        NOT NULL,
    transaction_id    UUID        NOT NULL,
    ledger_account_id UUID        NOT NULL,
    unit_code         VARCHAR(32) NOT NULL,
    direction         VARCHAR(8)  NOT NULL,
    amount            BIGINT      NOT NULL,
    point_lot_id      UUID,
    sequence_no       INTEGER     NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL,
    UNIQUE (transaction_id, sequence_no),
    FOREIGN KEY (tenant_id, ledger_scope_id, transaction_id)
        REFERENCES dianlian_business.point_ledger_transaction
            (tenant_id, ledger_scope_id, transaction_id),
    FOREIGN KEY (tenant_id, ledger_scope_id, ledger_account_id)
        REFERENCES dianlian_business.point_ledger_account
            (tenant_id, ledger_scope_id, ledger_account_id),
    FOREIGN KEY (tenant_id, point_lot_id)
        REFERENCES dianlian_business.point_lot (tenant_id, lot_id),
    CHECK (unit_code = 'POINT'),
    CHECK (direction IN ('DEBIT', 'CREDIT')),
    CHECK (amount > 0),
    CHECK (sequence_no > 0)
);

CREATE INDEX idx_point_ledger_entry_transaction
    ON dianlian_business.point_ledger_entry (transaction_id, sequence_no);

CREATE OR REPLACE FUNCTION dianlian_business.reject_immutable_point_ledger_change()
RETURNS TRIGGER AS
$$
BEGIN
    RAISE EXCEPTION 'posted point ledger facts are immutable';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_point_ledger_transaction_immutable
    BEFORE UPDATE OR DELETE ON dianlian_business.point_ledger_transaction
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.reject_immutable_point_ledger_change();

CREATE TRIGGER trg_point_ledger_entry_immutable
    BEFORE UPDATE OR DELETE ON dianlian_business.point_ledger_entry
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.reject_immutable_point_ledger_change();

CREATE OR REPLACE FUNCTION dianlian_business.assert_balanced_point_ledger_transaction()
RETURNS TRIGGER AS
$$
DECLARE
    target_transaction_id UUID := NEW.transaction_id;
    entry_count            BIGINT;
    point_balance          BIGINT;
BEGIN
    SELECT COUNT(*),
           COALESCE(SUM(CASE WHEN direction = 'DEBIT' THEN amount ELSE -amount END), 0)
      INTO entry_count, point_balance
      FROM dianlian_business.point_ledger_entry
     WHERE transaction_id = target_transaction_id;

    IF entry_count < 2 OR point_balance <> 0 THEN
        RAISE EXCEPTION 'point ledger transaction % is not balanced', target_transaction_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_point_ledger_entry_balanced
    AFTER INSERT ON dianlian_business.point_ledger_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_balanced_point_ledger_transaction();

CREATE CONSTRAINT TRIGGER trg_point_ledger_transaction_balanced
    AFTER INSERT ON dianlian_business.point_ledger_transaction
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION dianlian_business.assert_balanced_point_ledger_transaction();

CREATE TABLE dianlian_business.task_run
(
    task_id                     UUID         PRIMARY KEY,
    tenant_id                   UUID         NOT NULL,
    task_version                BIGINT       NOT NULL,
    title                       VARCHAR(200) NOT NULL,
    goal                        TEXT         NOT NULL,
    status                      VARCHAR(32)  NOT NULL,
    current_plan_version        INTEGER      NOT NULL,
    collaboration_mode          VARCHAR(32)  NOT NULL,
    capability_code             VARCHAR(64)  NOT NULL,
    primary_agent_id            UUID,
    source_conversation_id      UUID,
    source_message_id           UUID,
    expected_membership_version VARCHAR(128),
    owner_user_id               UUID         NOT NULL,
    project_id                  UUID,
    billing_scope_type          VARCHAR(32)  NOT NULL,
    billing_scope_id            UUID         NOT NULL,
    max_point_cost              BIGINT       NOT NULL,
    point_reservation_id        UUID         NOT NULL,
    resume_event_id             UUID         NOT NULL,
    created_by                  UUID         NOT NULL,
    created_at                  TIMESTAMPTZ  NOT NULL,
    updated_at                  TIMESTAMPTZ  NOT NULL,
    UNIQUE (tenant_id, task_id),
    FOREIGN KEY (tenant_id, point_reservation_id)
        REFERENCES dianlian_business.point_reservation (tenant_id, reservation_id),
    CHECK (task_version > 0),
    CHECK (current_plan_version > 0),
    CHECK (char_length(goal) BETWEEN 1 AND 5000),
    CHECK (status IN ('DRAFT', 'PLANNING', 'WAITING_USER', 'QUEUED', 'RUNNING',
                      'APPLYING_GUIDANCE', 'REPLANNING', 'WAITING_CONFIRMATION',
                      'WAITING_APPROVAL', 'PAUSED', 'SUCCEEDED', 'PARTIAL_SUCCESS',
                      'FAILED', 'CANCELLED')),
    CHECK (collaboration_mode IN ('SINGLE_TARGET', 'PARALLEL_SEPARATE', 'PRIMARY_SUMMARY')),
    CHECK (max_point_cost > 0)
);

CREATE INDEX idx_task_run_owner_office
    ON dianlian_business.task_run (tenant_id, owner_user_id, updated_at DESC, task_id);

CREATE INDEX idx_task_run_status
    ON dianlian_business.task_run (tenant_id, status, updated_at DESC);

CREATE TABLE dianlian_business.execution_plan_version
(
    task_id                    UUID        NOT NULL,
    tenant_id                  UUID        NOT NULL,
    plan_version               INTEGER     NOT NULL,
    status                     VARCHAR(16) NOT NULL,
    execution_profile_snapshot JSONB       NOT NULL,
    created_by                 UUID        NOT NULL,
    created_at                 TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (task_id, plan_version),
    UNIQUE (tenant_id, task_id, plan_version),
    FOREIGN KEY (tenant_id, task_id)
        REFERENCES dianlian_business.task_run (tenant_id, task_id),
    CHECK (plan_version > 0),
    CHECK (status IN ('ACTIVE', 'SUPERSEDED')),
    CHECK (jsonb_typeof(execution_profile_snapshot) = 'object')
);

CREATE TABLE dianlian_business.task_step
(
    step_id             UUID         PRIMARY KEY,
    tenant_id           UUID         NOT NULL,
    task_id             UUID         NOT NULL,
    plan_version        INTEGER      NOT NULL,
    step_key            VARCHAR(100) NOT NULL,
    title               VARCHAR(200) NOT NULL,
    status              VARCHAR(48)  NOT NULL,
    responsible_type    VARCHAR(16)  NOT NULL,
    responsible_id      UUID         NOT NULL,
    depends_on          JSONB        NOT NULL,
    input_contract      VARCHAR(200) NOT NULL,
    output_contract     VARCHAR(200) NOT NULL,
    human_checkpoint    BOOLEAN      NOT NULL DEFAULT FALSE,
    step_order          INTEGER      NOT NULL,
    created_at          TIMESTAMPTZ  NOT NULL,
    updated_at          TIMESTAMPTZ  NOT NULL,
    UNIQUE (task_id, plan_version, step_key),
    FOREIGN KEY (tenant_id, task_id, plan_version)
        REFERENCES dianlian_business.execution_plan_version (tenant_id, task_id, plan_version),
    CHECK (status IN ('PENDING', 'READY', 'RUNNING', 'WAITING_EXTERNAL', 'RETRY_WAIT',
                      'SUCCEEDED', 'FAILED_FINAL', 'SKIPPED', 'CANCELLED',
                      'BLOCKED_SIDE_EFFECT_RECONCILIATION')),
    CHECK (responsible_type IN ('AGENT', 'USER', 'APPROVER', 'SYSTEM', 'EXTERNAL')),
    CHECK (jsonb_typeof(depends_on) = 'array'),
    CHECK (step_order > 0)
);

CREATE INDEX idx_task_step_current_plan
    ON dianlian_business.task_step (tenant_id, task_id, plan_version, step_order);

CREATE TABLE dianlian_business.task_participant
(
    task_id          UUID        NOT NULL,
    tenant_id        UUID        NOT NULL,
    user_id          UUID        NOT NULL,
    participant_role VARCHAR(16) NOT NULL,
    status           VARCHAR(16) NOT NULL,
    granted_by       UUID        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (task_id, user_id, participant_role),
    FOREIGN KEY (tenant_id, task_id)
        REFERENCES dianlian_business.task_run (tenant_id, task_id),
    CHECK (participant_role IN ('OWNER', 'COLLABORATOR', 'APPROVER', 'VIEWER')),
    CHECK (status IN ('ACTIVE', 'REVOKED'))
);

CREATE INDEX idx_task_participant_office
    ON dianlian_business.task_participant (tenant_id, user_id, status, task_id);

CREATE TABLE dianlian_business.task_target
(
    task_id                   UUID         NOT NULL,
    tenant_id                 UUID         NOT NULL,
    enterprise_agent_id       UUID         NOT NULL,
    agent_version_id          UUID         NOT NULL,
    target_role               VARCHAR(16)  NOT NULL,
    target_order              INTEGER      NOT NULL,
    capability_code           VARCHAR(64)  NOT NULL,
    execution_template_code   VARCHAR(128) NOT NULL,
    execution_template_version VARCHAR(64) NOT NULL,
    estimated_point_cost      BIGINT       NOT NULL,
    created_at                TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (task_id, enterprise_agent_id),
    FOREIGN KEY (tenant_id, task_id)
        REFERENCES dianlian_business.task_run (tenant_id, task_id),
    CHECK (target_role IN ('PRIMARY', 'SEPARATE', 'SUPPORT')),
    CHECK (target_order > 0),
    CHECK (estimated_point_cost >= 0)
);

CREATE TABLE dianlian_business.task_input_snapshot
(
    input_snapshot_id UUID        PRIMARY KEY,
    tenant_id         UUID        NOT NULL,
    task_id           UUID        NOT NULL,
    plan_version      INTEGER     NOT NULL,
    schema_id         VARCHAR(128),
    schema_version    VARCHAR(64),
    request_hash      VARCHAR(128) NOT NULL,
    input_payload     JSONB       NOT NULL,
    created_by        UUID        NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL,
    UNIQUE (task_id, plan_version),
    FOREIGN KEY (tenant_id, task_id, plan_version)
        REFERENCES dianlian_business.execution_plan_version (tenant_id, task_id, plan_version),
    CHECK (jsonb_typeof(input_payload) = 'object')
);

CREATE TABLE dianlian_business.task_business_trace
(
    trace_item_id    UUID          PRIMARY KEY,
    tenant_id        UUID          NOT NULL,
    task_id          UUID          NOT NULL,
    trace_type       VARCHAR(32)   NOT NULL,
    responsible_type VARCHAR(16),
    responsible_id   UUID,
    summary          VARCHAR(1000) NOT NULL,
    reference_ids    JSONB         NOT NULL,
    occurred_at      TIMESTAMPTZ   NOT NULL,
    FOREIGN KEY (tenant_id, task_id)
        REFERENCES dianlian_business.task_run (tenant_id, task_id),
    CHECK (trace_type IN ('GOAL_CONFIRMED', 'PLAN_CREATED', 'STEP_STARTED', 'STEP_COMPLETED',
                          'EVIDENCE_USED', 'TOOL_RESULT', 'CHECKPOINT_OPENED',
                          'CHECKPOINT_RESOLVED', 'ARTIFACT_CREATED', 'COST_UPDATED',
                          'CONTROL_APPLIED', 'FAILURE')),
    CHECK (responsible_type IS NULL OR responsible_type IN ('AGENT', 'USER', 'APPROVER', 'SYSTEM', 'EXTERNAL')),
    CHECK (jsonb_typeof(reference_ids) = 'array')
);

CREATE INDEX idx_task_business_trace_order
    ON dianlian_business.task_business_trace (task_id, occurred_at, trace_item_id);

ALTER TABLE dianlian_business.idempotency_record
    ADD COLUMN response_http_status INTEGER,
    ADD COLUMN response_payload JSONB,
    ADD COLUMN completed_at TIMESTAMPTZ;

ALTER TABLE dianlian_business.idempotency_record
    ADD CONSTRAINT chk_idempotency_response_complete
        CHECK ((response_payload IS NULL AND completed_at IS NULL)
            OR (response_payload IS NOT NULL AND completed_at IS NOT NULL));

-- Purpose: allow one new read-only admission-manifest permit after Run takeover.
-- Scope: ADMISSION_RESOLVE only; MODEL_INVOKE and TOOL_INVOKE remain globally single-consume.
-- Preconditions: migrations 000-018 are current and the routine owner is sealed.
-- Idempotency: the migration ledger applies this immutable file once by checksum.
-- Activation: no route, worker, model, tool, UI, or role flow is enabled by this migration.
-- Rollback: deploy the previous runtime first; schema rollback requires a reviewed later migration.

GRANT CREATE ON SCHEMA deer_runtime TO dianlian_supervisor_routine_owner;

LOCK TABLE deer_runtime.runtime_external_permit_attempt
    IN SHARE ROW EXCLUSIVE MODE;

-- 外部派发仍以逻辑意图全局单次消费；只读 Manifest 则按 lease epoch 单次消费，
-- 允许接管者在更高 epoch 重新读取同一不可变 Admission Snapshot。
DROP INDEX deer_runtime.uq_runtime_external_intent_consumed;
CREATE UNIQUE INDEX uq_runtime_external_dispatch_intent_consumed
    ON deer_runtime.runtime_external_permit_attempt
        (tenant_id, runtime_run_id, operation_kind, intent_id)
    WHERE status = 'CONSUMED'
      AND operation_kind IN ('MODEL_INVOKE', 'TOOL_INVOKE');
CREATE UNIQUE INDEX uq_runtime_admission_intent_consumed_per_epoch
    ON deer_runtime.runtime_external_permit_attempt
        (tenant_id, runtime_run_id, operation_kind, intent_id, lease_epoch)
    WHERE status = 'CONSUMED'
      AND operation_kind = 'ADMISSION_RESOLVE';

SET LOCAL ROLE dianlian_supervisor_routine_owner;

CREATE OR REPLACE FUNCTION deer_runtime.issue_runtime_external_permit(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_runtime_external_permit_id UUID,
    p_operation_kind VARCHAR,
    p_intent_id UUID,
    p_request_hash CHAR(64),
    p_requested_ttl_seconds INTEGER,
    p_issue_event_id UUID
)
RETURNS TABLE
(
    tenant_id UUID,
    runtime_external_permit_id UUID,
    runtime_run_id UUID,
    runtime_thread_id UUID,
    task_step_id UUID,
    task_execution_generation BIGINT,
    admission_contract_version VARCHAR(8),
    admission_snapshot_id UUID,
    admission_snapshot_hash CHAR(64),
    operation_kind VARCHAR(32),
    intent_id UUID,
    request_hash CHAR(64),
    lease_owner VARCHAR(160),
    lease_epoch BIGINT,
    permit_attempt INTEGER,
    status VARCHAR(16),
    requested_ttl_seconds INTEGER,
    issued_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    issue_event_id UUID,
    consume_event_id UUID,
    consumed_by VARCHAR(160),
    consumed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_expires_at TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_admission deer_runtime.runtime_execution_admission_ref%ROWTYPE;
    v_intent deer_runtime.runtime_external_intent%ROWTYPE;
    v_attempt deer_runtime.runtime_external_permit_attempt%ROWTYPE;
    v_next_attempt INTEGER;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_run_id IS NULL
       OR p_runtime_external_permit_id IS NULL OR p_intent_id IS NULL
       OR p_issue_event_id IS NULL
       OR p_tenant_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_run_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_external_permit_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_intent_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_issue_event_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_operation_kind IS NULL
       OR p_operation_kind NOT IN ('ADMISSION_RESOLVE', 'MODEL_INVOKE', 'TOOL_INVOKE')
       OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_requested_ttl_seconds IS NULL
       OR p_requested_ttl_seconds < 1 OR p_requested_ttl_seconds > 60 THEN
        RAISE EXCEPTION 'invalid runtime external permit issue arguments'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    v_now := CLOCK_TIMESTAMP();

    SELECT * INTO v_admission
      FROM deer_runtime.runtime_execution_admission_ref AS admission_ref
     WHERE admission_ref.tenant_id = p_tenant_id
       AND admission_ref.runtime_run_id = p_runtime_run_id
       AND admission_ref.admission_contract_version = '2.2';
    IF NOT FOUND THEN
        RETURN;
    END IF;

    SELECT * INTO v_intent
      FROM deer_runtime.runtime_external_intent AS external_intent
     WHERE external_intent.tenant_id = p_tenant_id
       AND external_intent.runtime_run_id = p_runtime_run_id
       AND external_intent.operation_kind = p_operation_kind
       AND external_intent.intent_id = p_intent_id;
    IF FOUND THEN
        IF v_intent.runtime_thread_id IS DISTINCT FROM v_run.runtime_thread_id
           OR v_intent.task_step_id IS DISTINCT FROM v_run.task_step_id
           OR v_intent.task_execution_generation IS DISTINCT FROM v_run.task_execution_generation
           OR v_intent.admission_contract_version IS DISTINCT FROM '2.2'
           OR v_intent.admission_snapshot_id IS DISTINCT FROM v_admission.admission_snapshot_id
           OR v_intent.admission_snapshot_hash IS DISTINCT FROM v_admission.admission_snapshot_hash
           OR v_intent.request_hash IS DISTINCT FROM p_request_hash THEN
            RAISE EXCEPTION 'runtime external intent identity conflict'
                USING ERRCODE = '23505';
        END IF;
    END IF;

    -- 精确 Permit ID 永远先走原事实重放，包括同 epoch 已消费的 Manifest。
    SELECT * INTO v_attempt
      FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
     WHERE permit_attempt.runtime_external_permit_id = p_runtime_external_permit_id
     FOR UPDATE;
    IF FOUND THEN
        IF v_attempt.tenant_id IS DISTINCT FROM p_tenant_id
           OR v_attempt.runtime_run_id IS DISTINCT FROM p_runtime_run_id
           OR v_attempt.operation_kind IS DISTINCT FROM p_operation_kind
           OR v_attempt.intent_id IS DISTINCT FROM p_intent_id
           OR v_attempt.lease_owner IS DISTINCT FROM p_lease_owner
           OR v_attempt.lease_epoch IS DISTINCT FROM p_lease_epoch
           OR v_attempt.requested_ttl_seconds IS DISTINCT FROM p_requested_ttl_seconds
           OR v_attempt.issue_event_id IS DISTINCT FROM p_issue_event_id THEN
            RAISE EXCEPTION 'runtime external permit issue idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY
        SELECT external_intent.tenant_id,
               permit_attempt.runtime_external_permit_id,
               external_intent.runtime_run_id,
               external_intent.runtime_thread_id,
               external_intent.task_step_id,
               external_intent.task_execution_generation,
               external_intent.admission_contract_version,
               external_intent.admission_snapshot_id,
               external_intent.admission_snapshot_hash,
               external_intent.operation_kind,
               external_intent.intent_id,
               external_intent.request_hash,
               permit_attempt.lease_owner,
               permit_attempt.lease_epoch,
               permit_attempt.permit_attempt,
               permit_attempt.status,
               permit_attempt.requested_ttl_seconds,
               permit_attempt.issued_at,
               permit_attempt.expires_at,
               permit_attempt.issue_event_id,
               permit_attempt.consume_event_id,
               permit_attempt.consumed_by,
               permit_attempt.consumed_at,
               permit_attempt.updated_at
          FROM deer_runtime.runtime_external_intent AS external_intent
          JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
            ON permit_attempt.tenant_id = external_intent.tenant_id
           AND permit_attempt.runtime_run_id = external_intent.runtime_run_id
           AND permit_attempt.operation_kind = external_intent.operation_kind
           AND permit_attempt.intent_id = external_intent.intent_id
         WHERE permit_attempt.tenant_id = v_attempt.tenant_id
           AND permit_attempt.runtime_external_permit_id = v_attempt.runtime_external_permit_id;
        RETURN;
    END IF;

    -- 总是锁定最新已消费 attempt。模型/工具返回原事实；Admission 只有在更高
    -- lease epoch 才继续签发新的只读 attempt。
    SELECT * INTO v_attempt
      FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
     WHERE permit_attempt.tenant_id = p_tenant_id
       AND permit_attempt.runtime_run_id = p_runtime_run_id
       AND permit_attempt.operation_kind = p_operation_kind
       AND permit_attempt.intent_id = p_intent_id
       AND permit_attempt.status = 'CONSUMED'
     ORDER BY permit_attempt.permit_attempt DESC
     LIMIT 1
     FOR UPDATE;
    IF FOUND THEN
        IF v_run.status <> 'RUNNING'
           OR v_run.lease_owner IS DISTINCT FROM p_lease_owner
           OR v_run.lease_epoch IS DISTINCT FROM p_lease_epoch
           OR v_run.lease_until IS NULL OR v_run.lease_until <= v_now THEN
            RETURN;
        END IF;
        IF p_operation_kind <> 'ADMISSION_RESOLVE'
           OR p_lease_epoch <= v_attempt.lease_epoch THEN
            RETURN QUERY
            SELECT external_intent.tenant_id,
                   permit_attempt.runtime_external_permit_id,
                   external_intent.runtime_run_id,
                   external_intent.runtime_thread_id,
                   external_intent.task_step_id,
                   external_intent.task_execution_generation,
                   external_intent.admission_contract_version,
                   external_intent.admission_snapshot_id,
                   external_intent.admission_snapshot_hash,
                   external_intent.operation_kind,
                   external_intent.intent_id,
                   external_intent.request_hash,
                   permit_attempt.lease_owner,
                   permit_attempt.lease_epoch,
                   permit_attempt.permit_attempt,
                   permit_attempt.status,
                   permit_attempt.requested_ttl_seconds,
                   permit_attempt.issued_at,
                   permit_attempt.expires_at,
                   permit_attempt.issue_event_id,
                   permit_attempt.consume_event_id,
                   permit_attempt.consumed_by,
                   permit_attempt.consumed_at,
                   permit_attempt.updated_at
              FROM deer_runtime.runtime_external_intent AS external_intent
              JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
                ON permit_attempt.tenant_id = external_intent.tenant_id
               AND permit_attempt.runtime_run_id = external_intent.runtime_run_id
               AND permit_attempt.operation_kind = external_intent.operation_kind
               AND permit_attempt.intent_id = external_intent.intent_id
             WHERE permit_attempt.tenant_id = v_attempt.tenant_id
               AND permit_attempt.runtime_external_permit_id =
                   v_attempt.runtime_external_permit_id;
            RETURN;
        END IF;
    END IF;

    IF v_run.status <> 'RUNNING'
       OR v_run.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_run.lease_epoch IS DISTINCT FROM p_lease_epoch
       OR v_run.lease_until IS NULL OR v_run.lease_until <= v_now THEN
        RETURN;
    END IF;

    v_expires_at := v_now + MAKE_INTERVAL(secs => p_requested_ttl_seconds);
    IF v_expires_at > v_run.lease_until THEN
        RETURN;
    END IF;

    IF v_intent.tenant_id IS NULL THEN
        INSERT INTO deer_runtime.runtime_external_intent (
            tenant_id, runtime_run_id, operation_kind, intent_id,
            runtime_thread_id, task_step_id, task_execution_generation,
            admission_contract_version, admission_snapshot_id,
            admission_snapshot_hash, request_hash, created_at
        ) VALUES (
            p_tenant_id, p_runtime_run_id, p_operation_kind, p_intent_id,
            v_run.runtime_thread_id, v_run.task_step_id, v_run.task_execution_generation,
            '2.2', v_admission.admission_snapshot_id,
            v_admission.admission_snapshot_hash, p_request_hash, v_now
        ) RETURNING * INTO v_intent;
    END IF;

    SELECT * INTO v_attempt
      FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
     WHERE permit_attempt.tenant_id = p_tenant_id
       AND permit_attempt.runtime_run_id = p_runtime_run_id
       AND permit_attempt.operation_kind = p_operation_kind
       AND permit_attempt.intent_id = p_intent_id
       AND permit_attempt.lease_epoch = p_lease_epoch
       AND permit_attempt.status = 'ISSUED'
       AND permit_attempt.expires_at > v_now
     ORDER BY permit_attempt.permit_attempt DESC
     LIMIT 1
     FOR UPDATE;
    IF FOUND THEN
        RAISE EXCEPTION 'live runtime external permit already exists for this lease epoch'
            USING ERRCODE = '23505';
    END IF;

    SELECT COALESCE(MAX(permit_attempt.permit_attempt), 0) + 1
      INTO v_next_attempt
      FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
     WHERE permit_attempt.tenant_id = p_tenant_id
       AND permit_attempt.runtime_run_id = p_runtime_run_id
       AND permit_attempt.operation_kind = p_operation_kind
       AND permit_attempt.intent_id = p_intent_id;

    INSERT INTO deer_runtime.runtime_external_permit_attempt (
        tenant_id, runtime_external_permit_id, runtime_run_id, operation_kind,
        intent_id, lease_owner, lease_epoch, permit_attempt, status,
        requested_ttl_seconds, issued_at, expires_at, issue_event_id,
        consume_event_id, consumed_by, consumed_at, updated_at
    ) VALUES (
        p_tenant_id, p_runtime_external_permit_id, p_runtime_run_id, p_operation_kind,
        p_intent_id, p_lease_owner, p_lease_epoch, v_next_attempt, 'ISSUED',
        p_requested_ttl_seconds, v_now, v_expires_at, p_issue_event_id,
        NULL, NULL, NULL, v_now
    ) RETURNING * INTO v_attempt;

    INSERT INTO deer_runtime.runtime_external_permit_event (
        tenant_id, runtime_external_permit_id, event_id, runtime_run_id,
        operation_kind, intent_id, permit_attempt, event_type,
        lease_owner, lease_epoch, occurred_at, created_at
    ) VALUES (
        p_tenant_id, p_runtime_external_permit_id, p_issue_event_id, p_runtime_run_id,
        p_operation_kind, p_intent_id, v_next_attempt, 'ISSUED',
        p_lease_owner, p_lease_epoch, v_now, v_now
    );

    RETURN QUERY
    SELECT external_intent.tenant_id,
           permit_attempt.runtime_external_permit_id,
           external_intent.runtime_run_id,
           external_intent.runtime_thread_id,
           external_intent.task_step_id,
           external_intent.task_execution_generation,
           external_intent.admission_contract_version,
           external_intent.admission_snapshot_id,
           external_intent.admission_snapshot_hash,
           external_intent.operation_kind,
           external_intent.intent_id,
           external_intent.request_hash,
           permit_attempt.lease_owner,
           permit_attempt.lease_epoch,
           permit_attempt.permit_attempt,
           permit_attempt.status,
           permit_attempt.requested_ttl_seconds,
           permit_attempt.issued_at,
           permit_attempt.expires_at,
           permit_attempt.issue_event_id,
           permit_attempt.consume_event_id,
           permit_attempt.consumed_by,
           permit_attempt.consumed_at,
           permit_attempt.updated_at
      FROM deer_runtime.runtime_external_intent AS external_intent
      JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
        ON permit_attempt.tenant_id = external_intent.tenant_id
       AND permit_attempt.runtime_run_id = external_intent.runtime_run_id
       AND permit_attempt.operation_kind = external_intent.operation_kind
       AND permit_attempt.intent_id = external_intent.intent_id
     WHERE permit_attempt.tenant_id = v_attempt.tenant_id
       AND permit_attempt.runtime_external_permit_id = v_attempt.runtime_external_permit_id;
END;
$function$;

RESET ROLE;
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner;

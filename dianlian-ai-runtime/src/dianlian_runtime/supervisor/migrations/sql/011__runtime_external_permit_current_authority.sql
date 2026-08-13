-- Purpose: combine permit consumption with the current live Supervisor Run authority.
-- Scope: PostgreSQL 15+; only one dormant authorizer routine and its ACL are changed.
-- Preconditions: migrations 000-010 are current and all named cluster roles already exist.
-- Idempotency: the migration ledger applies this immutable file once by checksum.
-- Activation: no worker, HTTP endpoint, Java adapter, or external dispatch is enabled here.
-- Rollback: deploy the previous runtime first; removal requires a reviewed later migration.

GRANT CREATE ON SCHEMA deer_runtime TO dianlian_supervisor_routine_owner;
SET LOCAL ROLE dianlian_supervisor_routine_owner;

CREATE FUNCTION deer_runtime.consume_and_authorize_runtime_external_permit(
    p_tenant_id UUID,
    p_runtime_external_permit_id UUID,
    p_runtime_run_id UUID,
    p_task_execution_generation BIGINT,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_admission_snapshot_id UUID,
    p_admission_snapshot_hash CHAR(64),
    p_operation_kind VARCHAR,
    p_intent_id UUID,
    p_request_hash CHAR(64),
    p_consume_event_id UUID,
    p_consumed_by VARCHAR
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
    v_run deer_runtime.runtime_run%ROWTYPE;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_external_permit_id IS NULL
       OR p_runtime_run_id IS NULL OR p_admission_snapshot_id IS NULL
       OR p_intent_id IS NULL OR p_consume_event_id IS NULL
       OR p_tenant_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_external_permit_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_run_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_admission_snapshot_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_intent_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_consume_event_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_task_execution_generation IS NULL OR p_task_execution_generation < 1
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_admission_snapshot_hash IS NULL
       OR p_admission_snapshot_hash !~ '^[0-9a-f]{64}$'
       OR p_operation_kind IS NULL
       OR p_operation_kind NOT IN ('ADMISSION_RESOLVE', 'MODEL_INVOKE', 'TOOL_INVOKE')
       OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_consumed_by IS NULL OR BTRIM(p_consumed_by) = ''
       OR LENGTH(p_consumed_by) > 160 THEN
        RAISE EXCEPTION 'invalid runtime external permit consume and authorize arguments'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run AS runtime_run
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    v_now := CLOCK_TIMESTAMP();

    IF v_run.status <> 'RUNNING'
       OR v_run.task_execution_generation IS DISTINCT FROM p_task_execution_generation
       OR v_run.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_run.lease_epoch IS DISTINCT FROM p_lease_epoch
       OR v_run.lease_until IS NULL OR v_run.lease_until <= v_now THEN
        RETURN;
    END IF;

    RETURN QUERY
    SELECT consumed.*
      FROM deer_runtime.consume_runtime_external_permit(
          p_tenant_id,
          p_runtime_external_permit_id,
          p_runtime_run_id,
          p_task_execution_generation,
          p_lease_owner,
          p_lease_epoch,
          p_admission_snapshot_id,
          p_admission_snapshot_hash,
          p_operation_kind,
          p_intent_id,
          p_request_hash,
          p_consume_event_id,
          p_consumed_by
      ) AS consumed;
END;
$function$;

REVOKE ALL PRIVILEGES ON FUNCTION deer_runtime.consume_runtime_external_permit(
    UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
    VARCHAR, UUID, CHAR(64), UUID, VARCHAR
) FROM PUBLIC, dianlian_supervisor_executor, dianlian_supervisor_permit_authorizer;
REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.consume_and_authorize_runtime_external_permit(
        UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
        VARCHAR, UUID, CHAR(64), UUID, VARCHAR
    ) FROM PUBLIC, dianlian_supervisor_executor, dianlian_supervisor_permit_authorizer;

GRANT EXECUTE ON FUNCTION
    deer_runtime.consume_and_authorize_runtime_external_permit(
        UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
        VARCHAR, UUID, CHAR(64), UUID, VARCHAR
    ) TO dianlian_supervisor_permit_authorizer;

RESET ROLE;
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner;

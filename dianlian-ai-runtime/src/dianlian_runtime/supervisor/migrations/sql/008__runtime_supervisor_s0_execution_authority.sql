-- Purpose: expose narrowly scoped execution and cancellation authority facts.
-- Scope: PostgreSQL 15+; only read-only deer_runtime Supervisor routines are added.
-- Preconditions: apply after 007 with the pre-created owner and executor roles.
-- Idempotency: the migration ledger applies this immutable file once by checksum.
-- Activation: no service, application lifecycle, RunStore, or worker invokes these functions.
-- Rollback: deploy the previous runtime first; removal requires a reviewed later migration.

CREATE FUNCTION deer_runtime.authorize_runtime_run_cancellation(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT
)
RETURNS TABLE
(
    tenant_id UUID,
    runtime_run_id UUID,
    runtime_thread_id UUID,
    task_step_id UUID,
    task_execution_generation BIGINT,
    status VARCHAR(32),
    lease_owner VARCHAR(160),
    lease_epoch BIGINT,
    run_version BIGINT,
    cancel_requested_at TIMESTAMPTZ
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
BEGIN
    IF p_tenant_id IS NULL
       OR p_runtime_run_id IS NULL
       OR p_lease_owner IS NULL
       OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL
       OR p_lease_epoch < 1 THEN
        RAISE EXCEPTION 'invalid runtime cancellation authorization arguments'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT runtime_run.tenant_id,
           runtime_run.runtime_run_id,
           runtime_run.runtime_thread_id,
           runtime_run.task_step_id,
           runtime_run.task_execution_generation,
           runtime_run.status,
           runtime_run.lease_owner,
           runtime_run.lease_epoch,
           runtime_run.run_version,
           runtime_run.cancel_requested_at
      FROM deer_runtime.runtime_run AS runtime_run
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
       AND runtime_run.status = 'CANCELLING'
       AND runtime_run.lease_owner = p_lease_owner
       AND runtime_run.lease_epoch = p_lease_epoch
       AND runtime_run.lease_until > CLOCK_TIMESTAMP();
END;
$function$;

CREATE FUNCTION deer_runtime.load_runtime_execution_authority(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT
)
RETURNS TABLE
(
    tenant_id UUID,
    runtime_run_id UUID,
    runtime_thread_id UUID,
    task_run_id UUID,
    task_step_id UUID,
    task_execution_generation BIGINT,
    agent_instance_id UUID,
    user_id UUID,
    conversation_id UUID,
    source_message_id UUID,
    runtime_thread_revision BIGINT,
    runtime_type VARCHAR(32),
    runtime_agent_name VARCHAR(128),
    capability_version_id UUID,
    prompt_version_id UUID,
    model_policy_id UUID,
    budget_reservation_id UUID,
    operation_kind VARCHAR(16),
    multitask_strategy VARCHAR(16),
    request_hash CHAR(64),
    idempotency_key VARCHAR(200),
    predecessor_runtime_run_id UUID,
    expected_checkpoint_id VARCHAR(160),
    runtime_version VARCHAR(128),
    agent_name VARCHAR(128),
    lease_owner VARCHAR(160),
    lease_epoch BIGINT
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
BEGIN
    IF p_tenant_id IS NULL
       OR p_runtime_run_id IS NULL
       OR p_lease_owner IS NULL
       OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL
       OR p_lease_epoch < 1 THEN
        RAISE EXCEPTION 'invalid runtime execution authority arguments'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT runtime_run.tenant_id,
           runtime_run.runtime_run_id,
           runtime_run.runtime_thread_id,
           runtime_thread.task_run_id,
           runtime_run.task_step_id,
           runtime_run.task_execution_generation,
           runtime_thread.agent_instance_id,
           runtime_thread.user_id,
           runtime_thread.conversation_id,
           runtime_thread.source_message_id,
           runtime_thread.runtime_thread_revision,
           runtime_thread.runtime_type,
           runtime_thread.runtime_agent_name,
           runtime_thread.capability_version_id,
           runtime_thread.prompt_version_id,
           runtime_thread.model_policy_id,
           runtime_thread.budget_reservation_id,
           runtime_run.operation_kind,
           runtime_run.multitask_strategy,
           runtime_run.request_hash,
           runtime_run.idempotency_key,
           runtime_run.predecessor_runtime_run_id,
           runtime_run.expected_checkpoint_id,
           runtime_run.runtime_version,
           runtime_run.agent_name,
           runtime_run.lease_owner,
           runtime_run.lease_epoch
      FROM deer_runtime.runtime_run AS runtime_run
      JOIN deer_runtime.runtime_thread AS runtime_thread
        ON runtime_thread.tenant_id = runtime_run.tenant_id
       AND runtime_thread.runtime_thread_id = runtime_run.runtime_thread_id
       AND runtime_thread.task_step_id = runtime_run.task_step_id
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
       AND runtime_run.status = 'RUNNING'
       AND runtime_run.lease_owner = p_lease_owner
       AND runtime_run.lease_epoch = p_lease_epoch
       AND runtime_run.lease_until > CLOCK_TIMESTAMP();
END;
$function$;

REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.authorize_runtime_run_cancellation(UUID, UUID, VARCHAR, BIGINT)
    FROM PUBLIC;
REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.load_runtime_execution_authority(UUID, UUID, VARCHAR, BIGINT)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    deer_runtime.authorize_runtime_run_cancellation(UUID, UUID, VARCHAR, BIGINT)
    TO dianlian_supervisor_executor;
GRANT EXECUTE ON FUNCTION
    deer_runtime.load_runtime_execution_authority(UUID, UUID, VARCHAR, BIGINT)
    TO dianlian_supervisor_executor;

-- PostgreSQL requires the target owner to have CREATE while ownership transfers.
GRANT CREATE ON SCHEMA deer_runtime TO dianlian_supervisor_routine_owner;
ALTER FUNCTION deer_runtime.authorize_runtime_run_cancellation(UUID, UUID, VARCHAR, BIGINT)
    OWNER TO dianlian_supervisor_routine_owner;
ALTER FUNCTION deer_runtime.load_runtime_execution_authority(UUID, UUID, VARCHAR, BIGINT)
    OWNER TO dianlian_supervisor_routine_owner;
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner;

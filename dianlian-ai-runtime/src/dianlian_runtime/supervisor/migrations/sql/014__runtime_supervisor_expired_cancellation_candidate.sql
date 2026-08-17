-- Purpose: make expired cancellation work recoverable by the existing takeover path.
-- Scope: read-only candidate discovery for CANCEL_REQUESTED and CANCELLING Runs.
-- Preconditions: migration 013 is current; takeover already accepts cancellation states.
-- Idempotency: the migration ledger applies this immutable file once by checksum.
-- Activation: the governed worker may resume only the durable cancellation workflow.
-- Rollback: deploy the previous worker first; remove the index in a reviewed migration.

CREATE INDEX idx_runtime_run_expired_cancellation_candidate
    ON deer_runtime.runtime_run (
        runtime_version,
        agent_name,
        lease_until,
        created_at,
        tenant_id,
        runtime_run_id
    )
    WHERE status IN ('CANCEL_REQUESTED', 'CANCELLING')
      AND lease_owner IS NOT NULL
      AND lease_until IS NOT NULL;

GRANT CREATE ON SCHEMA deer_runtime TO dianlian_supervisor_routine_owner;
SET LOCAL ROLE dianlian_supervisor_routine_owner;

CREATE OR REPLACE FUNCTION deer_runtime.select_next_runtime_run_candidate(
    p_runtime_version VARCHAR,
    p_agent_name VARCHAR,
    p_admission_contract_version VARCHAR
)
RETURNS TABLE
(
    tenant_id UUID,
    runtime_run_id UUID
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
BEGIN
    IF p_runtime_version IS NULL
       OR BTRIM(p_runtime_version) = ''
       OR LENGTH(p_runtime_version) > 128
       OR p_agent_name IS NULL
       OR BTRIM(p_agent_name) = ''
       OR LENGTH(p_agent_name) > 128
       OR p_admission_contract_version IS DISTINCT FROM '2.2' THEN
        RAISE EXCEPTION 'runtime_version, agent_name and admission contract 2.2 are required'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT runtime_run.tenant_id,
           runtime_run.runtime_run_id
      FROM deer_runtime.runtime_run AS runtime_run
      JOIN deer_runtime.runtime_execution_admission_ref AS admission_ref
        ON admission_ref.tenant_id = runtime_run.tenant_id
       AND admission_ref.runtime_run_id = runtime_run.runtime_run_id
       AND admission_ref.admission_contract_version = p_admission_contract_version
     WHERE runtime_run.runtime_version = p_runtime_version
       AND runtime_run.agent_name = p_agent_name
       AND (
            runtime_run.status = 'QUEUED'
            OR (
                runtime_run.status IN (
                    'RUNNING', 'CANCEL_REQUESTED', 'CANCELLING'
                )
                AND runtime_run.lease_owner IS NOT NULL
                AND runtime_run.lease_until IS NOT NULL
                AND runtime_run.lease_until <= STATEMENT_TIMESTAMP()
            )
       )
     ORDER BY CASE
                  WHEN runtime_run.status IN (
                      'CANCEL_REQUESTED', 'CANCELLING'
                  ) THEN 0
                  WHEN runtime_run.status = 'RUNNING' THEN 1
                  ELSE 2
              END,
              CASE
                  WHEN runtime_run.status <> 'QUEUED' THEN runtime_run.lease_until
                  ELSE runtime_run.created_at
              END,
              runtime_run.created_at,
              runtime_run.tenant_id,
              runtime_run.runtime_run_id
     LIMIT 1;
END;
$function$;

RESET ROLE;
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner;

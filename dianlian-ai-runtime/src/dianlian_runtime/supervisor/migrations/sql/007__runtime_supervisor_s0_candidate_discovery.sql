-- Purpose: discover one compatible queued Run without granting execution ownership.
-- Scope: PostgreSQL 15+; only the dormant deer_runtime Supervisor boundary is affected.
-- Preconditions: apply after 006 with the pre-created owner and executor roles.
-- Idempotency: the migration ledger applies this immutable file once by checksum.
-- Activation: no service, application lifecycle, RunStore, or worker invokes this function.
-- Rollback: deploy the previous runtime first; removal requires a reviewed later migration.

CREATE INDEX idx_runtime_run_queued_candidate
    ON deer_runtime.runtime_run (
        runtime_version,
        agent_name,
        created_at,
        tenant_id,
        runtime_run_id
    )
    WHERE status = 'QUEUED';

CREATE FUNCTION deer_runtime.select_next_runtime_run_candidate(
    p_runtime_version VARCHAR,
    p_agent_name VARCHAR
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
       OR LENGTH(p_agent_name) > 128 THEN
        RAISE EXCEPTION 'runtime_version and agent_name are required and limited to 128 characters'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT runtime_run.tenant_id,
           runtime_run.runtime_run_id
      FROM deer_runtime.runtime_run AS runtime_run
     WHERE runtime_run.status = 'QUEUED'
       AND runtime_run.runtime_version = p_runtime_version
       AND runtime_run.agent_name = p_agent_name
     ORDER BY runtime_run.created_at,
              runtime_run.tenant_id,
              runtime_run.runtime_run_id
     LIMIT 1;
END;
$function$;

REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.select_next_runtime_run_candidate(VARCHAR, VARCHAR)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    deer_runtime.select_next_runtime_run_candidate(VARCHAR, VARCHAR)
    TO dianlian_supervisor_executor;

-- PostgreSQL requires the target owner to have CREATE while ownership transfers.
GRANT CREATE ON SCHEMA deer_runtime TO dianlian_supervisor_routine_owner;
ALTER FUNCTION deer_runtime.select_next_runtime_run_candidate(VARCHAR, VARCHAR)
    OWNER TO dianlian_supervisor_routine_owner;
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner;

-- Purpose: expose one atomic, side-effect-free Run projection to a sealed observer capability.
-- Scope: only the deer_runtime Run snapshot and ordered event page are observable.
-- Preconditions: migrations 000-017 are current and the sealed run-observer role exists.
-- Idempotency: the migration ledger applies this immutable file once by checksum.
-- Activation: no HTTP route, Java projection worker, task mapping, UI, or role flow is enabled.
-- Rollback: deploy the previous runtime first; remove the observer grant in a reviewed migration.

DO $precondition$
DECLARE
    v_migrator pg_catalog.pg_roles%ROWTYPE;
    v_observer pg_catalog.pg_roles%ROWTYPE;
BEGIN
    SELECT * INTO v_migrator
      FROM pg_catalog.pg_roles
     WHERE rolname = CURRENT_USER;
    IF NOT FOUND
       OR NOT v_migrator.rolcanlogin
       OR v_migrator.rolinherit
       OR v_migrator.rolsuper
       OR v_migrator.rolcreatedb
       OR v_migrator.rolcreaterole
       OR v_migrator.rolreplication
       OR v_migrator.rolbypassrls THEN
        RAISE EXCEPTION 'Supervisor migrator must be a restricted NOINHERIT login'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_observer
      FROM pg_catalog.pg_roles
     WHERE rolname = 'dianlian_supervisor_run_observer';
    IF NOT FOUND
       OR v_observer.rolcanlogin
       OR v_observer.rolinherit
       OR v_observer.rolsuper
       OR v_observer.rolcreatedb
       OR v_observer.rolcreaterole
       OR v_observer.rolreplication
       OR v_observer.rolbypassrls
       OR EXISTS (
           SELECT 1
             FROM pg_catalog.pg_auth_members
            WHERE member = v_observer.oid
       ) THEN
        RAISE EXCEPTION 'dianlian_supervisor_run_observer must be a sealed NOLOGIN NOINHERIT role'
            USING ERRCODE = '42501';
    END IF;

    IF NOT pg_catalog.pg_has_role(
        CURRENT_USER,
        'dianlian_supervisor_routine_owner',
        'MEMBER'
    ) OR (
        SELECT COUNT(*)
          FROM pg_catalog.pg_auth_members
         WHERE member = v_migrator.oid
    ) <> 1 THEN
        RAISE EXCEPTION 'Supervisor migrator may only inherit the routine-owner role'
            USING ERRCODE = '42501';
    END IF;
END;
$precondition$;

GRANT CREATE ON SCHEMA deer_runtime TO dianlian_supervisor_routine_owner;
SET LOCAL ROLE dianlian_supervisor_routine_owner;

CREATE FUNCTION deer_runtime.read_runtime_run_projection(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_task_step_id UUID,
    p_task_execution_generation BIGINT,
    p_request_hash CHAR(64),
    p_after_sequence BIGINT,
    p_page_size INTEGER
)
RETURNS TABLE (
    tenant_id UUID,
    runtime_run_id UUID,
    runtime_thread_id UUID,
    task_step_id UUID,
    task_execution_generation BIGINT,
    status VARCHAR,
    operation_kind VARCHAR,
    request_hash CHAR(64),
    current_checkpoint_id VARCHAR,
    current_checkpoint_sequence_no BIGINT,
    next_event_sequence_no BIGINT,
    event_retention_floor_sequence BIGINT,
    run_version BIGINT,
    terminal_reason VARCHAR,
    terminal_event_id UUID,
    lease_epoch BIGINT,
    attempt INTEGER,
    runtime_version VARCHAR,
    agent_name VARCHAR,
    failure_code VARCHAR,
    cancel_requested_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    terminal_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    after_sequence BIGINT,
    next_sequence BIGINT,
    has_more BOOLEAN,
    replay_gap BOOLEAN,
    events JSONB
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $function$
DECLARE
    v_nil_uuid CONSTANT UUID := '00000000-0000-0000-0000-000000000000';
BEGIN
    IF p_tenant_id IS NULL OR p_tenant_id = v_nil_uuid
       OR p_runtime_run_id IS NULL OR p_runtime_run_id = v_nil_uuid
       OR p_task_step_id IS NULL OR p_task_step_id = v_nil_uuid
       OR p_task_execution_generation IS NULL OR p_task_execution_generation < 1
       OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_after_sequence IS NULL OR p_after_sequence < 0
       OR p_page_size IS NULL OR p_page_size < 1 OR p_page_size > 100 THEN
        RAISE EXCEPTION 'runtime Run projection query is invalid'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT run.tenant_id,
           run.runtime_run_id,
           run.runtime_thread_id,
           run.task_step_id,
           run.task_execution_generation,
           run.status,
           run.operation_kind,
           run.request_hash,
           run.current_checkpoint_id,
           run.current_checkpoint_sequence_no,
           run.next_event_sequence_no,
           run.event_retention_floor_sequence,
           run.run_version,
           run.terminal_reason,
           run.terminal_event_id,
           run.lease_epoch,
           run.attempt,
           run.runtime_version,
           run.agent_name,
           run.failure_code,
           run.cancel_requested_at,
           run.started_at,
           run.terminal_at,
           run.created_at,
           run.updated_at,
           p_after_sequence,
           CASE
               WHEN p_after_sequence < run.event_retention_floor_sequence - 1
                   THEN p_after_sequence
               ELSE COALESCE(page.last_sequence, p_after_sequence)
           END,
           CASE
               WHEN p_after_sequence < run.event_retention_floor_sequence - 1
                   THEN FALSE
               ELSE run.next_event_sequence_no - 1
                    > COALESCE(page.last_sequence, p_after_sequence)
           END,
           p_after_sequence < run.event_retention_floor_sequence - 1,
           CASE
               WHEN p_after_sequence < run.event_retention_floor_sequence - 1
                   THEN '[]'::JSONB
               ELSE COALESCE(page.events, '[]'::JSONB)
           END
      FROM deer_runtime.runtime_run AS run
      LEFT JOIN LATERAL (
          SELECT pg_catalog.MAX(event_page.sequence_no) AS last_sequence,
                 pg_catalog.JSONB_AGG(
                     pg_catalog.JSONB_BUILD_OBJECT(
                         'eventId', event_page.event_id,
                         'sequenceNo', event_page.sequence_no,
                         'eventType', event_page.event_type,
                         'eventVersion', event_page.event_version,
                         'runVersion', event_page.run_version,
                         'leaseOwner', event_page.lease_owner,
                         'leaseEpoch', event_page.lease_epoch,
                         'checkpointId', event_page.checkpoint_id,
                         'payload', event_page.payload,
                         'occurredAt', event_page.occurred_at,
                         'createdAt', event_page.created_at
                     ) ORDER BY event_page.sequence_no
                 ) AS events
            FROM (
                SELECT event.event_id,
                       event.sequence_no,
                       event.event_type,
                       event.event_version,
                       event.run_version,
                       event.lease_owner,
                       event.lease_epoch,
                       event.checkpoint_id,
                       event.payload,
                       event.occurred_at,
                       event.created_at
                  FROM deer_runtime.runtime_run_event AS event
                 WHERE event.tenant_id = run.tenant_id
                   AND event.runtime_run_id = run.runtime_run_id
                   AND event.runtime_thread_id = run.runtime_thread_id
                   AND event.sequence_no > p_after_sequence
                 ORDER BY event.sequence_no
                 LIMIT p_page_size
            ) AS event_page
      ) AS page ON p_after_sequence >= run.event_retention_floor_sequence - 1
     WHERE run.tenant_id = p_tenant_id
       AND run.runtime_run_id = p_runtime_run_id
       AND run.task_step_id = p_task_step_id
       AND run.task_execution_generation = p_task_execution_generation
       AND run.request_hash = p_request_hash;
END;
$function$;

REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA deer_runtime
    FROM dianlian_supervisor_run_observer;
REVOKE ALL PRIVILEGES ON FUNCTION deer_runtime.read_runtime_run_projection(
    UUID, UUID, UUID, BIGINT, CHAR(64), BIGINT, INTEGER
) FROM PUBLIC,
       dianlian_supervisor_executor,
       dianlian_supervisor_permit_authorizer,
       dianlian_supervisor_dispatch_authorizer,
       dianlian_supervisor_outcome_reconciler,
       dianlian_supervisor_controller,
       dianlian_supervisor_run_admitter;
GRANT EXECUTE ON FUNCTION deer_runtime.read_runtime_run_projection(
    UUID, UUID, UUID, BIGINT, CHAR(64), BIGINT, INTEGER
) TO dianlian_supervisor_run_observer;

RESET ROLE;
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner;

REVOKE ALL PRIVILEGES ON SCHEMA deer_runtime
    FROM dianlian_supervisor_run_observer;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_run_observer;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_run_observer;

DO $revoke_run_observer_column_privileges$
DECLARE
    v_column RECORD;
BEGIN
    FOR v_column IN
        SELECT namespace.nspname, relation.relname, attribute.attname
          FROM pg_catalog.pg_attribute AS attribute
          JOIN pg_catalog.pg_class AS relation
            ON relation.oid = attribute.attrelid
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
         WHERE namespace.nspname = 'deer_runtime'
           AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
           AND attribute.attnum > 0
           AND NOT attribute.attisdropped
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL PRIVILEGES (%I) ON TABLE %I.%I FROM dianlian_supervisor_run_observer',
            v_column.attname,
            v_column.nspname,
            v_column.relname
        );
    END LOOP;
END;
$revoke_run_observer_column_privileges$;

GRANT USAGE ON SCHEMA deer_runtime TO dianlian_supervisor_run_observer;
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_run_observer;

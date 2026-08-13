-- Purpose: add atomic START/REJECT admission for the dormant S0 Run Supervisor.
-- Scope: PostgreSQL 15+; only deer_runtime Thread, Run and accepted-event facts.
-- Preconditions: migrations 000-004 are current; authentication is completed by the caller.
-- Idempotency: the Thread and Run command identities plus RUN_ACCEPTED fact replay exactly.
-- Activation: no application component invokes this function in this migration.
-- Rollback: deploy the previous runtime first; remove the function in a reviewed later migration.

CREATE FUNCTION deer_runtime.admit_runtime_run(
    p_tenant_id UUID,
    p_runtime_thread_id UUID,
    p_task_run_id UUID,
    p_task_step_id UUID,
    p_agent_instance_id UUID,
    p_user_id UUID,
    p_conversation_id UUID,
    p_source_message_id UUID,
    p_runtime_thread_revision BIGINT,
    p_runtime_type VARCHAR,
    p_runtime_agent_name VARCHAR,
    p_capability_version_id UUID,
    p_prompt_version_id UUID,
    p_model_policy_id UUID,
    p_budget_reservation_id UUID,
    p_input_artifact_ids JSONB,
    p_runtime_run_id UUID,
    p_task_execution_generation BIGINT,
    p_operation_kind VARCHAR,
    p_multitask_strategy VARCHAR,
    p_request_hash CHAR(64),
    p_idempotency_key VARCHAR,
    p_predecessor_runtime_run_id UUID,
    p_expected_checkpoint_id VARCHAR,
    p_runtime_version VARCHAR,
    p_agent_name VARCHAR,
    p_accepted_event_id UUID,
    p_accepted_event_payload JSONB
)
RETURNS SETOF deer_runtime.runtime_run
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, deer_runtime
AS $function$
DECLARE
    v_thread deer_runtime.runtime_thread%ROWTYPE;
    v_conflicting_thread deer_runtime.runtime_thread%ROWTYPE;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_event deer_runtime.runtime_run_event%ROWTYPE;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_thread_id IS NULL
       OR p_task_run_id IS NULL OR p_task_step_id IS NULL
       OR p_agent_instance_id IS NULL OR p_user_id IS NULL
       OR p_conversation_id IS NULL
       OR p_runtime_thread_revision IS NULL OR p_runtime_thread_revision < 1
       OR p_runtime_type IS NULL
       OR p_runtime_type !~ '^[A-Z][A-Z0-9_]{0,31}$'
       OR p_runtime_agent_name IS NULL OR BTRIM(p_runtime_agent_name) = ''
       OR LENGTH(p_runtime_agent_name) > 128
       OR p_capability_version_id IS NULL OR p_prompt_version_id IS NULL
       OR p_model_policy_id IS NULL OR p_budget_reservation_id IS NULL
       OR p_input_artifact_ids IS NULL
       OR JSONB_TYPEOF(p_input_artifact_ids) <> 'array'
       OR p_runtime_run_id IS NULL
       OR p_task_execution_generation IS NULL OR p_task_execution_generation < 1
       OR p_operation_kind IS NULL OR BTRIM(p_operation_kind) = ''
       OR LENGTH(p_operation_kind) > 16
       OR p_multitask_strategy IS NULL OR BTRIM(p_multitask_strategy) = ''
       OR LENGTH(p_multitask_strategy) > 16
       OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_idempotency_key IS NULL OR BTRIM(p_idempotency_key) = ''
       OR LENGTH(p_idempotency_key) > 200
       OR p_expected_checkpoint_id IS NOT NULL
          AND (BTRIM(p_expected_checkpoint_id) = ''
               OR LENGTH(p_expected_checkpoint_id) > 160)
       OR p_runtime_version IS NULL OR BTRIM(p_runtime_version) = ''
       OR LENGTH(p_runtime_version) > 128
       OR p_agent_name IS NULL OR BTRIM(p_agent_name) = ''
       OR LENGTH(p_agent_name) > 128
       OR p_accepted_event_id IS NULL
       OR p_accepted_event_payload IS NULL
       OR JSONB_TYPEOF(p_accepted_event_payload) <> 'object'
       OR OCTET_LENGTH(p_accepted_event_payload::TEXT) > 65536 THEN
        RAISE EXCEPTION 'invalid runtime admission arguments' USING ERRCODE = '22023';
    END IF;

    IF p_operation_kind <> 'START' THEN
        RAISE EXCEPTION 'runtime admission operation % is not supported', p_operation_kind
            USING ERRCODE = '0A000';
    END IF;
    IF p_multitask_strategy <> 'REJECT' THEN
        RAISE EXCEPTION 'runtime admission strategy % is not supported', p_multitask_strategy
            USING ERRCODE = '0A000';
    END IF;
    IF p_predecessor_runtime_run_id IS NOT NULL THEN
        RAISE EXCEPTION 'START admission cannot have a predecessor'
            USING ERRCODE = '22023';
    END IF;

    -- A row lock cannot protect a Thread that does not exist yet. This
    -- transaction-scoped key serializes both first creation and later replay;
    -- the table row lock below remains the durable per-Thread write barrier.
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            p_tenant_id::TEXT || ':' || p_runtime_thread_id::TEXT,
            7619104233
        )
    );
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            p_tenant_id::TEXT || ':' || p_task_step_id::TEXT || ':'
                || p_runtime_thread_revision::TEXT,
            7619104234
        )
    );

    SELECT * INTO v_thread
      FROM deer_runtime.runtime_thread
     WHERE tenant_id = p_tenant_id
       AND runtime_thread_id = p_runtime_thread_id;
    IF FOUND THEN
        IF v_thread.task_run_id IS DISTINCT FROM p_task_run_id
           OR v_thread.task_step_id IS DISTINCT FROM p_task_step_id
           OR v_thread.agent_instance_id IS DISTINCT FROM p_agent_instance_id
           OR v_thread.user_id IS DISTINCT FROM p_user_id
           OR v_thread.conversation_id IS DISTINCT FROM p_conversation_id
           OR v_thread.source_message_id IS DISTINCT FROM p_source_message_id
           OR v_thread.runtime_thread_revision IS DISTINCT FROM p_runtime_thread_revision
           OR v_thread.runtime_type IS DISTINCT FROM p_runtime_type
           OR v_thread.runtime_agent_name IS DISTINCT FROM p_runtime_agent_name
           OR v_thread.capability_version_id IS DISTINCT FROM p_capability_version_id
           OR v_thread.prompt_version_id IS DISTINCT FROM p_prompt_version_id
           OR v_thread.model_policy_id IS DISTINCT FROM p_model_policy_id
           OR v_thread.budget_reservation_id IS DISTINCT FROM p_budget_reservation_id
           OR v_thread.input_artifact_ids IS DISTINCT FROM p_input_artifact_ids THEN
            RAISE EXCEPTION 'runtime Thread admission identity conflict'
                USING ERRCODE = '23505';
        END IF;
    ELSE
        SELECT * INTO v_conflicting_thread
          FROM deer_runtime.runtime_thread
         WHERE tenant_id = p_tenant_id
           AND task_step_id = p_task_step_id
           AND runtime_thread_revision = p_runtime_thread_revision;
        IF FOUND THEN
            RAISE EXCEPTION 'runtime Thread revision admission identity conflict'
                USING ERRCODE = '23505';
        END IF;

        INSERT INTO deer_runtime.runtime_thread (
            tenant_id, runtime_thread_id, task_run_id, task_step_id,
            agent_instance_id, user_id, conversation_id, source_message_id,
            runtime_thread_revision, runtime_type, runtime_agent_name,
            capability_version_id, prompt_version_id, model_policy_id,
            budget_reservation_id, input_artifact_ids
        ) VALUES (
            p_tenant_id, p_runtime_thread_id, p_task_run_id, p_task_step_id,
            p_agent_instance_id, p_user_id, p_conversation_id, p_source_message_id,
            p_runtime_thread_revision, p_runtime_type, p_runtime_agent_name,
            p_capability_version_id, p_prompt_version_id, p_model_policy_id,
            p_budget_reservation_id, p_input_artifact_ids
        ) RETURNING * INTO v_thread;
    END IF;

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run
     WHERE tenant_id = p_tenant_id
       AND runtime_thread_id = p_runtime_thread_id
       AND idempotency_key = p_idempotency_key
     FOR UPDATE;
    IF FOUND THEN
        IF v_run.runtime_run_id IS DISTINCT FROM p_runtime_run_id
           OR v_run.task_step_id IS DISTINCT FROM p_task_step_id
           OR v_run.task_execution_generation IS DISTINCT FROM p_task_execution_generation
           OR v_run.operation_kind IS DISTINCT FROM p_operation_kind
           OR v_run.multitask_strategy IS DISTINCT FROM p_multitask_strategy
           OR v_run.request_hash IS DISTINCT FROM p_request_hash
           OR v_run.predecessor_runtime_run_id IS DISTINCT FROM p_predecessor_runtime_run_id
           OR v_run.expected_checkpoint_id IS DISTINCT FROM p_expected_checkpoint_id
           OR v_run.runtime_version IS DISTINCT FROM p_runtime_version
           OR v_run.agent_name IS DISTINCT FROM p_agent_name THEN
            RAISE EXCEPTION 'runtime Run admission idempotency conflict'
                USING ERRCODE = '23505';
        END IF;

        SELECT * INTO v_event
          FROM deer_runtime.runtime_run_event
         WHERE tenant_id = p_tenant_id
           AND runtime_run_id = p_runtime_run_id
           AND sequence_no = 1;
        IF NOT FOUND
           OR v_event.runtime_thread_id IS DISTINCT FROM p_runtime_thread_id
           OR v_event.event_id IS DISTINCT FROM p_accepted_event_id
           OR v_event.event_type <> 'RUN_ACCEPTED'
           OR v_event.event_version <> 1
           OR v_event.run_version <> 1
           OR v_event.lease_owner IS NOT NULL
           OR v_event.lease_epoch <> 0
           OR v_event.checkpoint_id IS NOT NULL
           OR v_event.payload IS DISTINCT FROM p_accepted_event_payload THEN
            RAISE EXCEPTION 'runtime Run accepted-event idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN NEXT v_run;
        RETURN;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM deer_runtime.runtime_run
         WHERE tenant_id = p_tenant_id
           AND runtime_run_id = p_runtime_run_id
    ) OR EXISTS (
        SELECT 1
          FROM deer_runtime.runtime_run
         WHERE tenant_id = p_tenant_id
           AND task_step_id = p_task_step_id
           AND task_execution_generation = p_task_execution_generation
    ) THEN
        RAISE EXCEPTION 'runtime Run admission identity conflict'
            USING ERRCODE = '23505';
    END IF;

    -- REJECT is deliberately represented as no admitted row. Identity
    -- collisions were classified above; only a distinct active intent reaches
    -- this zero-row result. The partial unique index remains the DB backstop.
    IF EXISTS (
        SELECT 1
          FROM deer_runtime.runtime_run
         WHERE tenant_id = p_tenant_id
           AND runtime_thread_id = p_runtime_thread_id
           AND status IN (
               'QUEUED', 'RUNNING', 'WAITING_USER_INPUT', 'WAITING_AUTH',
               'PAUSED', 'CANCEL_REQUESTED', 'CANCELLING'
           )
    ) THEN
        RETURN;
    END IF;

    INSERT INTO deer_runtime.runtime_run (
        tenant_id, runtime_run_id, runtime_thread_id, task_step_id,
        task_execution_generation, status, operation_kind, multitask_strategy,
        request_hash, idempotency_key, predecessor_runtime_run_id,
        expected_checkpoint_id, next_event_sequence_no,
        event_retention_floor_sequence, run_version, lease_epoch, attempt,
        runtime_version, agent_name
    ) VALUES (
        p_tenant_id, p_runtime_run_id, p_runtime_thread_id, p_task_step_id,
        p_task_execution_generation, 'QUEUED', p_operation_kind,
        p_multitask_strategy, p_request_hash, p_idempotency_key,
        p_predecessor_runtime_run_id, p_expected_checkpoint_id, 2, 1, 1, 0, 0,
        p_runtime_version, p_agent_name
    ) RETURNING * INTO v_run;

    INSERT INTO deer_runtime.runtime_run_event (
        tenant_id, runtime_run_id, runtime_thread_id, event_id, sequence_no,
        event_type, event_version, run_version, lease_owner, lease_epoch,
        checkpoint_id, payload
    ) VALUES (
        p_tenant_id, p_runtime_run_id, p_runtime_thread_id, p_accepted_event_id, 1,
        'RUN_ACCEPTED', 1, 1, NULL, 0, NULL, p_accepted_event_payload
    );
    RETURN NEXT v_run;
END;
$function$;

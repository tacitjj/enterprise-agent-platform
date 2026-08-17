-- Purpose: persist an explicit Run source without fabricating conversations for task steps.
-- Scope: H12 / 2.2 remains CONVERSATION; structured / 3.0 is exactly TASK_STEP.
-- Preconditions: migrations 000-021 are current and capability roles remain sealed.
-- Activation: no structured Driver, Provider, UI, or production route is enabled here.
-- Rollback: deploy the previous runtime first; use a reviewed later migration for rollback.

LOCK TABLE deer_runtime.runtime_thread IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE deer_runtime.runtime_run IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE deer_runtime.runtime_execution_admission_ref IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE deer_runtime.runtime_run_event IN SHARE ROW EXCLUSIVE MODE;

ALTER TABLE deer_runtime.runtime_thread
    ADD COLUMN source_kind VARCHAR(16) NOT NULL DEFAULT 'CONVERSATION';
ALTER TABLE deer_runtime.runtime_thread
    ALTER COLUMN source_kind DROP DEFAULT,
    ALTER COLUMN conversation_id DROP NOT NULL;
ALTER TABLE deer_runtime.runtime_thread
    ADD CONSTRAINT ck_runtime_thread_source_identity CHECK (
        (source_kind = 'CONVERSATION' AND conversation_id IS NOT NULL)
        OR
        (source_kind = 'TASK_STEP'
            AND conversation_id IS NULL
            AND source_message_id IS NULL)
    );

DO $precondition$
DECLARE
    v_admit REGPROCEDURE;
    v_load REGPROCEDURE;
BEGIN
    v_admit := pg_catalog.to_regprocedure(
        'deer_runtime.admit_runtime_run(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,bigint,varchar,varchar,uuid,uuid,uuid,uuid,jsonb,uuid,bigint,varchar,varchar,character,varchar,uuid,varchar,varchar,varchar,varchar,uuid,character,uuid,jsonb)'
    );
    v_load := pg_catalog.to_regprocedure(
        'deer_runtime.load_runtime_execution_authority(uuid,uuid,varchar,bigint)'
    );
    IF v_admit IS NULL OR v_load IS NULL THEN
        RAISE EXCEPTION 'runtime source migration requires the current admission routines'
            USING ERRCODE = '42704';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_proc AS procedure
          JOIN pg_catalog.pg_roles AS owner ON owner.oid = procedure.proowner
         WHERE procedure.oid IN (v_admit, v_load)
           AND owner.rolname <> 'dianlian_supervisor_routine_owner'
    ) THEN
        RAISE EXCEPTION 'runtime admission routine owner drifted'
            USING ERRCODE = '42501';
    END IF;
END;
$precondition$;

GRANT CREATE ON SCHEMA deer_runtime TO dianlian_supervisor_routine_owner;
SET LOCAL ROLE dianlian_supervisor_routine_owner;

DROP FUNCTION deer_runtime.admit_runtime_run(
    UUID, UUID, UUID, UUID, UUID, UUID, UUID, UUID,
    BIGINT, VARCHAR, VARCHAR, UUID, UUID, UUID, UUID, JSONB,
    UUID, BIGINT, VARCHAR, VARCHAR, CHAR(64), VARCHAR, UUID, VARCHAR,
    VARCHAR, VARCHAR, VARCHAR, UUID, CHAR(64), UUID, JSONB
) RESTRICT;

CREATE FUNCTION deer_runtime.admit_runtime_run(
    p_tenant_id UUID,
    p_runtime_thread_id UUID,
    p_task_run_id UUID,
    p_task_step_id UUID,
    p_agent_instance_id UUID,
    p_user_id UUID,
    p_source_kind VARCHAR,
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
    p_admission_contract_version VARCHAR,
    p_admission_snapshot_id UUID,
    p_admission_snapshot_hash CHAR(64),
    p_accepted_event_id UUID,
    p_accepted_event_payload JSONB
)
RETURNS SETOF deer_runtime.runtime_run
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
DECLARE
    v_thread deer_runtime.runtime_thread%ROWTYPE;
    v_conflicting_thread deer_runtime.runtime_thread%ROWTYPE;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_admission_ref deer_runtime.runtime_execution_admission_ref%ROWTYPE;
    v_event deer_runtime.runtime_run_event%ROWTYPE;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_thread_id IS NULL
       OR p_task_run_id IS NULL OR p_task_step_id IS NULL
       OR p_agent_instance_id IS NULL OR p_user_id IS NULL
       OR p_source_kind IS NULL
       OR p_source_kind NOT IN ('CONVERSATION', 'TASK_STEP')
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
       OR p_admission_snapshot_id IS NULL
       OR p_admission_snapshot_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_admission_snapshot_hash IS NULL
       OR p_admission_snapshot_hash !~ '^[0-9a-f]{64}$'
       OR p_accepted_event_id IS NULL
       OR p_accepted_event_payload IS NULL
       OR JSONB_TYPEOF(p_accepted_event_payload) <> 'object'
       OR OCTET_LENGTH(p_accepted_event_payload::TEXT) > 65536 THEN
        RAISE EXCEPTION 'invalid runtime admission arguments' USING ERRCODE = '22023';
    END IF;

    IF p_admission_contract_version IS NULL
       OR p_admission_contract_version NOT IN ('2.2', '3.0') THEN
        RAISE EXCEPTION 'runtime admission contract % is not supported',
            p_admission_contract_version USING ERRCODE = '0A000';
    END IF;
    IF p_admission_contract_version = '2.2' THEN
        IF p_source_kind <> 'CONVERSATION'
           OR p_conversation_id IS NULL
           OR (p_accepted_event_payload ->> 'schemaVersion')
                IS DISTINCT FROM 'runtime-run-accepted-v2'
           OR p_accepted_event_payload ? 'sourceKind' THEN
            RAISE EXCEPTION '2.2 admission requires a v2 conversation source'
                USING ERRCODE = '22023';
        END IF;
    ELSIF p_source_kind <> 'TASK_STEP'
       OR p_conversation_id IS NOT NULL
       OR p_source_message_id IS NOT NULL
       OR p_runtime_thread_revision <> p_task_execution_generation
       OR p_runtime_type <> 'JAVA_CAPABILITY_STRUCTURED'
       OR (p_accepted_event_payload ->> 'schemaVersion')
            IS DISTINCT FROM 'runtime-run-accepted-v3'
       OR (p_accepted_event_payload ->> 'sourceKind')
            IS DISTINCT FROM 'TASK_STEP' THEN
        RAISE EXCEPTION '3.0 admission requires a v3 task-step source'
            USING ERRCODE = '22023';
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
           OR v_thread.source_kind IS DISTINCT FROM p_source_kind
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
            agent_instance_id, user_id, source_kind, conversation_id,
            source_message_id, runtime_thread_revision, runtime_type,
            runtime_agent_name, capability_version_id, prompt_version_id,
            model_policy_id, budget_reservation_id, input_artifact_ids
        ) VALUES (
            p_tenant_id, p_runtime_thread_id, p_task_run_id, p_task_step_id,
            p_agent_instance_id, p_user_id, p_source_kind, p_conversation_id,
            p_source_message_id, p_runtime_thread_revision, p_runtime_type,
            p_runtime_agent_name, p_capability_version_id, p_prompt_version_id,
            p_model_policy_id, p_budget_reservation_id, p_input_artifact_ids
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

        SELECT * INTO v_admission_ref
          FROM deer_runtime.runtime_execution_admission_ref
         WHERE tenant_id = p_tenant_id
           AND runtime_run_id = p_runtime_run_id;
        IF NOT FOUND
           OR v_admission_ref.admission_contract_version
                IS DISTINCT FROM p_admission_contract_version
           OR v_admission_ref.admission_snapshot_id
                IS DISTINCT FROM p_admission_snapshot_id
           OR v_admission_ref.admission_snapshot_hash
                IS DISTINCT FROM p_admission_snapshot_hash THEN
            RAISE EXCEPTION 'runtime Run admission receipt idempotency conflict'
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
        SELECT 1 FROM deer_runtime.runtime_run
         WHERE tenant_id = p_tenant_id AND runtime_run_id = p_runtime_run_id
    ) OR EXISTS (
        SELECT 1 FROM deer_runtime.runtime_run
         WHERE tenant_id = p_tenant_id
           AND task_step_id = p_task_step_id
           AND task_execution_generation = p_task_execution_generation
    ) THEN
        RAISE EXCEPTION 'runtime Run admission identity conflict'
            USING ERRCODE = '23505';
    END IF;

    IF EXISTS (
        SELECT 1 FROM deer_runtime.runtime_run
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

    INSERT INTO deer_runtime.runtime_execution_admission_ref (
        tenant_id, runtime_run_id, admission_contract_version,
        admission_snapshot_id, admission_snapshot_hash
    ) VALUES (
        p_tenant_id, p_runtime_run_id, p_admission_contract_version,
        p_admission_snapshot_id, p_admission_snapshot_hash
    );

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

DROP FUNCTION deer_runtime.load_runtime_execution_authority(
    UUID, UUID, VARCHAR, BIGINT
) RESTRICT;

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
    source_kind VARCHAR(16),
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
    lease_epoch BIGINT,
    admission_contract_version VARCHAR(8),
    admission_snapshot_id UUID,
    admission_snapshot_hash CHAR(64)
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
           runtime_thread.source_kind,
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
           runtime_run.lease_epoch,
           admission_ref.admission_contract_version,
           admission_ref.admission_snapshot_id,
           admission_ref.admission_snapshot_hash
      FROM deer_runtime.runtime_run AS runtime_run
      JOIN deer_runtime.runtime_thread AS runtime_thread
        ON runtime_thread.tenant_id = runtime_run.tenant_id
       AND runtime_thread.runtime_thread_id = runtime_run.runtime_thread_id
       AND runtime_thread.task_step_id = runtime_run.task_step_id
      JOIN deer_runtime.runtime_execution_admission_ref AS admission_ref
        ON admission_ref.tenant_id = runtime_run.tenant_id
       AND admission_ref.runtime_run_id = runtime_run.runtime_run_id
       AND admission_ref.admission_contract_version IN ('2.2', '3.0')
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
       AND runtime_run.status = 'RUNNING'
       AND runtime_run.lease_owner = p_lease_owner
       AND runtime_run.lease_epoch = p_lease_epoch
       AND runtime_run.lease_until > CLOCK_TIMESTAMP();
END;
$function$;

REVOKE ALL PRIVILEGES ON FUNCTION deer_runtime.admit_runtime_run(
    UUID, UUID, UUID, UUID, UUID, UUID, VARCHAR, UUID, UUID,
    BIGINT, VARCHAR, VARCHAR, UUID, UUID, UUID, UUID, JSONB,
    UUID, BIGINT, VARCHAR, VARCHAR, CHAR(64), VARCHAR, UUID, VARCHAR,
    VARCHAR, VARCHAR, VARCHAR, UUID, CHAR(64), UUID, JSONB
) FROM PUBLIC, dianlian_supervisor_executor,
    dianlian_supervisor_permit_authorizer,
    dianlian_supervisor_dispatch_authorizer,
    dianlian_supervisor_outcome_reconciler,
    dianlian_supervisor_controller;
GRANT EXECUTE ON FUNCTION deer_runtime.admit_runtime_run(
    UUID, UUID, UUID, UUID, UUID, UUID, VARCHAR, UUID, UUID,
    BIGINT, VARCHAR, VARCHAR, UUID, UUID, UUID, UUID, JSONB,
    UUID, BIGINT, VARCHAR, VARCHAR, CHAR(64), VARCHAR, UUID, VARCHAR,
    VARCHAR, VARCHAR, VARCHAR, UUID, CHAR(64), UUID, JSONB
) TO dianlian_supervisor_run_admitter;

REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.load_runtime_execution_authority(UUID, UUID, VARCHAR, BIGINT)
    FROM PUBLIC, dianlian_supervisor_run_admitter,
    dianlian_supervisor_permit_authorizer,
    dianlian_supervisor_dispatch_authorizer,
    dianlian_supervisor_outcome_reconciler,
    dianlian_supervisor_controller;
GRANT EXECUTE ON FUNCTION
    deer_runtime.load_runtime_execution_authority(UUID, UUID, VARCHAR, BIGINT)
    TO dianlian_supervisor_executor;

RESET ROLE;
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner;

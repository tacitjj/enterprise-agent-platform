-- Purpose: bind every executable Supervisor Run to one immutable Java admission receipt.
-- Scope: PostgreSQL 15+; only the dormant deer_runtime Supervisor boundary is affected.
-- Preconditions: migrations 000-008 are current; no legacy Run may remain active.
-- Idempotency: the migration ledger applies this immutable file once by checksum.
-- Activation: only admission contract 2.2 is accepted; no worker is activated here.
-- Rollback: deploy the previous runtime first; removal requires a reviewed later migration.

LOCK TABLE deer_runtime.runtime_run IN SHARE ROW EXCLUSIVE MODE;

DO $legacy_active_precondition$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM deer_runtime.runtime_run
         WHERE status IN (
             'QUEUED', 'RUNNING', 'WAITING_USER_INPUT', 'WAITING_AUTH',
             'PAUSED', 'CANCEL_REQUESTED', 'CANCELLING'
         )
    ) THEN
        RAISE EXCEPTION 'active legacy runtime Runs must be resolved before admission binding'
            USING ERRCODE = '55000';
    END IF;
END;
$legacy_active_precondition$;

CREATE TABLE deer_runtime.runtime_execution_admission_ref (
    tenant_id UUID NOT NULL,
    runtime_run_id UUID NOT NULL,
    admission_contract_version VARCHAR(8) NOT NULL,
    admission_snapshot_id UUID NOT NULL,
    admission_snapshot_hash CHAR(64) NOT NULL,
    PRIMARY KEY (tenant_id, runtime_run_id),
    FOREIGN KEY (tenant_id, runtime_run_id)
        REFERENCES deer_runtime.runtime_run (tenant_id, runtime_run_id),
    UNIQUE (admission_snapshot_id),
    CONSTRAINT ck_runtime_execution_admission_ref_non_nil_ids CHECK (
        tenant_id <> '00000000-0000-0000-0000-000000000000'::UUID
        AND runtime_run_id <> '00000000-0000-0000-0000-000000000000'::UUID
        AND admission_snapshot_id <> '00000000-0000-0000-0000-000000000000'::UUID
    ),
    CONSTRAINT ck_runtime_execution_admission_ref_contract_v22 CHECK (
        admission_contract_version = '2.2'
    ),
    CONSTRAINT ck_runtime_execution_admission_ref_snapshot_hash CHECK (
        admission_snapshot_hash ~ '^[0-9a-f]{64}$'
    )
);

GRANT SELECT, INSERT ON TABLE deer_runtime.runtime_execution_admission_ref
    TO dianlian_supervisor_routine_owner;
GRANT TRIGGER ON TABLE deer_runtime.runtime_execution_admission_ref
    TO dianlian_supervisor_routine_owner;
GRANT CREATE ON SCHEMA deer_runtime TO dianlian_supervisor_routine_owner;

SET LOCAL ROLE dianlian_supervisor_routine_owner;

CREATE TRIGGER trg_runtime_execution_admission_ref_append_only
    BEFORE UPDATE OR DELETE ON deer_runtime.runtime_execution_admission_ref
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

CREATE TRIGGER trg_runtime_execution_admission_ref_no_truncate
    BEFORE TRUNCATE ON deer_runtime.runtime_execution_admission_ref
    FOR EACH STATEMENT EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

DROP FUNCTION deer_runtime.admit_runtime_run(
    UUID, UUID, UUID, UUID, UUID, UUID, UUID, UUID,
    BIGINT, VARCHAR, VARCHAR, UUID, UUID, UUID, UUID, JSONB,
    UUID, BIGINT, VARCHAR, VARCHAR, CHAR(64), VARCHAR, UUID, VARCHAR,
    VARCHAR, VARCHAR, UUID, JSONB
) RESTRICT;

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

    IF p_admission_contract_version IS DISTINCT FROM '2.2' THEN
        RAISE EXCEPTION 'runtime admission contract % is not supported',
            p_admission_contract_version
            USING ERRCODE = '0A000';
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

DROP FUNCTION deer_runtime.select_next_runtime_run_candidate(VARCHAR, VARCHAR) RESTRICT;

CREATE FUNCTION deer_runtime.select_next_runtime_run_candidate(
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
     WHERE runtime_run.status = 'QUEUED'
       AND runtime_run.runtime_version = p_runtime_version
       AND runtime_run.agent_name = p_agent_name
     ORDER BY runtime_run.created_at,
              runtime_run.tenant_id,
              runtime_run.runtime_run_id
     LIMIT 1;
END;
$function$;

CREATE OR REPLACE FUNCTION deer_runtime.claim_runtime_run(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_seconds INTEGER,
    p_started_event_id UUID,
    p_event_payload JSONB
)
RETURNS SETOF deer_runtime.runtime_run
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_event deer_runtime.runtime_run_event%ROWTYPE;
    v_sequence_no BIGINT;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_run_id IS NULL OR p_started_event_id IS NULL
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_seconds IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600
       OR p_event_payload IS NULL OR JSONB_TYPEOF(p_event_payload) <> 'object'
       OR OCTET_LENGTH(p_event_payload::TEXT) > 65536 THEN
        RAISE EXCEPTION 'invalid runtime run claim arguments' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run
     WHERE tenant_id = p_tenant_id AND runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM deer_runtime.runtime_execution_admission_ref
         WHERE tenant_id = p_tenant_id
           AND runtime_run_id = p_runtime_run_id
           AND admission_contract_version = '2.2'
    ) THEN
        RETURN;
    END IF;
    v_now := CLOCK_TIMESTAMP();

    SELECT * INTO v_event
      FROM deer_runtime.runtime_run_event
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND event_id = p_started_event_id;
    IF FOUND THEN
        IF v_event.event_type <> 'RUN_STARTED'
           OR v_event.payload IS DISTINCT FROM p_event_payload THEN
            RAISE EXCEPTION 'runtime run claim idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        IF v_run.status = 'RUNNING'
           AND v_run.lease_owner = p_lease_owner
           AND v_run.lease_epoch = v_event.lease_epoch
           AND v_run.lease_until > v_now
           AND v_event.lease_owner = p_lease_owner THEN
            RETURN NEXT v_run;
        END IF;
        RETURN;
    END IF;

    IF v_run.status <> 'QUEUED' OR v_run.lease_epoch <> 0 THEN
        RETURN;
    END IF;
    v_sequence_no := v_run.next_event_sequence_no;

    UPDATE deer_runtime.runtime_run
       SET status = 'RUNNING',
           lease_owner = p_lease_owner,
           lease_until = v_now + MAKE_INTERVAL(secs => p_lease_seconds),
           lease_epoch = 1,
           heartbeat_at = v_now,
           attempt = 1,
           started_at = v_now,
           next_event_sequence_no = v_sequence_no + 1,
           run_version = run_version + 1,
           updated_at = v_now
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND status = 'QUEUED'
       AND lease_epoch = 0
    RETURNING * INTO v_run;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    INSERT INTO deer_runtime.runtime_run_event (
        tenant_id, runtime_run_id, runtime_thread_id, event_id, sequence_no,
        event_type, run_version, lease_owner, lease_epoch, payload, occurred_at, created_at
    ) VALUES (
        v_run.tenant_id, v_run.runtime_run_id, v_run.runtime_thread_id,
        p_started_event_id, v_sequence_no, 'RUN_STARTED', v_run.run_version,
        p_lease_owner, v_run.lease_epoch, p_event_payload, v_now, v_now
    );
    RETURN NEXT v_run;
END;
$function$;

CREATE OR REPLACE FUNCTION deer_runtime.takeover_runtime_run(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_new_lease_owner VARCHAR,
    p_lease_seconds INTEGER,
    p_takeover_event_id UUID,
    p_event_payload JSONB
)
RETURNS SETOF deer_runtime.runtime_run
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_event deer_runtime.runtime_run_event%ROWTYPE;
    v_sequence_no BIGINT;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_run_id IS NULL OR p_takeover_event_id IS NULL
       OR p_new_lease_owner IS NULL OR BTRIM(p_new_lease_owner) = ''
       OR LENGTH(p_new_lease_owner) > 160
       OR p_lease_seconds IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600
       OR p_event_payload IS NULL OR JSONB_TYPEOF(p_event_payload) <> 'object'
       OR OCTET_LENGTH(p_event_payload::TEXT) > 65536 THEN
        RAISE EXCEPTION 'invalid runtime run takeover arguments' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run
     WHERE tenant_id = p_tenant_id AND runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM deer_runtime.runtime_execution_admission_ref
         WHERE tenant_id = p_tenant_id
           AND runtime_run_id = p_runtime_run_id
           AND admission_contract_version = '2.2'
    ) THEN
        RETURN;
    END IF;
    v_now := CLOCK_TIMESTAMP();

    SELECT * INTO v_event
      FROM deer_runtime.runtime_run_event
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND event_id = p_takeover_event_id;
    IF FOUND THEN
        IF v_event.event_type <> 'RUN_TAKEN_OVER'
           OR v_event.payload IS DISTINCT FROM p_event_payload THEN
            RAISE EXCEPTION 'runtime run takeover idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        IF v_run.lease_owner = p_new_lease_owner
           AND v_run.lease_epoch = v_event.lease_epoch
           AND v_run.lease_until > v_now
           AND v_event.lease_owner = p_new_lease_owner THEN
            RETURN NEXT v_run;
        END IF;
        RETURN;
    END IF;

    IF v_run.status NOT IN (
           'RUNNING', 'WAITING_USER_INPUT', 'WAITING_AUTH', 'PAUSED',
           'CANCEL_REQUESTED', 'CANCELLING'
       ) THEN
        RETURN;
    END IF;
    IF v_run.lease_owner IS NULL OR v_run.lease_until IS NULL
       OR v_run.lease_until > v_now THEN
        RETURN;
    END IF;
    v_sequence_no := v_run.next_event_sequence_no;

    UPDATE deer_runtime.runtime_run
       SET lease_owner = p_new_lease_owner,
           lease_until = v_now + MAKE_INTERVAL(secs => p_lease_seconds),
           lease_epoch = lease_epoch + 1,
           heartbeat_at = v_now,
           attempt = attempt + 1,
           next_event_sequence_no = v_sequence_no + 1,
           run_version = run_version + 1,
           updated_at = v_now
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND lease_until <= v_now
    RETURNING * INTO v_run;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    INSERT INTO deer_runtime.runtime_run_event (
        tenant_id, runtime_run_id, runtime_thread_id, event_id, sequence_no,
        event_type, run_version, lease_owner, lease_epoch, payload, occurred_at, created_at
    ) VALUES (
        v_run.tenant_id, v_run.runtime_run_id, v_run.runtime_thread_id,
        p_takeover_event_id, v_sequence_no, 'RUN_TAKEN_OVER', v_run.run_version,
        p_new_lease_owner, v_run.lease_epoch, p_event_payload, v_now, v_now
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
       AND admission_ref.admission_contract_version = '2.2'
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
       AND runtime_run.status = 'RUNNING'
       AND runtime_run.lease_owner = p_lease_owner
       AND runtime_run.lease_epoch = p_lease_epoch
       AND runtime_run.lease_until > CLOCK_TIMESTAMP();
END;
$function$;

REVOKE ALL PRIVILEGES ON FUNCTION deer_runtime.admit_runtime_run(
    UUID, UUID, UUID, UUID, UUID, UUID, UUID, UUID,
    BIGINT, VARCHAR, VARCHAR, UUID, UUID, UUID, UUID, JSONB,
    UUID, BIGINT, VARCHAR, VARCHAR, CHAR(64), VARCHAR, UUID, VARCHAR,
    VARCHAR, VARCHAR, VARCHAR, UUID, CHAR(64), UUID, JSONB
) FROM PUBLIC;
REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.select_next_runtime_run_candidate(VARCHAR, VARCHAR, VARCHAR)
    FROM PUBLIC;
REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.claim_runtime_run(UUID, UUID, VARCHAR, INTEGER, UUID, JSONB)
    FROM PUBLIC;
REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.takeover_runtime_run(UUID, UUID, VARCHAR, INTEGER, UUID, JSONB)
    FROM PUBLIC;
REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.load_runtime_execution_authority(UUID, UUID, VARCHAR, BIGINT)
    FROM PUBLIC;

GRANT EXECUTE ON FUNCTION deer_runtime.admit_runtime_run(
    UUID, UUID, UUID, UUID, UUID, UUID, UUID, UUID,
    BIGINT, VARCHAR, VARCHAR, UUID, UUID, UUID, UUID, JSONB,
    UUID, BIGINT, VARCHAR, VARCHAR, CHAR(64), VARCHAR, UUID, VARCHAR,
    VARCHAR, VARCHAR, VARCHAR, UUID, CHAR(64), UUID, JSONB
) TO dianlian_supervisor_executor;
GRANT EXECUTE ON FUNCTION
    deer_runtime.select_next_runtime_run_candidate(VARCHAR, VARCHAR, VARCHAR)
    TO dianlian_supervisor_executor;
GRANT EXECUTE ON FUNCTION
    deer_runtime.claim_runtime_run(UUID, UUID, VARCHAR, INTEGER, UUID, JSONB)
    TO dianlian_supervisor_executor;
GRANT EXECUTE ON FUNCTION
    deer_runtime.takeover_runtime_run(UUID, UUID, VARCHAR, INTEGER, UUID, JSONB)
    TO dianlian_supervisor_executor;
GRANT EXECUTE ON FUNCTION
    deer_runtime.load_runtime_execution_authority(UUID, UUID, VARCHAR, BIGINT)
    TO dianlian_supervisor_executor;

RESET ROLE;

REVOKE TRIGGER ON TABLE deer_runtime.runtime_execution_admission_ref
    FROM dianlian_supervisor_routine_owner;
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner;

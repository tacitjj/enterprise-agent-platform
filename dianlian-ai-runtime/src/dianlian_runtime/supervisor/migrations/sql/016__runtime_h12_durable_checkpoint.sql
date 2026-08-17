-- Purpose: persist governed H12 state as immutable PostgreSQL checkpoints.
-- Scope: one current-fenced load primitive and one current-fenced CAS append primitive.
-- Preconditions: migrations 000-015 are current and the sealed Supervisor roles exist.
-- Idempotency: the migration ledger applies this immutable file once by checksum.
-- Activation: no worker uses this store until the PostgreSQL H12 adapter is enabled.
-- Rollback: deploy the previous runtime first; remove only in a reviewed later migration.

CREATE TABLE deer_runtime.runtime_h12_checkpoint
(
    tenant_id                  UUID         NOT NULL,
    runtime_run_id             UUID         NOT NULL,
    task_execution_generation BIGINT       NOT NULL CHECK (task_execution_generation > 0),
    checkpoint_id              VARCHAR(160) NOT NULL CHECK (BTRIM(checkpoint_id) <> ''),
    previous_checkpoint_id     VARCHAR(160),
    state_version              BIGINT       NOT NULL CHECK (state_version > 0),
    state_json                 JSONB        NOT NULL,
    state_hash                 CHAR(64)     NOT NULL CHECK (state_hash ~ '^[0-9a-f]{64}$'),
    transition_code            VARCHAR(64)  NOT NULL
        CHECK (transition_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
    event_id                   UUID         NOT NULL,
    created_by                 VARCHAR(160) NOT NULL CHECK (BTRIM(created_by) <> ''),
    lease_epoch                BIGINT       NOT NULL CHECK (lease_epoch > 0),
    created_at                 TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (tenant_id, runtime_run_id, checkpoint_id),
    UNIQUE (tenant_id, runtime_run_id, state_version),
    UNIQUE (tenant_id, runtime_run_id, event_id),
    FOREIGN KEY (tenant_id, runtime_run_id)
        REFERENCES deer_runtime.runtime_run (tenant_id, runtime_run_id),
    FOREIGN KEY (tenant_id, runtime_run_id, checkpoint_id)
        REFERENCES deer_runtime.runtime_checkpoint_ref
            (tenant_id, runtime_run_id, checkpoint_id),
    FOREIGN KEY (tenant_id, runtime_run_id, previous_checkpoint_id)
        REFERENCES deer_runtime.runtime_h12_checkpoint
            (tenant_id, runtime_run_id, checkpoint_id),
    CHECK (previous_checkpoint_id IS NULL OR BTRIM(previous_checkpoint_id) <> ''),
    CHECK (JSONB_TYPEOF(state_json) = 'object'),
    CHECK (OCTET_LENGTH(state_json::TEXT) <= 1048576)
);

CREATE INDEX idx_runtime_h12_checkpoint_latest
    ON deer_runtime.runtime_h12_checkpoint
        (tenant_id, runtime_run_id, state_version DESC);

GRANT TRIGGER ON TABLE deer_runtime.runtime_h12_checkpoint
    TO dianlian_supervisor_routine_owner;
SET LOCAL ROLE dianlian_supervisor_routine_owner;

CREATE TRIGGER trg_runtime_h12_checkpoint_append_only
    BEFORE UPDATE OR DELETE ON deer_runtime.runtime_h12_checkpoint
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

CREATE TRIGGER trg_runtime_h12_checkpoint_no_truncate
    BEFORE TRUNCATE ON deer_runtime.runtime_h12_checkpoint
    FOR EACH STATEMENT EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

RESET ROLE;

CREATE FUNCTION deer_runtime.load_runtime_h12_checkpoint(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_task_execution_generation BIGINT,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT
)
RETURNS TABLE
(
    tenant_id UUID,
    runtime_run_id UUID,
    task_execution_generation BIGINT,
    checkpoint_id VARCHAR(160),
    previous_checkpoint_id VARCHAR(160),
    state_version BIGINT,
    state_json JSONB,
    state_hash CHAR(64),
    transition_code VARCHAR(64),
    event_id UUID,
    created_by VARCHAR(160),
    lease_epoch BIGINT,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
BEGIN
    IF p_tenant_id IS NULL
       OR p_tenant_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_run_id IS NULL
       OR p_runtime_run_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_task_execution_generation IS NULL
       OR p_task_execution_generation < 1
       OR p_lease_owner IS NULL
       OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL
       OR p_lease_epoch < 1 THEN
        RAISE EXCEPTION 'invalid runtime H12 checkpoint load arguments'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT checkpoint.tenant_id,
           checkpoint.runtime_run_id,
           checkpoint.task_execution_generation,
           checkpoint.checkpoint_id,
           checkpoint.previous_checkpoint_id,
           checkpoint.state_version,
           checkpoint.state_json,
           checkpoint.state_hash,
           checkpoint.transition_code,
           checkpoint.event_id,
           checkpoint.created_by,
           checkpoint.lease_epoch,
           checkpoint.created_at
      FROM deer_runtime.runtime_run AS runtime_run
      JOIN deer_runtime.runtime_h12_checkpoint AS checkpoint
        ON checkpoint.tenant_id = runtime_run.tenant_id
       AND checkpoint.runtime_run_id = runtime_run.runtime_run_id
       AND checkpoint.checkpoint_id = runtime_run.current_checkpoint_id
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
       AND runtime_run.task_execution_generation = p_task_execution_generation
       AND runtime_run.status = 'RUNNING'
       AND runtime_run.lease_owner = p_lease_owner
       AND runtime_run.lease_epoch = p_lease_epoch
       AND runtime_run.lease_until > CLOCK_TIMESTAMP();
END;
$function$;

CREATE FUNCTION deer_runtime.save_runtime_h12_checkpoint(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_task_execution_generation BIGINT,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_expected_checkpoint_id VARCHAR,
    p_expected_state_version BIGINT,
    p_event_id UUID,
    p_checkpoint_id VARCHAR,
    p_transition_code VARCHAR,
    p_state_json JSONB
)
RETURNS TABLE
(
    tenant_id UUID,
    runtime_run_id UUID,
    task_execution_generation BIGINT,
    checkpoint_id VARCHAR(160),
    previous_checkpoint_id VARCHAR(160),
    state_version BIGINT,
    state_json JSONB,
    state_hash CHAR(64),
    transition_code VARCHAR(64),
    event_id UUID,
    created_by VARCHAR(160),
    lease_epoch BIGINT,
    created_at TIMESTAMPTZ
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_existing deer_runtime.runtime_h12_checkpoint%ROWTYPE;
    v_current deer_runtime.runtime_h12_checkpoint%ROWTYPE;
    v_event deer_runtime.runtime_run_event%ROWTYPE;
    v_checkpoint_ref deer_runtime.runtime_checkpoint_ref%ROWTYPE;
    v_state_hash CHAR(64);
    v_event_payload JSONB;
    v_new_state_version BIGINT;
    v_new_run_version BIGINT;
    v_sequence_no BIGINT;
BEGIN
    IF p_tenant_id IS NULL
       OR p_tenant_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_run_id IS NULL
       OR p_runtime_run_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_task_execution_generation IS NULL
       OR p_task_execution_generation < 1
       OR p_lease_owner IS NULL
       OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL
       OR p_lease_epoch < 1
       OR p_expected_state_version IS NULL
       OR p_expected_state_version < 0
       OR (p_expected_state_version = 0 AND p_expected_checkpoint_id IS NOT NULL)
       OR (p_expected_state_version > 0 AND (
            p_expected_checkpoint_id IS NULL
            OR BTRIM(p_expected_checkpoint_id) = ''
            OR LENGTH(p_expected_checkpoint_id) > 160
       ))
       OR p_event_id IS NULL
       OR p_event_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_checkpoint_id IS NULL
       OR BTRIM(p_checkpoint_id) = ''
       OR LENGTH(p_checkpoint_id) > 160
       OR p_checkpoint_id IS NOT DISTINCT FROM p_expected_checkpoint_id
       OR p_transition_code IS NULL
       OR p_transition_code !~ '^[A-Z][A-Z0-9_]{0,63}$'
       OR p_state_json IS NULL
       OR JSONB_TYPEOF(p_state_json) <> 'object'
       OR OCTET_LENGTH(p_state_json::TEXT) > 1048576 THEN
        RAISE EXCEPTION 'invalid runtime H12 checkpoint save arguments'
            USING ERRCODE = '22023';
    END IF;
    IF (SELECT COUNT(*) FROM JSONB_OBJECT_KEYS(p_state_json)) <> 8
       OR p_state_json->>'schemaVersion' IS DISTINCT FROM 'governed-h12-state-v1'
       OR p_state_json->>'tenantId' IS DISTINCT FROM p_tenant_id::TEXT
       OR p_state_json->>'runtimeRunId' IS DISTINCT FROM p_runtime_run_id::TEXT
       OR COALESCE(p_state_json->>'taskExecutionGeneration', '') !~ '^[1-9][0-9]*$'
       OR COALESCE(p_state_json->>'stateVersion', '') !~ '^[1-9][0-9]*$'
       OR NOT p_state_json ? 'initialModel'
       OR NOT p_state_json ? 'tool'
       OR NOT p_state_json ? 'afterToolModel'
       OR JSONB_TYPEOF(p_state_json->'initialModel') NOT IN ('object', 'null')
       OR JSONB_TYPEOF(p_state_json->'tool') NOT IN ('object', 'null')
       OR JSONB_TYPEOF(p_state_json->'afterToolModel') NOT IN ('object', 'null') THEN
        RAISE EXCEPTION 'invalid runtime H12 checkpoint state document'
            USING ERRCODE = '22023';
    END IF;
    IF (p_state_json->>'taskExecutionGeneration')::BIGINT
            IS DISTINCT FROM p_task_execution_generation
       OR (p_state_json->>'stateVersion')::BIGINT
            IS DISTINCT FROM p_expected_state_version + 1 THEN
        RAISE EXCEPTION 'runtime H12 checkpoint state identity is invalid'
            USING ERRCODE = '22023';
    END IF;

    v_new_state_version := p_expected_state_version + 1;
    v_state_hash := ENCODE(SHA256(CONVERT_TO(p_state_json::TEXT, 'UTF8')), 'hex');
    v_event_payload := JSONB_BUILD_OBJECT(
        'schemaVersion', 'runtime-h12-checkpoint-event-v1',
        'transitionCode', p_transition_code,
        'stateVersion', v_new_state_version,
        'stateHash', v_state_hash,
        'previousCheckpointId', p_expected_checkpoint_id
    );

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    v_now := CLOCK_TIMESTAMP();
    IF v_run.task_execution_generation <> p_task_execution_generation
       OR v_run.status <> 'RUNNING'
       OR v_run.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_run.lease_epoch <> p_lease_epoch
       OR v_run.lease_until <= v_now THEN
        RETURN;
    END IF;

    SELECT * INTO v_existing
      FROM deer_runtime.runtime_h12_checkpoint AS checkpoint
     WHERE checkpoint.tenant_id = p_tenant_id
       AND checkpoint.runtime_run_id = p_runtime_run_id
       AND checkpoint.checkpoint_id = p_checkpoint_id;
    IF FOUND THEN
        SELECT * INTO v_event
          FROM deer_runtime.runtime_run_event AS event
         WHERE event.tenant_id = p_tenant_id
           AND event.runtime_run_id = p_runtime_run_id
           AND event.event_id = v_existing.event_id;
        IF v_existing.task_execution_generation = p_task_execution_generation
           AND v_existing.previous_checkpoint_id IS NOT DISTINCT FROM p_expected_checkpoint_id
           AND v_existing.state_version = v_new_state_version
           AND v_existing.state_json = p_state_json
           AND v_existing.state_hash = v_state_hash
           AND v_existing.transition_code = p_transition_code
           AND v_existing.event_id = p_event_id
           AND v_existing.created_by = p_lease_owner
           AND v_existing.lease_epoch = p_lease_epoch
           AND v_event.event_type = 'CHECKPOINT_SAVED'
           AND v_event.event_version = 1
           AND v_event.lease_owner = p_lease_owner
           AND v_event.lease_epoch = p_lease_epoch
           AND v_event.checkpoint_id = p_checkpoint_id
           AND v_event.payload = v_event_payload THEN
            SELECT checkpoint.* INTO v_current
              FROM deer_runtime.runtime_h12_checkpoint AS checkpoint
             WHERE checkpoint.tenant_id = p_tenant_id
               AND checkpoint.runtime_run_id = p_runtime_run_id
               AND checkpoint.checkpoint_id = v_run.current_checkpoint_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'runtime H12 current checkpoint projection drifted'
                    USING ERRCODE = '55000';
            END IF;
            RETURN QUERY SELECT
                v_current.tenant_id,
                v_current.runtime_run_id,
                v_current.task_execution_generation,
                v_current.checkpoint_id,
                v_current.previous_checkpoint_id,
                v_current.state_version,
                v_current.state_json,
                v_current.state_hash,
                v_current.transition_code,
                v_current.event_id,
                v_current.created_by,
                v_current.lease_epoch,
                v_current.created_at;
            RETURN;
        END IF;
        RAISE EXCEPTION 'runtime H12 checkpoint idempotency conflict'
            USING ERRCODE = '23505';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM deer_runtime.runtime_run_event AS event
         WHERE event.tenant_id = p_tenant_id
           AND event.runtime_run_id = p_runtime_run_id
           AND event.event_id = p_event_id
    ) OR EXISTS (
        SELECT 1
          FROM deer_runtime.runtime_checkpoint_ref AS checkpoint_ref
         WHERE checkpoint_ref.tenant_id = p_tenant_id
           AND checkpoint_ref.runtime_run_id = p_runtime_run_id
           AND checkpoint_ref.checkpoint_id = p_checkpoint_id
    ) THEN
        RAISE EXCEPTION 'runtime H12 checkpoint identity conflict'
            USING ERRCODE = '23505';
    END IF;

    IF p_expected_state_version = 0 THEN
        IF v_run.current_checkpoint_id IS NOT NULL
           OR v_run.current_checkpoint_sequence_no IS NOT NULL THEN
            RETURN;
        END IF;
    ELSE
        IF v_run.current_checkpoint_id IS DISTINCT FROM p_expected_checkpoint_id THEN
            RETURN;
        END IF;
        SELECT * INTO v_current
          FROM deer_runtime.runtime_h12_checkpoint AS checkpoint
         WHERE checkpoint.tenant_id = p_tenant_id
           AND checkpoint.runtime_run_id = p_runtime_run_id
           AND checkpoint.checkpoint_id = p_expected_checkpoint_id;
        IF NOT FOUND
           OR v_current.task_execution_generation <> p_task_execution_generation
           OR v_current.state_version <> p_expected_state_version THEN
            RETURN;
        END IF;
    END IF;

    v_sequence_no := v_run.next_event_sequence_no;
    v_new_run_version := v_run.run_version + 1;

    INSERT INTO deer_runtime.runtime_run_event (
        tenant_id, runtime_run_id, runtime_thread_id, event_id, sequence_no,
        event_type, event_version, run_version, lease_owner, lease_epoch,
        checkpoint_id, payload, occurred_at, created_at
    ) VALUES (
        v_run.tenant_id, v_run.runtime_run_id, v_run.runtime_thread_id,
        p_event_id, v_sequence_no, 'CHECKPOINT_SAVED', 1, v_new_run_version,
        p_lease_owner, p_lease_epoch, p_checkpoint_id, v_event_payload, v_now, v_now
    ) RETURNING * INTO v_event;

    INSERT INTO deer_runtime.runtime_checkpoint_ref (
        tenant_id, runtime_run_id, runtime_thread_id, checkpoint_id,
        checkpoint_namespace, sequence_no, event_id, run_version,
        lease_epoch, checkpoint_schema_version, created_at
    ) VALUES (
        v_run.tenant_id, v_run.runtime_run_id, v_run.runtime_thread_id,
        p_checkpoint_id, 'governed-h12', v_sequence_no, p_event_id,
        v_new_run_version, p_lease_epoch, 'governed-h12-state-v1', v_now
    ) RETURNING * INTO v_checkpoint_ref;

    INSERT INTO deer_runtime.runtime_h12_checkpoint (
        tenant_id, runtime_run_id, task_execution_generation,
        checkpoint_id, previous_checkpoint_id, state_version, state_json,
        state_hash, transition_code, event_id, created_by, lease_epoch, created_at
    ) VALUES (
        p_tenant_id, p_runtime_run_id, p_task_execution_generation,
        p_checkpoint_id, p_expected_checkpoint_id, v_new_state_version, p_state_json,
        v_state_hash, p_transition_code, p_event_id, p_lease_owner, p_lease_epoch, v_now
    ) RETURNING * INTO v_existing;

    UPDATE deer_runtime.runtime_run
       SET current_checkpoint_id = p_checkpoint_id,
           current_checkpoint_sequence_no = v_sequence_no,
           next_event_sequence_no = v_sequence_no + 1,
           run_version = v_new_run_version,
           updated_at = v_now
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id;

    RETURN QUERY SELECT
        v_existing.tenant_id,
        v_existing.runtime_run_id,
        v_existing.task_execution_generation,
        v_existing.checkpoint_id,
        v_existing.previous_checkpoint_id,
        v_existing.state_version,
        v_existing.state_json,
        v_existing.state_hash,
        v_existing.transition_code,
        v_existing.event_id,
        v_existing.created_by,
        v_existing.lease_epoch,
        v_existing.created_at;
END;
$function$;

REVOKE ALL PRIVILEGES ON TABLE deer_runtime.runtime_h12_checkpoint
    FROM PUBLIC, dianlian_supervisor_executor,
         dianlian_supervisor_permit_authorizer,
         dianlian_supervisor_dispatch_authorizer,
         dianlian_supervisor_outcome_reconciler,
         dianlian_supervisor_controller;
REVOKE TRIGGER ON TABLE deer_runtime.runtime_h12_checkpoint
    FROM dianlian_supervisor_routine_owner;
REVOKE ALL PRIVILEGES ON FUNCTION deer_runtime.load_runtime_h12_checkpoint(
    UUID, UUID, BIGINT, VARCHAR, BIGINT
) FROM PUBLIC, dianlian_supervisor_permit_authorizer,
       dianlian_supervisor_dispatch_authorizer,
       dianlian_supervisor_outcome_reconciler,
       dianlian_supervisor_controller;
REVOKE ALL PRIVILEGES ON FUNCTION deer_runtime.save_runtime_h12_checkpoint(
    UUID, UUID, BIGINT, VARCHAR, BIGINT, VARCHAR, BIGINT,
    UUID, VARCHAR, VARCHAR, JSONB
) FROM PUBLIC, dianlian_supervisor_permit_authorizer,
       dianlian_supervisor_dispatch_authorizer,
       dianlian_supervisor_outcome_reconciler,
       dianlian_supervisor_controller;

GRANT SELECT, INSERT ON TABLE deer_runtime.runtime_h12_checkpoint
    TO dianlian_supervisor_routine_owner;
GRANT EXECUTE ON FUNCTION deer_runtime.load_runtime_h12_checkpoint(
    UUID, UUID, BIGINT, VARCHAR, BIGINT
) TO dianlian_supervisor_executor;
GRANT EXECUTE ON FUNCTION deer_runtime.save_runtime_h12_checkpoint(
    UUID, UUID, BIGINT, VARCHAR, BIGINT, VARCHAR, BIGINT,
    UUID, VARCHAR, VARCHAR, JSONB
) TO dianlian_supervisor_executor;

GRANT CREATE ON SCHEMA deer_runtime TO dianlian_supervisor_routine_owner;
ALTER FUNCTION deer_runtime.load_runtime_h12_checkpoint(
    UUID, UUID, BIGINT, VARCHAR, BIGINT
) OWNER TO dianlian_supervisor_routine_owner;
ALTER FUNCTION deer_runtime.save_runtime_h12_checkpoint(
    UUID, UUID, BIGINT, VARCHAR, BIGINT, VARCHAR, BIGINT,
    UUID, VARCHAR, VARCHAR, JSONB
) OWNER TO dianlian_supervisor_routine_owner;
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner;

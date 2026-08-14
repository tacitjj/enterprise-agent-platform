-- Purpose: add fenced progress-event and Checkpoint-pointer primitives for S0.
-- Scope: PostgreSQL 15+; only deer_runtime run, event and checkpoint-reference facts.
-- Preconditions: migrations 000-002 are current; Checkpoint blobs already exist externally.
-- Idempotency: stable event/checkpoint identities replay exact committed facts only.
-- Activation: no application component invokes these functions in this migration.
-- Rollback: deploy the previous runtime first; remove functions in a reviewed later migration.

CREATE FUNCTION deer_runtime.append_runtime_run_event(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_event_id UUID,
    p_event_type VARCHAR,
    p_event_version SMALLINT,
    p_payload JSONB
)
RETURNS SETOF deer_runtime.runtime_run_event
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, deer_runtime
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_event deer_runtime.runtime_run_event%ROWTYPE;
    v_sequence_no BIGINT;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_run_id IS NULL OR p_event_id IS NULL
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_event_type NOT IN ('PLAN_CREATED', 'STEP_STARTED', 'STEP_PROGRESS')
       OR p_event_version IS NULL OR p_event_version < 1
       OR p_payload IS NULL OR JSONB_TYPEOF(p_payload) <> 'object'
       OR OCTET_LENGTH(p_payload::TEXT) > 65536 THEN
        RAISE EXCEPTION 'invalid runtime progress event arguments' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    v_now := CLOCK_TIMESTAMP();

    -- Recheck after the Run lock. A concurrent exact replay may have committed
    -- while this transaction was waiting for ownership serialization.
    SELECT * INTO v_event
      FROM deer_runtime.runtime_run_event
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND event_id = p_event_id;
    IF FOUND THEN
        IF v_event.event_type = p_event_type
           AND v_event.event_version = p_event_version
           AND v_event.lease_epoch = p_lease_epoch
           AND v_event.lease_owner = p_lease_owner
           AND v_event.checkpoint_id IS NULL
           AND v_event.payload = p_payload
           AND v_run.status = 'RUNNING'
           AND v_run.lease_owner = p_lease_owner
           AND v_run.lease_epoch = p_lease_epoch
           AND v_run.lease_until > v_now THEN
            RETURN NEXT v_event;
            RETURN;
        END IF;
        IF v_event.event_type = p_event_type
           AND v_event.event_version = p_event_version
           AND v_event.lease_epoch = p_lease_epoch
           AND v_event.checkpoint_id IS NULL
           AND v_event.payload = p_payload THEN
            RETURN;
        END IF;
        RAISE EXCEPTION 'runtime progress event idempotency conflict'
            USING ERRCODE = '23505';
    END IF;

    IF v_run.status <> 'RUNNING'
       OR v_run.lease_owner <> p_lease_owner
       OR v_run.lease_epoch <> p_lease_epoch
       OR v_run.lease_until <= v_now THEN
        RETURN;
    END IF;
    v_sequence_no := v_run.next_event_sequence_no;

    UPDATE deer_runtime.runtime_run
       SET next_event_sequence_no = v_sequence_no + 1,
           run_version = run_version + 1,
           updated_at = v_now
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
    RETURNING * INTO v_run;

    INSERT INTO deer_runtime.runtime_run_event (
        tenant_id, runtime_run_id, runtime_thread_id, event_id, sequence_no,
        event_type, event_version, run_version, lease_owner, lease_epoch, payload,
        occurred_at, created_at
    ) VALUES (
        v_run.tenant_id, v_run.runtime_run_id, v_run.runtime_thread_id,
        p_event_id, v_sequence_no, p_event_type, p_event_version,
        v_run.run_version, p_lease_owner, p_lease_epoch, p_payload, v_now, v_now
    ) RETURNING * INTO v_event;
    RETURN NEXT v_event;
END;
$function$;

CREATE FUNCTION deer_runtime.record_runtime_checkpoint_ref(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_event_id UUID,
    p_checkpoint_id VARCHAR,
    p_checkpoint_namespace VARCHAR,
    p_checkpoint_schema_version VARCHAR,
    p_event_payload JSONB
)
RETURNS SETOF deer_runtime.runtime_checkpoint_ref
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, deer_runtime
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_event deer_runtime.runtime_run_event%ROWTYPE;
    v_checkpoint deer_runtime.runtime_checkpoint_ref%ROWTYPE;
    v_sequence_no BIGINT;
    v_new_run_version BIGINT;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_run_id IS NULL OR p_event_id IS NULL
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_checkpoint_id IS NULL OR BTRIM(p_checkpoint_id) = ''
       OR LENGTH(p_checkpoint_id) > 160
       OR p_checkpoint_namespace IS NULL OR LENGTH(p_checkpoint_namespace) > 160
       OR p_checkpoint_schema_version IS NULL
       OR BTRIM(p_checkpoint_schema_version) = ''
       OR LENGTH(p_checkpoint_schema_version) > 64
       OR p_event_payload IS NULL OR JSONB_TYPEOF(p_event_payload) <> 'object'
       OR OCTET_LENGTH(p_event_payload::TEXT) > 65536 THEN
        RAISE EXCEPTION 'invalid runtime checkpoint arguments' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    v_now := CLOCK_TIMESTAMP();

    -- Recheck both stable identities after the Run lock so simultaneous
    -- retries converge on the committed Checkpoint fact instead of surfacing
    -- an incidental unique-constraint failure.
    SELECT * INTO v_checkpoint
      FROM deer_runtime.runtime_checkpoint_ref
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND checkpoint_id = p_checkpoint_id;
    IF FOUND THEN
        SELECT * INTO v_event
          FROM deer_runtime.runtime_run_event
         WHERE tenant_id = p_tenant_id
           AND runtime_run_id = p_runtime_run_id
           AND event_id = v_checkpoint.event_id;
        IF v_checkpoint.event_id = p_event_id
           AND v_checkpoint.checkpoint_namespace = p_checkpoint_namespace
           AND v_checkpoint.lease_epoch = p_lease_epoch
           AND v_checkpoint.checkpoint_schema_version = p_checkpoint_schema_version
           AND v_event.event_type = 'CHECKPOINT_SAVED'
           AND v_event.sequence_no = v_checkpoint.sequence_no
           AND v_event.run_version = v_checkpoint.run_version
           AND v_event.lease_owner = p_lease_owner
           AND v_event.lease_epoch = v_checkpoint.lease_epoch
           AND v_event.checkpoint_id = v_checkpoint.checkpoint_id
           AND v_event.payload = p_event_payload
           AND v_run.status IN ('RUNNING', 'WAITING_USER_INPUT', 'WAITING_AUTH')
           AND v_run.lease_owner = p_lease_owner
           AND v_run.lease_epoch = p_lease_epoch
           AND v_run.lease_until > v_now THEN
            RETURN NEXT v_checkpoint;
            RETURN;
        END IF;
        IF v_checkpoint.event_id = p_event_id
           AND v_checkpoint.checkpoint_namespace = p_checkpoint_namespace
           AND v_checkpoint.lease_epoch = p_lease_epoch
           AND v_checkpoint.checkpoint_schema_version = p_checkpoint_schema_version
           AND v_event.event_type = 'CHECKPOINT_SAVED'
           AND v_event.sequence_no = v_checkpoint.sequence_no
           AND v_event.run_version = v_checkpoint.run_version
           AND v_event.lease_epoch = v_checkpoint.lease_epoch
           AND v_event.checkpoint_id = v_checkpoint.checkpoint_id
           AND v_event.payload = p_event_payload THEN
            RETURN;
        END IF;
        RAISE EXCEPTION 'runtime checkpoint idempotency conflict'
            USING ERRCODE = '23505';
    END IF;

    IF EXISTS (
        SELECT 1 FROM deer_runtime.runtime_run_event
         WHERE tenant_id = p_tenant_id
           AND runtime_run_id = p_runtime_run_id
           AND event_id = p_event_id
    ) THEN
        RAISE EXCEPTION 'runtime checkpoint event idempotency conflict'
            USING ERRCODE = '23505';
    END IF;

    IF v_run.status NOT IN ('RUNNING', 'WAITING_USER_INPUT', 'WAITING_AUTH')
       OR v_run.lease_owner <> p_lease_owner
       OR v_run.lease_epoch <> p_lease_epoch
       OR v_run.lease_until <= v_now THEN
        RETURN;
    END IF;
    v_sequence_no := v_run.next_event_sequence_no;
    v_new_run_version := v_run.run_version + 1;

    INSERT INTO deer_runtime.runtime_run_event (
        tenant_id, runtime_run_id, runtime_thread_id, event_id, sequence_no,
        event_type, run_version, lease_owner, lease_epoch, checkpoint_id, payload,
        occurred_at, created_at
    ) VALUES (
        v_run.tenant_id, v_run.runtime_run_id, v_run.runtime_thread_id,
        p_event_id, v_sequence_no, 'CHECKPOINT_SAVED', v_new_run_version,
        p_lease_owner, p_lease_epoch, p_checkpoint_id, p_event_payload, v_now, v_now
    );

    INSERT INTO deer_runtime.runtime_checkpoint_ref (
        tenant_id, runtime_run_id, runtime_thread_id, checkpoint_id,
        checkpoint_namespace, sequence_no, event_id, run_version,
        lease_epoch, checkpoint_schema_version, created_at
    ) VALUES (
        v_run.tenant_id, v_run.runtime_run_id, v_run.runtime_thread_id,
        p_checkpoint_id, p_checkpoint_namespace, v_sequence_no, p_event_id,
        v_new_run_version, p_lease_epoch, p_checkpoint_schema_version, v_now
    ) RETURNING * INTO v_checkpoint;

    UPDATE deer_runtime.runtime_run
       SET current_checkpoint_id = p_checkpoint_id,
           current_checkpoint_sequence_no = v_sequence_no,
           next_event_sequence_no = v_sequence_no + 1,
           run_version = v_new_run_version,
           updated_at = v_now
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id;
    RETURN NEXT v_checkpoint;
END;
$function$;

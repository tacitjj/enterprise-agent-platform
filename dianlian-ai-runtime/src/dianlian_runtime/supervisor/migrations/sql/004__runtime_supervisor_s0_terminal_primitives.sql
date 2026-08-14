-- Purpose: add explicit cancel and terminal-state primitives for the dormant S0 Supervisor.
-- Scope: PostgreSQL 15+; only deer_runtime run, control and event facts are affected.
-- Preconditions: migrations 000-003 are current; worker calls carry the current lease fence.
-- Idempotency: every command uses a stable control/event ID and replays exact facts only.
-- Activation: no application component invokes these functions in this migration.
-- Rollback: deploy the previous runtime first; remove functions in a reviewed later migration.

CREATE FUNCTION deer_runtime.request_runtime_run_cancel(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_cancel_request_id UUID,
    p_actor_id UUID,
    p_reason_code VARCHAR,
    p_expected_run_version BIGINT,
    p_idempotency_key VARCHAR,
    p_request_hash CHAR(64),
    p_event_payload JSONB
)
RETURNS SETOF deer_runtime.runtime_run_control
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, deer_runtime
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_control deer_runtime.runtime_run_control%ROWTYPE;
    v_event deer_runtime.runtime_run_event%ROWTYPE;
    v_sequence_no BIGINT;
    v_new_run_version BIGINT;
    v_event_type VARCHAR(64);
    v_event_lease_owner VARCHAR(160);
    v_event_lease_epoch BIGINT;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_run_id IS NULL
       OR p_cancel_request_id IS NULL OR p_actor_id IS NULL
       OR p_reason_code IS NULL
       OR p_reason_code !~ '^[A-Z][A-Z0-9_]{0,63}$'
       OR p_expected_run_version IS NULL OR p_expected_run_version < 1
       OR p_idempotency_key IS NULL OR BTRIM(p_idempotency_key) = ''
       OR LENGTH(p_idempotency_key) > 200
       OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_event_payload IS NULL OR JSONB_TYPEOF(p_event_payload) <> 'object'
       OR OCTET_LENGTH(p_event_payload::TEXT) > 65536 THEN
        RAISE EXCEPTION 'invalid runtime cancel request arguments' USING ERRCODE = '22023';
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

    SELECT * INTO v_control
      FROM deer_runtime.runtime_run_control
     WHERE tenant_id = p_tenant_id
       AND control_id = p_cancel_request_id;
    IF NOT FOUND THEN
        SELECT * INTO v_control
          FROM deer_runtime.runtime_run_control
         WHERE tenant_id = p_tenant_id
           AND runtime_run_id = p_runtime_run_id
           AND idempotency_key = p_idempotency_key;
    END IF;
    IF FOUND THEN
        IF v_control.control_id <> p_cancel_request_id
           OR v_control.runtime_run_id <> p_runtime_run_id
           OR v_control.runtime_thread_id <> v_run.runtime_thread_id
           OR v_control.control_type <> 'CANCEL'
           OR v_control.actor_id <> p_actor_id
           OR v_control.reason_code <> p_reason_code
           OR v_control.expected_run_version <> p_expected_run_version
           OR v_control.idempotency_key <> p_idempotency_key
           OR v_control.request_hash <> p_request_hash THEN
            RAISE EXCEPTION 'runtime cancel request idempotency conflict'
                USING ERRCODE = '23505';
        END IF;

        SELECT * INTO v_event
          FROM deer_runtime.runtime_run_event
         WHERE tenant_id = p_tenant_id
           AND runtime_run_id = p_runtime_run_id
           AND event_id = p_cancel_request_id;
        IF NOT FOUND
           OR v_event.event_type NOT IN ('RUN_CANCEL_REQUESTED', 'RUN_CANCELLED')
           OR v_event.event_version <> 1
           OR v_event.run_version <> p_expected_run_version + 1
           OR v_event.checkpoint_id IS DISTINCT FROM v_run.current_checkpoint_id
           OR v_event.payload IS DISTINCT FROM p_event_payload THEN
            RAISE EXCEPTION 'runtime cancel request event idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        IF v_event.event_type = 'RUN_CANCELLED'
           AND (
               v_event.lease_owner IS NOT NULL
               OR v_event.lease_epoch <> 0
               OR v_run.status <> 'CANCELLED'
               OR v_run.terminal_event_id <> p_cancel_request_id
               OR v_run.terminal_reason <> p_reason_code
           ) THEN
            RAISE EXCEPTION 'runtime cancel request terminal conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN NEXT v_control;
        RETURN;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM deer_runtime.runtime_run_event
         WHERE tenant_id = p_tenant_id
           AND runtime_run_id = p_runtime_run_id
           AND event_id = p_cancel_request_id
    ) THEN
        RAISE EXCEPTION 'runtime cancel request event idempotency conflict'
            USING ERRCODE = '23505';
    END IF;
    IF v_run.run_version <> p_expected_run_version
       OR v_run.status NOT IN (
           'QUEUED', 'RUNNING', 'WAITING_USER_INPUT', 'WAITING_AUTH', 'PAUSED'
       ) THEN
        RETURN;
    END IF;

    v_sequence_no := v_run.next_event_sequence_no;
    v_new_run_version := v_run.run_version + 1;
    IF v_run.status = 'QUEUED' THEN
        v_event_type := 'RUN_CANCELLED';
        v_event_lease_owner := NULL;
        v_event_lease_epoch := 0;
        UPDATE deer_runtime.runtime_run
           SET status = 'CANCELLED',
               cancel_requested_at = v_now,
               terminal_reason = p_reason_code,
               terminal_event_id = p_cancel_request_id,
               failure_code = NULL,
               terminal_at = v_now,
               lease_owner = NULL,
               lease_until = NULL,
               heartbeat_at = NULL,
               next_event_sequence_no = v_sequence_no + 1,
               run_version = v_new_run_version,
               updated_at = v_now
         WHERE tenant_id = p_tenant_id
           AND runtime_run_id = p_runtime_run_id
           AND status = 'QUEUED'
           AND run_version = p_expected_run_version
        RETURNING * INTO v_run;
    ELSE
        v_event_type := 'RUN_CANCEL_REQUESTED';
        IF v_run.lease_owner IS NULL THEN
            v_event_lease_owner := NULL;
            v_event_lease_epoch := 0;
        ELSE
            v_event_lease_owner := v_run.lease_owner;
            v_event_lease_epoch := v_run.lease_epoch;
        END IF;
        UPDATE deer_runtime.runtime_run
           SET status = 'CANCEL_REQUESTED',
               cancel_requested_at = v_now,
               next_event_sequence_no = v_sequence_no + 1,
               run_version = v_new_run_version,
               updated_at = v_now
         WHERE tenant_id = p_tenant_id
           AND runtime_run_id = p_runtime_run_id
           AND status IN ('RUNNING', 'WAITING_USER_INPUT', 'WAITING_AUTH', 'PAUSED')
           AND run_version = p_expected_run_version
        RETURNING * INTO v_run;
    END IF;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    INSERT INTO deer_runtime.runtime_run_control (
        tenant_id, control_id, runtime_run_id, runtime_thread_id, control_type,
        actor_id, reason_code, expected_run_version, idempotency_key, request_hash,
        created_at
    ) VALUES (
        v_run.tenant_id, p_cancel_request_id, v_run.runtime_run_id,
        v_run.runtime_thread_id, 'CANCEL', p_actor_id, p_reason_code,
        p_expected_run_version, p_idempotency_key, p_request_hash, v_now
    ) RETURNING * INTO v_control;

    INSERT INTO deer_runtime.runtime_run_event (
        tenant_id, runtime_run_id, runtime_thread_id, event_id, sequence_no,
        event_type, run_version, lease_owner, lease_epoch, checkpoint_id, payload,
        occurred_at, created_at
    ) VALUES (
        v_run.tenant_id, v_run.runtime_run_id, v_run.runtime_thread_id,
        p_cancel_request_id, v_sequence_no, v_event_type, v_new_run_version,
        v_event_lease_owner, v_event_lease_epoch, v_run.current_checkpoint_id,
        p_event_payload, v_now, v_now
    );
    RETURN NEXT v_control;
END;
$function$;

CREATE FUNCTION deer_runtime.begin_runtime_run_cancellation(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_event_id UUID,
    p_event_payload JSONB
)
RETURNS SETOF deer_runtime.runtime_run
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, deer_runtime
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_event deer_runtime.runtime_run_event%ROWTYPE;
    v_sequence_no BIGINT;
    v_new_run_version BIGINT;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_run_id IS NULL OR p_event_id IS NULL
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_event_payload IS NULL OR JSONB_TYPEOF(p_event_payload) <> 'object'
       OR OCTET_LENGTH(p_event_payload::TEXT) > 65536 THEN
        RAISE EXCEPTION 'invalid runtime cancellation start arguments' USING ERRCODE = '22023';
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

    SELECT * INTO v_event
      FROM deer_runtime.runtime_run_event
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND event_id = p_event_id;
    IF FOUND THEN
        IF v_event.event_type <> 'RUN_CANCELLING'
           OR v_event.event_version <> 1
           OR v_event.checkpoint_id IS NOT NULL
           OR v_event.payload IS DISTINCT FROM p_event_payload THEN
            RAISE EXCEPTION 'runtime cancellation start idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        IF v_event.lease_owner <> p_lease_owner
           OR v_event.lease_epoch <> p_lease_epoch THEN
            RETURN;
        END IF;
        IF v_run.status = 'CANCELLING'
           AND v_run.lease_owner = p_lease_owner
           AND v_run.lease_epoch = p_lease_epoch
           AND v_run.lease_until > v_now THEN
            RETURN NEXT v_run;
        END IF;
        RETURN;
    END IF;

    IF v_run.status <> 'CANCEL_REQUESTED'
       OR v_run.lease_owner <> p_lease_owner
       OR v_run.lease_epoch <> p_lease_epoch
       OR v_run.lease_until <= v_now THEN
        RETURN;
    END IF;
    v_sequence_no := v_run.next_event_sequence_no;
    v_new_run_version := v_run.run_version + 1;

    UPDATE deer_runtime.runtime_run
       SET status = 'CANCELLING',
           next_event_sequence_no = v_sequence_no + 1,
           run_version = v_new_run_version,
           updated_at = v_now
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND status = 'CANCEL_REQUESTED'
       AND lease_owner = p_lease_owner
       AND lease_epoch = p_lease_epoch
       AND lease_until > v_now
    RETURNING * INTO v_run;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    INSERT INTO deer_runtime.runtime_run_event (
        tenant_id, runtime_run_id, runtime_thread_id, event_id, sequence_no,
        event_type, run_version, lease_owner, lease_epoch, payload,
        occurred_at, created_at
    ) VALUES (
        v_run.tenant_id, v_run.runtime_run_id, v_run.runtime_thread_id,
        p_event_id, v_sequence_no, 'RUN_CANCELLING', v_new_run_version,
        p_lease_owner, p_lease_epoch, p_event_payload, v_now, v_now
    );
    RETURN NEXT v_run;
END;
$function$;

CREATE FUNCTION deer_runtime.complete_runtime_run(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_event_id UUID,
    p_terminal_reason VARCHAR,
    p_event_payload JSONB
)
RETURNS SETOF deer_runtime.runtime_run
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, deer_runtime
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_event deer_runtime.runtime_run_event%ROWTYPE;
    v_sequence_no BIGINT;
    v_new_run_version BIGINT;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_run_id IS NULL OR p_event_id IS NULL
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_terminal_reason IS NULL
       OR p_terminal_reason !~ '^[A-Z][A-Z0-9_]{0,63}$'
       OR p_event_payload IS NULL OR JSONB_TYPEOF(p_event_payload) <> 'object'
       OR OCTET_LENGTH(p_event_payload::TEXT) > 65536 THEN
        RAISE EXCEPTION 'invalid runtime completion arguments' USING ERRCODE = '22023';
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

    SELECT * INTO v_event
      FROM deer_runtime.runtime_run_event
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND event_id = p_event_id;
    IF FOUND THEN
        IF v_event.event_type <> 'RUN_COMPLETED'
           OR v_event.event_version <> 1
           OR v_event.checkpoint_id IS DISTINCT FROM v_run.current_checkpoint_id
           OR v_event.payload IS DISTINCT FROM p_event_payload THEN
            RAISE EXCEPTION 'runtime completion idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        IF v_event.lease_owner <> p_lease_owner
           OR v_event.lease_epoch <> p_lease_epoch THEN
            RETURN;
        END IF;
        IF v_run.status = 'COMPLETED'
           AND v_run.terminal_event_id = p_event_id
           AND v_run.terminal_reason = p_terminal_reason
           AND v_run.failure_code IS NULL THEN
            RETURN NEXT v_run;
            RETURN;
        END IF;
        RAISE EXCEPTION 'runtime completion terminal conflict' USING ERRCODE = '23505';
    END IF;

    IF v_run.status <> 'RUNNING'
       OR v_run.lease_owner <> p_lease_owner
       OR v_run.lease_epoch <> p_lease_epoch
       OR v_run.lease_until <= v_now THEN
        RETURN;
    END IF;
    v_sequence_no := v_run.next_event_sequence_no;
    v_new_run_version := v_run.run_version + 1;

    UPDATE deer_runtime.runtime_run
       SET status = 'COMPLETED',
           terminal_reason = p_terminal_reason,
           terminal_event_id = p_event_id,
           failure_code = NULL,
           terminal_at = v_now,
           lease_owner = NULL,
           lease_until = NULL,
           heartbeat_at = NULL,
           next_event_sequence_no = v_sequence_no + 1,
           run_version = v_new_run_version,
           updated_at = v_now
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND status = 'RUNNING'
       AND lease_owner = p_lease_owner
       AND lease_epoch = p_lease_epoch
       AND lease_until > v_now
    RETURNING * INTO v_run;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    INSERT INTO deer_runtime.runtime_run_event (
        tenant_id, runtime_run_id, runtime_thread_id, event_id, sequence_no,
        event_type, run_version, lease_owner, lease_epoch, checkpoint_id, payload,
        occurred_at, created_at
    ) VALUES (
        v_run.tenant_id, v_run.runtime_run_id, v_run.runtime_thread_id,
        p_event_id, v_sequence_no, 'RUN_COMPLETED', v_new_run_version,
        p_lease_owner, p_lease_epoch, v_run.current_checkpoint_id,
        p_event_payload, v_now, v_now
    );
    RETURN NEXT v_run;
END;
$function$;

CREATE FUNCTION deer_runtime.fail_runtime_run(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_event_id UUID,
    p_terminal_reason VARCHAR,
    p_failure_code VARCHAR,
    p_event_payload JSONB
)
RETURNS SETOF deer_runtime.runtime_run
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, deer_runtime
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_event deer_runtime.runtime_run_event%ROWTYPE;
    v_sequence_no BIGINT;
    v_new_run_version BIGINT;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_run_id IS NULL OR p_event_id IS NULL
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_terminal_reason IS NULL
       OR p_terminal_reason !~ '^[A-Z][A-Z0-9_]{0,63}$'
       OR p_failure_code IS NULL
       OR p_failure_code !~ '^[A-Z][A-Z0-9_]{0,63}$'
       OR p_event_payload IS NULL OR JSONB_TYPEOF(p_event_payload) <> 'object'
       OR OCTET_LENGTH(p_event_payload::TEXT) > 65536 THEN
        RAISE EXCEPTION 'invalid runtime failure arguments' USING ERRCODE = '22023';
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

    SELECT * INTO v_event
      FROM deer_runtime.runtime_run_event
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND event_id = p_event_id;
    IF FOUND THEN
        IF v_event.event_type <> 'RUN_FAILED'
           OR v_event.event_version <> 1
           OR v_event.checkpoint_id IS DISTINCT FROM v_run.current_checkpoint_id
           OR v_event.payload IS DISTINCT FROM p_event_payload THEN
            RAISE EXCEPTION 'runtime failure idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        IF v_event.lease_owner <> p_lease_owner
           OR v_event.lease_epoch <> p_lease_epoch THEN
            RETURN;
        END IF;
        IF v_run.status = 'FAILED'
           AND v_run.terminal_event_id = p_event_id
           AND v_run.terminal_reason = p_terminal_reason
           AND v_run.failure_code = p_failure_code THEN
            RETURN NEXT v_run;
            RETURN;
        END IF;
        RAISE EXCEPTION 'runtime failure terminal conflict' USING ERRCODE = '23505';
    END IF;

    IF v_run.status <> 'RUNNING'
       OR v_run.lease_owner <> p_lease_owner
       OR v_run.lease_epoch <> p_lease_epoch
       OR v_run.lease_until <= v_now THEN
        RETURN;
    END IF;
    v_sequence_no := v_run.next_event_sequence_no;
    v_new_run_version := v_run.run_version + 1;

    UPDATE deer_runtime.runtime_run
       SET status = 'FAILED',
           terminal_reason = p_terminal_reason,
           terminal_event_id = p_event_id,
           failure_code = p_failure_code,
           terminal_at = v_now,
           lease_owner = NULL,
           lease_until = NULL,
           heartbeat_at = NULL,
           next_event_sequence_no = v_sequence_no + 1,
           run_version = v_new_run_version,
           updated_at = v_now
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND status = 'RUNNING'
       AND lease_owner = p_lease_owner
       AND lease_epoch = p_lease_epoch
       AND lease_until > v_now
    RETURNING * INTO v_run;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    INSERT INTO deer_runtime.runtime_run_event (
        tenant_id, runtime_run_id, runtime_thread_id, event_id, sequence_no,
        event_type, run_version, lease_owner, lease_epoch, checkpoint_id, payload,
        occurred_at, created_at
    ) VALUES (
        v_run.tenant_id, v_run.runtime_run_id, v_run.runtime_thread_id,
        p_event_id, v_sequence_no, 'RUN_FAILED', v_new_run_version,
        p_lease_owner, p_lease_epoch, v_run.current_checkpoint_id,
        p_event_payload, v_now, v_now
    );
    RETURN NEXT v_run;
END;
$function$;

CREATE FUNCTION deer_runtime.finish_runtime_run_cancellation(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_terminal_status VARCHAR,
    p_event_id UUID,
    p_terminal_reason VARCHAR,
    p_event_payload JSONB
)
RETURNS SETOF deer_runtime.runtime_run
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, deer_runtime
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_event deer_runtime.runtime_run_event%ROWTYPE;
    v_sequence_no BIGINT;
    v_new_run_version BIGINT;
    v_event_type VARCHAR(64);
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_run_id IS NULL OR p_event_id IS NULL
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_terminal_status NOT IN ('CANCELLED', 'CANCEL_OUTCOME_UNKNOWN')
       OR p_terminal_reason IS NULL
       OR p_terminal_reason !~ '^[A-Z][A-Z0-9_]{0,63}$'
       OR p_event_payload IS NULL OR JSONB_TYPEOF(p_event_payload) <> 'object'
       OR OCTET_LENGTH(p_event_payload::TEXT) > 65536 THEN
        RAISE EXCEPTION 'invalid runtime cancellation finish arguments' USING ERRCODE = '22023';
    END IF;
    v_event_type := CASE p_terminal_status
        WHEN 'CANCELLED' THEN 'RUN_CANCELLED'
        ELSE 'RUN_CANCEL_OUTCOME_UNKNOWN'
    END;

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    v_now := CLOCK_TIMESTAMP();

    SELECT * INTO v_event
      FROM deer_runtime.runtime_run_event
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND event_id = p_event_id;
    IF FOUND THEN
        IF v_event.event_type <> v_event_type
           OR v_event.event_version <> 1
           OR v_event.checkpoint_id IS DISTINCT FROM v_run.current_checkpoint_id
           OR v_event.payload IS DISTINCT FROM p_event_payload THEN
            RAISE EXCEPTION 'runtime cancellation finish idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        IF v_event.lease_owner <> p_lease_owner
           OR v_event.lease_epoch <> p_lease_epoch THEN
            RETURN;
        END IF;
        IF v_run.status = p_terminal_status
           AND v_run.terminal_event_id = p_event_id
           AND v_run.terminal_reason = p_terminal_reason
           AND v_run.failure_code IS NULL THEN
            RETURN NEXT v_run;
            RETURN;
        END IF;
        RAISE EXCEPTION 'runtime cancellation finish terminal conflict'
            USING ERRCODE = '23505';
    END IF;

    IF v_run.status <> 'CANCELLING'
       OR v_run.lease_owner <> p_lease_owner
       OR v_run.lease_epoch <> p_lease_epoch
       OR v_run.lease_until <= v_now THEN
        RETURN;
    END IF;
    v_sequence_no := v_run.next_event_sequence_no;
    v_new_run_version := v_run.run_version + 1;

    UPDATE deer_runtime.runtime_run
       SET status = p_terminal_status,
           terminal_reason = p_terminal_reason,
           terminal_event_id = p_event_id,
           failure_code = NULL,
           terminal_at = v_now,
           lease_owner = NULL,
           lease_until = NULL,
           heartbeat_at = NULL,
           next_event_sequence_no = v_sequence_no + 1,
           run_version = v_new_run_version,
           updated_at = v_now
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND status = 'CANCELLING'
       AND lease_owner = p_lease_owner
       AND lease_epoch = p_lease_epoch
       AND lease_until > v_now
    RETURNING * INTO v_run;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    INSERT INTO deer_runtime.runtime_run_event (
        tenant_id, runtime_run_id, runtime_thread_id, event_id, sequence_no,
        event_type, run_version, lease_owner, lease_epoch, checkpoint_id, payload,
        occurred_at, created_at
    ) VALUES (
        v_run.tenant_id, v_run.runtime_run_id, v_run.runtime_thread_id,
        p_event_id, v_sequence_no, v_event_type, v_new_run_version,
        p_lease_owner, p_lease_epoch, v_run.current_checkpoint_id,
        p_event_payload, v_now, v_now
    );
    RETURN NEXT v_run;
END;
$function$;

CREATE FUNCTION deer_runtime.validate_runtime_terminal_consistency()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, deer_runtime
AS $function$
DECLARE
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_event deer_runtime.runtime_run_event%ROWTYPE;
    v_expected_event_type VARCHAR(64);
    v_trigger_event_id UUID;
BEGIN
    IF TG_TABLE_NAME = 'runtime_run' THEN
        SELECT * INTO v_run
          FROM deer_runtime.runtime_run
         WHERE tenant_id = NEW.tenant_id
           AND runtime_run_id = NEW.runtime_run_id;
        v_trigger_event_id := NULL;
    ELSE
        SELECT * INTO v_run
          FROM deer_runtime.runtime_run
         WHERE tenant_id = NEW.tenant_id
           AND runtime_run_id = NEW.runtime_run_id;
        v_trigger_event_id := NULLIF(TO_JSONB(NEW) ->> 'event_id', '')::UUID;
    END IF;
    IF NOT FOUND OR v_run.status NOT IN (
        'COMPLETED', 'FAILED', 'CANCELLED', 'CANCEL_OUTCOME_UNKNOWN'
    ) THEN
        RETURN NULL;
    END IF;
    v_expected_event_type := CASE v_run.status
        WHEN 'COMPLETED' THEN 'RUN_COMPLETED'
        WHEN 'FAILED' THEN 'RUN_FAILED'
        WHEN 'CANCELLED' THEN 'RUN_CANCELLED'
        ELSE 'RUN_CANCEL_OUTCOME_UNKNOWN'
    END;
    SELECT * INTO v_event
      FROM deer_runtime.runtime_run_event
     WHERE tenant_id = v_run.tenant_id
       AND runtime_run_id = v_run.runtime_run_id
       AND event_id = v_run.terminal_event_id;
    IF NOT FOUND
       OR v_event.event_type <> v_expected_event_type
       OR v_event.event_version <> 1
       OR v_event.run_version <> v_run.run_version
       OR v_event.lease_epoch <> v_run.lease_epoch
       OR v_event.sequence_no <> v_run.next_event_sequence_no - 1
       OR v_event.checkpoint_id IS DISTINCT FROM v_run.current_checkpoint_id
       OR v_event.occurred_at IS DISTINCT FROM v_run.terminal_at
       OR (v_run.status = 'FAILED' AND v_run.failure_code IS NULL)
       OR (v_run.status <> 'FAILED' AND v_run.failure_code IS NOT NULL)
       OR (v_run.status IN ('CANCELLED', 'CANCEL_OUTCOME_UNKNOWN')
           AND v_run.cancel_requested_at IS NULL)
       OR (v_run.status IN ('COMPLETED', 'FAILED')
           AND v_run.cancel_requested_at IS NOT NULL) THEN
        RAISE EXCEPTION 'runtime terminal fact is inconsistent'
            USING ERRCODE = '55000';
    END IF;
    RETURN NULL;
END;
$function$;

CREATE CONSTRAINT TRIGGER trg_runtime_run_terminal_consistency
    AFTER INSERT OR UPDATE ON deer_runtime.runtime_run
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.validate_runtime_terminal_consistency();

CREATE CONSTRAINT TRIGGER trg_runtime_event_terminal_consistency
    AFTER INSERT ON deer_runtime.runtime_run_event
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.validate_runtime_terminal_consistency();

CREATE FUNCTION deer_runtime.reject_post_terminal_runtime_event()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, deer_runtime
AS $function$
DECLARE
    v_run deer_runtime.runtime_run%ROWTYPE;
BEGIN
    SELECT * INTO v_run
      FROM deer_runtime.runtime_run
     WHERE tenant_id = NEW.tenant_id
       AND runtime_run_id = NEW.runtime_run_id;
    IF FOUND
       AND v_run.status IN (
           'COMPLETED', 'FAILED', 'CANCELLED', 'CANCEL_OUTCOME_UNKNOWN'
       )
       AND NEW.event_id IS DISTINCT FROM v_run.terminal_event_id THEN
        RAISE EXCEPTION 'runtime terminal event must remain the final event'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE TRIGGER trg_runtime_event_reject_post_terminal
    BEFORE INSERT ON deer_runtime.runtime_run_event
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.reject_post_terminal_runtime_event();

CREATE FUNCTION deer_runtime.validate_runtime_cancel_control_consistency()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, deer_runtime
AS $function$
DECLARE
    v_event deer_runtime.runtime_run_event%ROWTYPE;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_event_found BOOLEAN;
BEGIN
    SELECT * INTO v_event
      FROM deer_runtime.runtime_run_event
     WHERE tenant_id = NEW.tenant_id
       AND runtime_run_id = NEW.runtime_run_id
       AND event_id = NEW.control_id;
    v_event_found := FOUND;
    SELECT * INTO v_run
      FROM deer_runtime.runtime_run
     WHERE tenant_id = NEW.tenant_id
       AND runtime_run_id = NEW.runtime_run_id;
    IF NOT FOUND OR NOT v_event_found
       OR NEW.control_type <> 'CANCEL'
       OR v_event.event_type NOT IN ('RUN_CANCEL_REQUESTED', 'RUN_CANCELLED')
       OR v_event.event_version <> 1
       OR v_event.run_version <> NEW.expected_run_version + 1
       OR v_event.checkpoint_id IS DISTINCT FROM v_run.current_checkpoint_id
       OR v_event.occurred_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'runtime cancel control fact is inconsistent'
            USING ERRCODE = '55000';
    END IF;
    RETURN NULL;
END;
$function$;

CREATE CONSTRAINT TRIGGER trg_runtime_cancel_control_consistency
    AFTER INSERT ON deer_runtime.runtime_run_control
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.validate_runtime_cancel_control_consistency();

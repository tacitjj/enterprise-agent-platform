-- Purpose: add the dormant S0 claim, heartbeat, takeover and authorization primitives.
-- Scope: PostgreSQL 15+; only deer_runtime functions and runtime_run/event rows are affected.
-- Preconditions: migrations 000 and 001 are current; callers use short transactions only.
-- Idempotency: claim/takeover replay their stable event ID; renew is monotonic and safe to repeat.
-- Activation: no application component invokes these functions in this migration.
-- Rollback: deploy the previous runtime first; remove functions in a reviewed later migration.

CREATE FUNCTION deer_runtime.claim_runtime_run(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_seconds INTEGER,
    p_started_event_id UUID,
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

CREATE FUNCTION deer_runtime.renew_runtime_run_lease(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_lease_seconds INTEGER
)
RETURNS SETOF deer_runtime.runtime_run
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, deer_runtime
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_run_id IS NULL
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_lease_seconds IS NULL OR p_lease_seconds < 5 OR p_lease_seconds > 3600 THEN
        RAISE EXCEPTION 'invalid runtime run lease renewal arguments' USING ERRCODE = '22023';
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
    IF v_run.lease_owner <> p_lease_owner
       OR v_run.lease_epoch <> p_lease_epoch
       OR v_run.lease_until <= v_now
       OR v_run.status NOT IN (
           'RUNNING', 'WAITING_USER_INPUT', 'WAITING_AUTH', 'PAUSED',
           'CANCEL_REQUESTED', 'CANCELLING'
       ) THEN
        RETURN;
    END IF;

    UPDATE deer_runtime.runtime_run
       SET lease_until = GREATEST(
               lease_until,
               v_now + MAKE_INTERVAL(secs => p_lease_seconds)
           ),
           heartbeat_at = v_now,
           updated_at = v_now
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND lease_owner = p_lease_owner
       AND lease_epoch = p_lease_epoch
       AND lease_until > v_now
       AND status IN (
           'RUNNING', 'WAITING_USER_INPUT', 'WAITING_AUTH', 'PAUSED',
           'CANCEL_REQUESTED', 'CANCELLING'
       )
    RETURNING * INTO v_run;
    IF FOUND THEN
        RETURN NEXT v_run;
    END IF;
END;
$function$;

CREATE FUNCTION deer_runtime.takeover_runtime_run(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_new_lease_owner VARCHAR,
    p_lease_seconds INTEGER,
    p_takeover_event_id UUID,
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

CREATE FUNCTION deer_runtime.authorize_runtime_run(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT
)
RETURNS SETOF deer_runtime.runtime_run
LANGUAGE sql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog, deer_runtime
AS $function$
    SELECT runtime_run.*
      FROM deer_runtime.runtime_run
     WHERE tenant_id = p_tenant_id
       AND runtime_run_id = p_runtime_run_id
       AND status = 'RUNNING'
       AND lease_owner = p_lease_owner
       AND lease_epoch = p_lease_epoch
       AND lease_until > CLOCK_TIMESTAMP()
$function$;

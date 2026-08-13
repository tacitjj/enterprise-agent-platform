-- Purpose: add a dormant, one-shot external dispatch and outcome barrier.
-- Scope: PostgreSQL 15+; only MODEL_INVOKE and TOOL_INVOKE Supervisor facts.
-- Preconditions: migrations 000-011 are current and all named cluster roles exist.
-- Idempotency: the migration ledger applies this immutable file once by checksum.
-- Activation: no worker, HTTP endpoint, Java client, model, or tool dispatch is enabled.
-- Rollback: deploy the previous runtime first; removal requires a reviewed later migration.

DO $precondition$
DECLARE
    v_dispatch_authorizer pg_catalog.pg_roles%ROWTYPE;
    v_reconciler pg_catalog.pg_roles%ROWTYPE;
BEGIN
    SELECT * INTO v_dispatch_authorizer
      FROM pg_catalog.pg_roles
     WHERE rolname = 'dianlian_supervisor_dispatch_authorizer';
    IF NOT FOUND
       OR v_dispatch_authorizer.rolcanlogin
       OR v_dispatch_authorizer.rolsuper
       OR v_dispatch_authorizer.rolcreatedb
       OR v_dispatch_authorizer.rolcreaterole
       OR v_dispatch_authorizer.rolinherit
       OR v_dispatch_authorizer.rolreplication
       OR v_dispatch_authorizer.rolbypassrls THEN
        RAISE EXCEPTION
            'dianlian_supervisor_dispatch_authorizer must be a restricted NOLOGIN NOINHERIT role'
            USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_auth_members
         WHERE member = v_dispatch_authorizer.oid
    ) THEN
        RAISE EXCEPTION
            'dianlian_supervisor_dispatch_authorizer must not inherit another role'
            USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_auth_members
         WHERE roleid = v_dispatch_authorizer.oid
           AND admin_option
    ) THEN
        RAISE EXCEPTION
            'dianlian_supervisor_dispatch_authorizer grants must not carry admin option'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_reconciler
      FROM pg_catalog.pg_roles
     WHERE rolname = 'dianlian_supervisor_outcome_reconciler';
    IF NOT FOUND
       OR v_reconciler.rolcanlogin
       OR v_reconciler.rolsuper
       OR v_reconciler.rolcreatedb
       OR v_reconciler.rolcreaterole
       OR v_reconciler.rolinherit
       OR v_reconciler.rolreplication
       OR v_reconciler.rolbypassrls THEN
        RAISE EXCEPTION
            'dianlian_supervisor_outcome_reconciler must be a restricted NOLOGIN NOINHERIT role'
            USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_auth_members
         WHERE member = v_reconciler.oid
    ) THEN
        RAISE EXCEPTION
            'dianlian_supervisor_outcome_reconciler must not inherit another role'
            USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_auth_members
         WHERE roleid = v_reconciler.oid
           AND admin_option
    ) THEN
        RAISE EXCEPTION
            'dianlian_supervisor_outcome_reconciler grants must not carry admin option'
            USING ERRCODE = '42501';
    END IF;
END;
$precondition$;

-- Prevent a concurrent legacy consume from crossing the compatibility check.
LOCK TABLE deer_runtime.runtime_external_permit_attempt
    IN SHARE ROW EXCLUSIVE MODE;

DO $legacy_consumed_precondition$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
         WHERE permit_attempt.operation_kind IN ('MODEL_INVOKE', 'TOOL_INVOKE')
           AND permit_attempt.status = 'CONSUMED'
    ) THEN
        RAISE EXCEPTION
            'consumed MODEL_INVOKE or TOOL_INVOKE permits must be reconciled before migration 012'
            USING ERRCODE = '55000';
    END IF;
END;
$legacy_consumed_precondition$;

REVOKE ALL PRIVILEGES ON SCHEMA deer_runtime
    FROM dianlian_supervisor_dispatch_authorizer,
         dianlian_supervisor_outcome_reconciler;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_dispatch_authorizer,
         dianlian_supervisor_outcome_reconciler;
DO $revoke_capability_column_privileges$
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
           AND relation.relkind IN ('r', 'p')
           AND attribute.attnum > 0
           AND NOT attribute.attisdropped
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL PRIVILEGES (%I) ON TABLE %I.%I FROM dianlian_supervisor_executor, dianlian_supervisor_permit_authorizer, dianlian_supervisor_dispatch_authorizer, dianlian_supervisor_outcome_reconciler',
            v_column.attname,
            v_column.nspname,
            v_column.relname
        );
    END LOOP;
END;
$revoke_capability_column_privileges$;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_dispatch_authorizer,
         dianlian_supervisor_outcome_reconciler;
SET LOCAL ROLE dianlian_supervisor_routine_owner;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA deer_runtime
    FROM dianlian_supervisor_dispatch_authorizer,
         dianlian_supervisor_outcome_reconciler;
RESET ROLE;

ALTER TABLE deer_runtime.runtime_external_permit_attempt
    ADD CONSTRAINT uq_runtime_external_permit_operation_binding UNIQUE
        (tenant_id, runtime_external_permit_id, runtime_run_id,
         operation_kind, intent_id, permit_attempt);

CREATE TABLE deer_runtime.runtime_external_operation_attempt
(
    tenant_id                    UUID         NOT NULL,
    runtime_external_permit_id   UUID         NOT NULL,
    runtime_run_id               UUID         NOT NULL,
    operation_kind               VARCHAR(32)  NOT NULL,
    intent_id                    UUID         NOT NULL,
    permit_attempt               INTEGER      NOT NULL CHECK (permit_attempt > 0),
    status                       VARCHAR(32)  NOT NULL CHECK (status IN (
        'DISPATCH_ARMED', 'NOT_DISPATCHED', 'SUCCEEDED',
        'FAILED_CONFIRMED', 'OUTCOME_UNKNOWN'
    )),
    arm_event_id                 UUID         NOT NULL,
    armed_by                     VARCHAR(160) NOT NULL CHECK (BTRIM(armed_by) <> ''),
    armed_at                     TIMESTAMPTZ  NOT NULL,
    last_event_id                UUID         NOT NULL,
    source_fact_id               UUID,
    source_fact_version          BIGINT,
    source_fact_hash             CHAR(64),
    outcome_code                 VARCHAR(64),
    evidence_kind                VARCHAR(64),
    result_hash                  CHAR(64),
    recorded_by                  VARCHAR(160),
    outcome_recorded_at          TIMESTAMPTZ,
    updated_at                   TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (tenant_id, runtime_external_permit_id),
    UNIQUE (runtime_external_permit_id),
    UNIQUE (arm_event_id),
    UNIQUE (tenant_id, runtime_run_id, operation_kind, intent_id),
    UNIQUE (tenant_id, runtime_external_permit_id, runtime_run_id,
            operation_kind, intent_id, permit_attempt),
    FOREIGN KEY (
        tenant_id, runtime_external_permit_id, runtime_run_id,
        operation_kind, intent_id, permit_attempt
    ) REFERENCES deer_runtime.runtime_external_permit_attempt (
        tenant_id, runtime_external_permit_id, runtime_run_id,
        operation_kind, intent_id, permit_attempt
    ),
    CHECK (operation_kind IN ('MODEL_INVOKE', 'TOOL_INVOKE')),
    CHECK (
        runtime_external_permit_id <> '00000000-0000-0000-0000-000000000000'::UUID
        AND runtime_run_id <> '00000000-0000-0000-0000-000000000000'::UUID
        AND intent_id <> '00000000-0000-0000-0000-000000000000'::UUID
        AND arm_event_id <> '00000000-0000-0000-0000-000000000000'::UUID
        AND last_event_id <> '00000000-0000-0000-0000-000000000000'::UUID
    ),
    CHECK (updated_at >= armed_at),
    CHECK (
        (status = 'DISPATCH_ARMED'
            AND last_event_id = arm_event_id
            AND source_fact_id IS NULL
            AND source_fact_version IS NULL
            AND source_fact_hash IS NULL
            AND outcome_code IS NULL
            AND evidence_kind IS NULL
            AND result_hash IS NULL
            AND recorded_by IS NULL
            AND outcome_recorded_at IS NULL)
        OR
        (status <> 'DISPATCH_ARMED'
            AND source_fact_id IS NOT NULL
            AND source_fact_id <> '00000000-0000-0000-0000-000000000000'::UUID
            AND source_fact_version > 0
            AND source_fact_hash ~ '^[0-9a-f]{64}$'
            AND outcome_code ~ '^[A-Z][A-Z0-9_]{0,63}$'
            AND evidence_kind = 'JAVA_CANONICAL_FACT'
            AND recorded_by IS NOT NULL
            AND BTRIM(recorded_by) <> ''
            AND outcome_recorded_at IS NOT NULL
            AND outcome_recorded_at >= armed_at
            AND updated_at >= outcome_recorded_at
            AND (
                (status IN ('SUCCEEDED', 'FAILED_CONFIRMED')
                    AND result_hash ~ '^[0-9a-f]{64}$')
                OR
                (status IN ('NOT_DISPATCHED', 'OUTCOME_UNKNOWN')
                    AND result_hash IS NULL)
            ))
    )
);

CREATE INDEX idx_runtime_external_operation_barrier
    ON deer_runtime.runtime_external_operation_attempt
        (tenant_id, runtime_run_id, status, armed_at)
    WHERE status IN ('DISPATCH_ARMED', 'OUTCOME_UNKNOWN');

CREATE TABLE deer_runtime.runtime_external_operation_event
(
    tenant_id                    UUID         NOT NULL,
    runtime_external_permit_id   UUID         NOT NULL,
    event_id                     UUID         NOT NULL,
    event_sequence               BIGINT       NOT NULL CHECK (event_sequence > 0),
    runtime_run_id               UUID         NOT NULL,
    operation_kind               VARCHAR(32)  NOT NULL,
    intent_id                    UUID         NOT NULL,
    permit_attempt               INTEGER      NOT NULL CHECK (permit_attempt > 0),
    event_type                   VARCHAR(32)  NOT NULL CHECK (event_type IN (
        'DISPATCH_ARMED', 'OUTCOME_RECORDED', 'OUTCOME_RECONCILED'
    )),
    from_status                  VARCHAR(32),
    to_status                    VARCHAR(32)  NOT NULL CHECK (to_status IN (
        'DISPATCH_ARMED', 'NOT_DISPATCHED', 'SUCCEEDED',
        'FAILED_CONFIRMED', 'OUTCOME_UNKNOWN'
    )),
    source_fact_id               UUID,
    source_fact_version          BIGINT,
    source_fact_hash             CHAR(64),
    outcome_code                 VARCHAR(64),
    evidence_kind                VARCHAR(64),
    result_hash                  CHAR(64),
    actor                        VARCHAR(160) NOT NULL CHECK (BTRIM(actor) <> ''),
    occurred_at                  TIMESTAMPTZ  NOT NULL,
    created_at                   TIMESTAMPTZ  NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    PRIMARY KEY (tenant_id, runtime_external_permit_id, event_id),
    UNIQUE (event_id),
    UNIQUE (tenant_id, runtime_external_permit_id, event_sequence),
    FOREIGN KEY (
        tenant_id, runtime_external_permit_id, runtime_run_id,
        operation_kind, intent_id, permit_attempt
    ) REFERENCES deer_runtime.runtime_external_operation_attempt (
        tenant_id, runtime_external_permit_id, runtime_run_id,
        operation_kind, intent_id, permit_attempt
    ),
    CHECK (event_id <> '00000000-0000-0000-0000-000000000000'::UUID),
    CHECK (operation_kind IN ('MODEL_INVOKE', 'TOOL_INVOKE')),
    CHECK (
        (event_type = 'DISPATCH_ARMED'
            AND event_sequence = 1
            AND from_status IS NULL
            AND to_status = 'DISPATCH_ARMED'
            AND source_fact_id IS NULL
            AND source_fact_version IS NULL
            AND source_fact_hash IS NULL
            AND outcome_code IS NULL
            AND evidence_kind IS NULL
            AND result_hash IS NULL)
        OR
        (event_type = 'OUTCOME_RECORDED'
            AND event_sequence = 2
            AND from_status = 'DISPATCH_ARMED'
            AND to_status IN (
                'NOT_DISPATCHED', 'SUCCEEDED',
                'FAILED_CONFIRMED', 'OUTCOME_UNKNOWN'
            )
            AND source_fact_id IS NOT NULL
            AND source_fact_version > 0
            AND source_fact_hash ~ '^[0-9a-f]{64}$'
            AND outcome_code ~ '^[A-Z][A-Z0-9_]{0,63}$'
            AND evidence_kind = 'JAVA_CANONICAL_FACT'
            AND (
                (to_status IN ('SUCCEEDED', 'FAILED_CONFIRMED')
                    AND result_hash ~ '^[0-9a-f]{64}$')
                OR
                (to_status IN ('NOT_DISPATCHED', 'OUTCOME_UNKNOWN')
                    AND result_hash IS NULL)
            ))
        OR
        (event_type = 'OUTCOME_RECONCILED'
            AND event_sequence = 3
            AND from_status = 'OUTCOME_UNKNOWN'
            AND to_status IN ('NOT_DISPATCHED', 'SUCCEEDED', 'FAILED_CONFIRMED')
            AND source_fact_id IS NOT NULL
            AND source_fact_version > 0
            AND source_fact_hash ~ '^[0-9a-f]{64}$'
            AND outcome_code ~ '^[A-Z][A-Z0-9_]{0,63}$'
            AND evidence_kind = 'JAVA_CANONICAL_FACT'
            AND (
                (to_status IN ('SUCCEEDED', 'FAILED_CONFIRMED')
                    AND result_hash ~ '^[0-9a-f]{64}$')
                OR
                (to_status = 'NOT_DISPATCHED' AND result_hash IS NULL)
            ))
    )
);

REVOKE ALL PRIVILEGES ON TABLE
    deer_runtime.runtime_external_operation_attempt,
    deer_runtime.runtime_external_operation_event
    FROM PUBLIC, dianlian_supervisor_executor,
         dianlian_supervisor_permit_authorizer,
         dianlian_supervisor_dispatch_authorizer,
         dianlian_supervisor_outcome_reconciler;

GRANT USAGE ON SCHEMA deer_runtime
    TO dianlian_supervisor_dispatch_authorizer,
       dianlian_supervisor_outcome_reconciler;
GRANT SELECT, INSERT ON TABLE deer_runtime.runtime_external_operation_attempt
    TO dianlian_supervisor_routine_owner;
GRANT UPDATE (
    status, last_event_id, source_fact_id, source_fact_version,
    source_fact_hash, outcome_code, evidence_kind, result_hash,
    recorded_by, outcome_recorded_at, updated_at
) ON TABLE deer_runtime.runtime_external_operation_attempt
    TO dianlian_supervisor_routine_owner;
GRANT SELECT, INSERT ON TABLE deer_runtime.runtime_external_operation_event
    TO dianlian_supervisor_routine_owner;
GRANT TRIGGER ON TABLE
    deer_runtime.runtime_external_operation_attempt,
    deer_runtime.runtime_external_operation_event
    TO dianlian_supervisor_routine_owner;
GRANT CREATE ON SCHEMA deer_runtime TO dianlian_supervisor_routine_owner;

SET LOCAL ROLE dianlian_supervisor_routine_owner;

CREATE FUNCTION deer_runtime.protect_runtime_external_operation_attempt()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'runtime_external_operation_attempt cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.runtime_external_permit_id IS DISTINCT FROM OLD.runtime_external_permit_id
       OR NEW.runtime_run_id IS DISTINCT FROM OLD.runtime_run_id
       OR NEW.operation_kind IS DISTINCT FROM OLD.operation_kind
       OR NEW.intent_id IS DISTINCT FROM OLD.intent_id
       OR NEW.permit_attempt IS DISTINCT FROM OLD.permit_attempt
       OR NEW.arm_event_id IS DISTINCT FROM OLD.arm_event_id
       OR NEW.armed_by IS DISTINCT FROM OLD.armed_by
       OR NEW.armed_at IS DISTINCT FROM OLD.armed_at
       OR NEW.updated_at IS NULL
       OR NEW.updated_at < OLD.updated_at
       OR (
           OLD.status = 'DISPATCH_ARMED'
           AND (
               NEW.status NOT IN (
                   'NOT_DISPATCHED', 'SUCCEEDED',
                   'FAILED_CONFIRMED', 'OUTCOME_UNKNOWN'
               )
               OR OLD.last_event_id IS DISTINCT FROM OLD.arm_event_id
               OR NEW.last_event_id IS NULL
               OR NEW.last_event_id = OLD.last_event_id
               OR NEW.source_fact_id IS NULL
               OR NEW.source_fact_version IS NULL
               OR NEW.source_fact_version < 1
               OR NEW.source_fact_hash IS NULL
               OR NEW.outcome_code IS NULL
               OR NEW.evidence_kind IS DISTINCT FROM 'JAVA_CANONICAL_FACT'
               OR NEW.recorded_by IS NULL
               OR NEW.outcome_recorded_at IS NULL
           )
       )
       OR (
           OLD.status = 'OUTCOME_UNKNOWN'
           AND (
               NEW.status NOT IN ('NOT_DISPATCHED', 'SUCCEEDED', 'FAILED_CONFIRMED')
               OR NEW.last_event_id IS NULL
               OR NEW.last_event_id = OLD.last_event_id
               OR NEW.source_fact_id IS DISTINCT FROM OLD.source_fact_id
               OR NEW.source_fact_version IS NULL
               OR NEW.source_fact_version <= OLD.source_fact_version
               OR NEW.source_fact_hash IS NULL
               OR NEW.outcome_code IS NULL
               OR NEW.evidence_kind IS DISTINCT FROM 'JAVA_CANONICAL_FACT'
               OR NEW.recorded_by IS NULL
               OR NEW.outcome_recorded_at IS NULL
               OR NEW.outcome_recorded_at < OLD.outcome_recorded_at
           )
       )
       OR OLD.status IN ('NOT_DISPATCHED', 'SUCCEEDED', 'FAILED_CONFIRMED') THEN
        RAISE EXCEPTION 'runtime_external_operation_attempt lifecycle mutation is invalid'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION deer_runtime.complete_runtime_run(
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
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
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
       OR v_run.lease_until <= v_now
       OR EXISTS (
           SELECT 1
             FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
            WHERE operation_attempt.tenant_id = p_tenant_id
              AND operation_attempt.runtime_run_id = p_runtime_run_id
              AND operation_attempt.status IN ('DISPATCH_ARMED', 'OUTCOME_UNKNOWN')
       ) THEN
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

CREATE OR REPLACE FUNCTION deer_runtime.fail_runtime_run(
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
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
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
       OR v_run.lease_until <= v_now
       OR (
           p_failure_code <> 'EXTERNAL_OUTCOME_UNKNOWN'
           AND EXISTS (
               SELECT 1
                 FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
                WHERE operation_attempt.tenant_id = p_tenant_id
                  AND operation_attempt.runtime_run_id = p_runtime_run_id
                  AND operation_attempt.status IN (
                      'DISPATCH_ARMED', 'OUTCOME_UNKNOWN'
                  )
           )
       ) THEN
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

CREATE OR REPLACE FUNCTION deer_runtime.finish_runtime_run_cancellation(
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
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
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
       OR v_run.lease_until <= v_now
       OR (
           p_terminal_status = 'CANCELLED'
           AND EXISTS (
               SELECT 1
                 FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
                WHERE operation_attempt.tenant_id = p_tenant_id
                  AND operation_attempt.runtime_run_id = p_runtime_run_id
                  AND operation_attempt.status IN (
                      'DISPATCH_ARMED', 'OUTCOME_UNKNOWN'
                  )
           )
       ) THEN
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

CREATE FUNCTION deer_runtime.record_runtime_external_operation_outcome(
    p_tenant_id UUID,
    p_runtime_external_permit_id UUID,
    p_runtime_run_id UUID,
    p_task_execution_generation BIGINT,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_admission_snapshot_id UUID,
    p_admission_snapshot_hash CHAR(64),
    p_operation_kind VARCHAR,
    p_intent_id UUID,
    p_request_hash CHAR(64),
    p_outcome_event_id UUID,
    p_outcome_status VARCHAR,
    p_source_fact_id UUID,
    p_source_fact_version BIGINT,
    p_source_fact_hash CHAR(64),
    p_outcome_code VARCHAR,
    p_evidence_kind VARCHAR,
    p_result_hash CHAR(64),
    p_recorded_by VARCHAR
)
RETURNS TABLE
(
    tenant_id UUID,
    runtime_external_permit_id UUID,
    runtime_run_id UUID,
    operation_kind VARCHAR(32),
    intent_id UUID,
    permit_attempt INTEGER,
    task_execution_generation BIGINT,
    admission_snapshot_id UUID,
    admission_snapshot_hash CHAR(64),
    request_hash CHAR(64),
    lease_owner VARCHAR(160),
    lease_epoch BIGINT,
    arm_event_id UUID,
    armed_by VARCHAR(160),
    armed_at TIMESTAMPTZ,
    status VARCHAR(32),
    last_event_id UUID,
    source_fact_id UUID,
    source_fact_version BIGINT,
    source_fact_hash CHAR(64),
    outcome_code VARCHAR(64),
    evidence_kind VARCHAR(64),
    result_hash CHAR(64),
    recorded_by VARCHAR(160),
    outcome_recorded_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_intent deer_runtime.runtime_external_intent%ROWTYPE;
    v_permit deer_runtime.runtime_external_permit_attempt%ROWTYPE;
    v_operation deer_runtime.runtime_external_operation_attempt%ROWTYPE;
    v_event deer_runtime.runtime_external_operation_event%ROWTYPE;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_external_permit_id IS NULL
       OR p_runtime_run_id IS NULL OR p_admission_snapshot_id IS NULL
       OR p_intent_id IS NULL OR p_outcome_event_id IS NULL
       OR p_source_fact_id IS NULL
       OR p_tenant_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_external_permit_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_run_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_admission_snapshot_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_intent_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_outcome_event_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_source_fact_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_task_execution_generation IS NULL OR p_task_execution_generation < 1
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_admission_snapshot_hash IS NULL
       OR p_admission_snapshot_hash !~ '^[0-9a-f]{64}$'
       OR p_operation_kind IS NULL
       OR p_operation_kind NOT IN ('MODEL_INVOKE', 'TOOL_INVOKE')
       OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_outcome_status IS NULL
       OR p_outcome_status NOT IN (
           'NOT_DISPATCHED', 'SUCCEEDED',
           'FAILED_CONFIRMED', 'OUTCOME_UNKNOWN'
       )
       OR p_source_fact_version IS NULL OR p_source_fact_version < 1
       OR p_source_fact_hash IS NULL
       OR p_source_fact_hash !~ '^[0-9a-f]{64}$'
       OR p_outcome_code IS NULL
       OR p_outcome_code !~ '^[A-Z][A-Z0-9_]{0,63}$'
       OR p_evidence_kind IS DISTINCT FROM 'JAVA_CANONICAL_FACT'
       OR p_recorded_by IS NULL OR BTRIM(p_recorded_by) = ''
       OR LENGTH(p_recorded_by) > 160
       OR (p_outcome_status IN ('SUCCEEDED', 'FAILED_CONFIRMED')
           AND (p_result_hash IS NULL OR p_result_hash !~ '^[0-9a-f]{64}$'))
       OR (p_outcome_status IN ('NOT_DISPATCHED', 'OUTCOME_UNKNOWN')
           AND p_result_hash IS NOT NULL) THEN
        RAISE EXCEPTION 'invalid runtime external operation outcome arguments'
            USING ERRCODE = '22023';
    END IF;

    -- Historical results still serialize through the Run, but they do not need
    -- the old lease to remain current after takeover or cancellation.
    SELECT * INTO v_run
      FROM deer_runtime.runtime_run AS runtime_run
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    SELECT * INTO v_permit
      FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
     WHERE permit_attempt.tenant_id = p_tenant_id
       AND permit_attempt.runtime_run_id = p_runtime_run_id
       AND permit_attempt.runtime_external_permit_id = p_runtime_external_permit_id
     FOR UPDATE;
    IF NOT FOUND THEN
        IF EXISTS (
            SELECT 1
              FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
             WHERE permit_attempt.runtime_external_permit_id =
                   p_runtime_external_permit_id
        ) THEN
            RAISE EXCEPTION 'runtime external operation outcome identity conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN;
    END IF;
    IF v_permit.tenant_id IS DISTINCT FROM p_tenant_id
       OR v_permit.runtime_run_id IS DISTINCT FROM p_runtime_run_id
       OR v_permit.operation_kind IS DISTINCT FROM p_operation_kind
       OR v_permit.intent_id IS DISTINCT FROM p_intent_id
       OR v_permit.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_permit.lease_epoch IS DISTINCT FROM p_lease_epoch
       OR v_permit.status IS DISTINCT FROM 'CONSUMED' THEN
        RAISE EXCEPTION 'runtime external operation outcome identity conflict'
            USING ERRCODE = '23505';
    END IF;

    SELECT * INTO v_operation
      FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
     WHERE operation_attempt.tenant_id = p_tenant_id
       AND operation_attempt.runtime_external_permit_id = p_runtime_external_permit_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT * INTO v_intent
      FROM deer_runtime.runtime_external_intent AS external_intent
     WHERE external_intent.tenant_id = p_tenant_id
       AND external_intent.runtime_run_id = p_runtime_run_id
       AND external_intent.operation_kind = p_operation_kind
       AND external_intent.intent_id = p_intent_id;
    IF NOT FOUND
       OR v_intent.task_execution_generation IS DISTINCT FROM p_task_execution_generation
       OR v_intent.admission_snapshot_id IS DISTINCT FROM p_admission_snapshot_id
       OR v_intent.admission_snapshot_hash IS DISTINCT FROM p_admission_snapshot_hash
       OR v_intent.request_hash IS DISTINCT FROM p_request_hash
       OR v_operation.runtime_run_id IS DISTINCT FROM p_runtime_run_id
       OR v_operation.operation_kind IS DISTINCT FROM p_operation_kind
       OR v_operation.intent_id IS DISTINCT FROM p_intent_id
       OR v_operation.permit_attempt IS DISTINCT FROM v_permit.permit_attempt THEN
        RAISE EXCEPTION 'runtime external operation outcome identity conflict'
            USING ERRCODE = '23505';
    END IF;

    SELECT * INTO v_event
      FROM deer_runtime.runtime_external_operation_event AS operation_event
     WHERE operation_event.event_id = p_outcome_event_id;
    IF FOUND THEN
        IF v_event.tenant_id IS DISTINCT FROM p_tenant_id
           OR v_event.runtime_external_permit_id IS DISTINCT FROM
               p_runtime_external_permit_id
           OR v_event.event_type IS DISTINCT FROM 'OUTCOME_RECORDED'
           OR v_event.from_status IS DISTINCT FROM 'DISPATCH_ARMED'
           OR v_event.to_status IS DISTINCT FROM p_outcome_status
           OR v_event.source_fact_id IS DISTINCT FROM p_source_fact_id
           OR v_event.source_fact_version IS DISTINCT FROM p_source_fact_version
           OR v_event.source_fact_hash IS DISTINCT FROM p_source_fact_hash
           OR v_event.outcome_code IS DISTINCT FROM p_outcome_code
           OR v_event.evidence_kind IS DISTINCT FROM p_evidence_kind
           OR v_event.result_hash IS DISTINCT FROM p_result_hash
           OR v_event.actor IS DISTINCT FROM p_recorded_by THEN
            RAISE EXCEPTION 'runtime external operation outcome idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY
        SELECT external_intent.tenant_id,
               operation_attempt.runtime_external_permit_id,
               external_intent.runtime_run_id,
               external_intent.operation_kind,
               external_intent.intent_id,
               operation_attempt.permit_attempt,
               external_intent.task_execution_generation,
               external_intent.admission_snapshot_id,
               external_intent.admission_snapshot_hash,
               external_intent.request_hash,
               permit_attempt.lease_owner,
               permit_attempt.lease_epoch,
               operation_attempt.arm_event_id,
               operation_attempt.armed_by,
               operation_attempt.armed_at,
               operation_attempt.status,
               operation_attempt.last_event_id,
               operation_attempt.source_fact_id,
               operation_attempt.source_fact_version,
               operation_attempt.source_fact_hash,
               operation_attempt.outcome_code,
               operation_attempt.evidence_kind,
               operation_attempt.result_hash,
               operation_attempt.recorded_by,
               operation_attempt.outcome_recorded_at,
               operation_attempt.updated_at
          FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
          JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
            USING (tenant_id, runtime_external_permit_id)
          JOIN deer_runtime.runtime_external_intent AS external_intent
            ON external_intent.tenant_id = operation_attempt.tenant_id
           AND external_intent.runtime_run_id = operation_attempt.runtime_run_id
           AND external_intent.operation_kind = operation_attempt.operation_kind
           AND external_intent.intent_id = operation_attempt.intent_id
         WHERE operation_attempt.tenant_id = v_operation.tenant_id
           AND operation_attempt.runtime_external_permit_id =
               v_operation.runtime_external_permit_id;
        RETURN;
    END IF;

    IF v_operation.status <> 'DISPATCH_ARMED' THEN
        RAISE EXCEPTION 'runtime external operation outcome state conflict'
            USING ERRCODE = '23505';
    END IF;
    v_now := CLOCK_TIMESTAMP();

    UPDATE deer_runtime.runtime_external_operation_attempt AS operation_attempt
       SET status = p_outcome_status,
           last_event_id = p_outcome_event_id,
           source_fact_id = p_source_fact_id,
           source_fact_version = p_source_fact_version,
           source_fact_hash = p_source_fact_hash,
           outcome_code = p_outcome_code,
           evidence_kind = p_evidence_kind,
           result_hash = p_result_hash,
           recorded_by = p_recorded_by,
           outcome_recorded_at = v_now,
           updated_at = v_now
     WHERE operation_attempt.tenant_id = p_tenant_id
       AND operation_attempt.runtime_external_permit_id = p_runtime_external_permit_id
       AND operation_attempt.status = 'DISPATCH_ARMED'
    RETURNING operation_attempt.* INTO v_operation;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'runtime external operation outcome state conflict'
            USING ERRCODE = '23505';
    END IF;

    INSERT INTO deer_runtime.runtime_external_operation_event (
        tenant_id, runtime_external_permit_id, event_id, event_sequence,
        runtime_run_id, operation_kind, intent_id, permit_attempt,
        event_type, from_status, to_status, source_fact_id,
        source_fact_version, source_fact_hash, outcome_code, evidence_kind,
        result_hash, actor, occurred_at, created_at
    ) VALUES (
        p_tenant_id, p_runtime_external_permit_id, p_outcome_event_id, 2,
        p_runtime_run_id, p_operation_kind, p_intent_id,
        v_operation.permit_attempt, 'OUTCOME_RECORDED', 'DISPATCH_ARMED',
        p_outcome_status, p_source_fact_id, p_source_fact_version,
        p_source_fact_hash, p_outcome_code, p_evidence_kind, p_result_hash,
        p_recorded_by, v_now, v_now
    );

    RETURN QUERY
    SELECT external_intent.tenant_id,
           operation_attempt.runtime_external_permit_id,
           external_intent.runtime_run_id,
           external_intent.operation_kind,
           external_intent.intent_id,
           operation_attempt.permit_attempt,
           external_intent.task_execution_generation,
           external_intent.admission_snapshot_id,
           external_intent.admission_snapshot_hash,
           external_intent.request_hash,
           permit_attempt.lease_owner,
           permit_attempt.lease_epoch,
           operation_attempt.arm_event_id,
           operation_attempt.armed_by,
           operation_attempt.armed_at,
           operation_attempt.status,
           operation_attempt.last_event_id,
           operation_attempt.source_fact_id,
           operation_attempt.source_fact_version,
           operation_attempt.source_fact_hash,
           operation_attempt.outcome_code,
           operation_attempt.evidence_kind,
           operation_attempt.result_hash,
           operation_attempt.recorded_by,
           operation_attempt.outcome_recorded_at,
           operation_attempt.updated_at
      FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
      JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
        USING (tenant_id, runtime_external_permit_id)
      JOIN deer_runtime.runtime_external_intent AS external_intent
        ON external_intent.tenant_id = operation_attempt.tenant_id
       AND external_intent.runtime_run_id = operation_attempt.runtime_run_id
       AND external_intent.operation_kind = operation_attempt.operation_kind
       AND external_intent.intent_id = operation_attempt.intent_id
     WHERE operation_attempt.tenant_id = v_operation.tenant_id
       AND operation_attempt.runtime_external_permit_id =
           v_operation.runtime_external_permit_id;
END;
$function$;

CREATE FUNCTION deer_runtime.reconcile_runtime_external_operation_outcome(
    p_tenant_id UUID,
    p_runtime_external_permit_id UUID,
    p_runtime_run_id UUID,
    p_task_execution_generation BIGINT,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_admission_snapshot_id UUID,
    p_admission_snapshot_hash CHAR(64),
    p_operation_kind VARCHAR,
    p_intent_id UUID,
    p_request_hash CHAR(64),
    p_expected_unknown_event_id UUID,
    p_reconcile_event_id UUID,
    p_outcome_status VARCHAR,
    p_source_fact_id UUID,
    p_source_fact_version BIGINT,
    p_source_fact_hash CHAR(64),
    p_outcome_code VARCHAR,
    p_evidence_kind VARCHAR,
    p_result_hash CHAR(64),
    p_recorded_by VARCHAR
)
RETURNS TABLE
(
    tenant_id UUID,
    runtime_external_permit_id UUID,
    runtime_run_id UUID,
    operation_kind VARCHAR(32),
    intent_id UUID,
    permit_attempt INTEGER,
    task_execution_generation BIGINT,
    admission_snapshot_id UUID,
    admission_snapshot_hash CHAR(64),
    request_hash CHAR(64),
    lease_owner VARCHAR(160),
    lease_epoch BIGINT,
    arm_event_id UUID,
    armed_by VARCHAR(160),
    armed_at TIMESTAMPTZ,
    status VARCHAR(32),
    last_event_id UUID,
    source_fact_id UUID,
    source_fact_version BIGINT,
    source_fact_hash CHAR(64),
    outcome_code VARCHAR(64),
    evidence_kind VARCHAR(64),
    result_hash CHAR(64),
    recorded_by VARCHAR(160),
    outcome_recorded_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_intent deer_runtime.runtime_external_intent%ROWTYPE;
    v_permit deer_runtime.runtime_external_permit_attempt%ROWTYPE;
    v_operation deer_runtime.runtime_external_operation_attempt%ROWTYPE;
    v_event deer_runtime.runtime_external_operation_event%ROWTYPE;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_external_permit_id IS NULL
       OR p_runtime_run_id IS NULL OR p_admission_snapshot_id IS NULL
       OR p_intent_id IS NULL OR p_expected_unknown_event_id IS NULL
       OR p_reconcile_event_id IS NULL OR p_source_fact_id IS NULL
       OR p_tenant_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_external_permit_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_run_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_admission_snapshot_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_intent_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_expected_unknown_event_id =
           '00000000-0000-0000-0000-000000000000'::UUID
       OR p_reconcile_event_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_source_fact_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_task_execution_generation IS NULL OR p_task_execution_generation < 1
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_admission_snapshot_hash IS NULL
       OR p_admission_snapshot_hash !~ '^[0-9a-f]{64}$'
       OR p_operation_kind IS NULL
       OR p_operation_kind NOT IN ('MODEL_INVOKE', 'TOOL_INVOKE')
       OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_outcome_status IS NULL
       OR p_outcome_status NOT IN ('NOT_DISPATCHED', 'SUCCEEDED', 'FAILED_CONFIRMED')
       OR p_source_fact_version IS NULL OR p_source_fact_version < 1
       OR p_source_fact_hash IS NULL
       OR p_source_fact_hash !~ '^[0-9a-f]{64}$'
       OR p_outcome_code IS NULL
       OR p_outcome_code !~ '^[A-Z][A-Z0-9_]{0,63}$'
       OR p_evidence_kind IS DISTINCT FROM 'JAVA_CANONICAL_FACT'
       OR p_recorded_by IS NULL OR BTRIM(p_recorded_by) = ''
       OR LENGTH(p_recorded_by) > 160
       OR (p_outcome_status IN ('SUCCEEDED', 'FAILED_CONFIRMED')
           AND (p_result_hash IS NULL OR p_result_hash !~ '^[0-9a-f]{64}$'))
       OR (p_outcome_status = 'NOT_DISPATCHED' AND p_result_hash IS NOT NULL) THEN
        RAISE EXCEPTION 'invalid runtime external operation reconcile arguments'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run AS runtime_run
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    SELECT * INTO v_permit
      FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
     WHERE permit_attempt.tenant_id = p_tenant_id
       AND permit_attempt.runtime_run_id = p_runtime_run_id
       AND permit_attempt.runtime_external_permit_id = p_runtime_external_permit_id
     FOR UPDATE;
    IF NOT FOUND THEN
        IF EXISTS (
            SELECT 1
              FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
             WHERE permit_attempt.runtime_external_permit_id =
                   p_runtime_external_permit_id
        ) THEN
            RAISE EXCEPTION 'runtime external operation reconcile identity conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN;
    END IF;
    IF v_permit.tenant_id IS DISTINCT FROM p_tenant_id
       OR v_permit.runtime_run_id IS DISTINCT FROM p_runtime_run_id
       OR v_permit.operation_kind IS DISTINCT FROM p_operation_kind
       OR v_permit.intent_id IS DISTINCT FROM p_intent_id
       OR v_permit.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_permit.lease_epoch IS DISTINCT FROM p_lease_epoch
       OR v_permit.status IS DISTINCT FROM 'CONSUMED' THEN
        RAISE EXCEPTION 'runtime external operation reconcile identity conflict'
            USING ERRCODE = '23505';
    END IF;

    SELECT * INTO v_operation
      FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
     WHERE operation_attempt.tenant_id = p_tenant_id
       AND operation_attempt.runtime_external_permit_id = p_runtime_external_permit_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT * INTO v_intent
      FROM deer_runtime.runtime_external_intent AS external_intent
     WHERE external_intent.tenant_id = p_tenant_id
       AND external_intent.runtime_run_id = p_runtime_run_id
       AND external_intent.operation_kind = p_operation_kind
       AND external_intent.intent_id = p_intent_id;
    IF NOT FOUND
       OR v_intent.task_execution_generation IS DISTINCT FROM p_task_execution_generation
       OR v_intent.admission_snapshot_id IS DISTINCT FROM p_admission_snapshot_id
       OR v_intent.admission_snapshot_hash IS DISTINCT FROM p_admission_snapshot_hash
       OR v_intent.request_hash IS DISTINCT FROM p_request_hash
       OR v_operation.runtime_run_id IS DISTINCT FROM p_runtime_run_id
       OR v_operation.operation_kind IS DISTINCT FROM p_operation_kind
       OR v_operation.intent_id IS DISTINCT FROM p_intent_id
       OR v_operation.permit_attempt IS DISTINCT FROM v_permit.permit_attempt THEN
        RAISE EXCEPTION 'runtime external operation reconcile identity conflict'
            USING ERRCODE = '23505';
    END IF;

    SELECT * INTO v_event
      FROM deer_runtime.runtime_external_operation_event AS operation_event
     WHERE operation_event.event_id = p_reconcile_event_id;
    IF FOUND THEN
        IF v_event.tenant_id IS DISTINCT FROM p_tenant_id
           OR v_event.runtime_external_permit_id IS DISTINCT FROM
               p_runtime_external_permit_id
           OR v_event.event_type IS DISTINCT FROM 'OUTCOME_RECONCILED'
           OR v_event.from_status IS DISTINCT FROM 'OUTCOME_UNKNOWN'
           OR v_event.to_status IS DISTINCT FROM p_outcome_status
           OR v_event.source_fact_id IS DISTINCT FROM p_source_fact_id
           OR v_event.source_fact_version IS DISTINCT FROM p_source_fact_version
           OR v_event.source_fact_hash IS DISTINCT FROM p_source_fact_hash
           OR v_event.outcome_code IS DISTINCT FROM p_outcome_code
           OR v_event.evidence_kind IS DISTINCT FROM p_evidence_kind
           OR v_event.result_hash IS DISTINCT FROM p_result_hash
           OR v_event.actor IS DISTINCT FROM p_recorded_by
           OR NOT EXISTS (
               SELECT 1
                 FROM deer_runtime.runtime_external_operation_event AS unknown_event
                WHERE unknown_event.tenant_id = p_tenant_id
                  AND unknown_event.runtime_external_permit_id =
                      p_runtime_external_permit_id
                  AND unknown_event.event_id = p_expected_unknown_event_id
                  AND unknown_event.event_sequence = 2
                  AND unknown_event.event_type = 'OUTCOME_RECORDED'
                  AND unknown_event.to_status = 'OUTCOME_UNKNOWN'
           ) THEN
            RAISE EXCEPTION 'runtime external operation reconcile idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY
        SELECT external_intent.tenant_id,
               operation_attempt.runtime_external_permit_id,
               external_intent.runtime_run_id,
               external_intent.operation_kind,
               external_intent.intent_id,
               operation_attempt.permit_attempt,
               external_intent.task_execution_generation,
               external_intent.admission_snapshot_id,
               external_intent.admission_snapshot_hash,
               external_intent.request_hash,
               permit_attempt.lease_owner,
               permit_attempt.lease_epoch,
               operation_attempt.arm_event_id,
               operation_attempt.armed_by,
               operation_attempt.armed_at,
               operation_attempt.status,
               operation_attempt.last_event_id,
               operation_attempt.source_fact_id,
               operation_attempt.source_fact_version,
               operation_attempt.source_fact_hash,
               operation_attempt.outcome_code,
               operation_attempt.evidence_kind,
               operation_attempt.result_hash,
               operation_attempt.recorded_by,
               operation_attempt.outcome_recorded_at,
               operation_attempt.updated_at
          FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
          JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
            USING (tenant_id, runtime_external_permit_id)
          JOIN deer_runtime.runtime_external_intent AS external_intent
            ON external_intent.tenant_id = operation_attempt.tenant_id
           AND external_intent.runtime_run_id = operation_attempt.runtime_run_id
           AND external_intent.operation_kind = operation_attempt.operation_kind
           AND external_intent.intent_id = operation_attempt.intent_id
         WHERE operation_attempt.tenant_id = v_operation.tenant_id
           AND operation_attempt.runtime_external_permit_id =
               v_operation.runtime_external_permit_id;
        RETURN;
    END IF;

    IF v_operation.status <> 'OUTCOME_UNKNOWN'
       OR v_operation.last_event_id IS DISTINCT FROM p_expected_unknown_event_id
       OR v_operation.source_fact_id IS DISTINCT FROM p_source_fact_id
       OR p_source_fact_version <= v_operation.source_fact_version THEN
        RAISE EXCEPTION 'runtime external operation reconcile state conflict'
            USING ERRCODE = '23505';
    END IF;
    v_now := CLOCK_TIMESTAMP();

    UPDATE deer_runtime.runtime_external_operation_attempt AS operation_attempt
       SET status = p_outcome_status,
           last_event_id = p_reconcile_event_id,
           source_fact_version = p_source_fact_version,
           source_fact_hash = p_source_fact_hash,
           outcome_code = p_outcome_code,
           evidence_kind = p_evidence_kind,
           result_hash = p_result_hash,
           recorded_by = p_recorded_by,
           outcome_recorded_at = v_now,
           updated_at = v_now
     WHERE operation_attempt.tenant_id = p_tenant_id
       AND operation_attempt.runtime_external_permit_id = p_runtime_external_permit_id
       AND operation_attempt.status = 'OUTCOME_UNKNOWN'
       AND operation_attempt.last_event_id = p_expected_unknown_event_id
       AND operation_attempt.source_fact_id = p_source_fact_id
       AND operation_attempt.source_fact_version < p_source_fact_version
    RETURNING operation_attempt.* INTO v_operation;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'runtime external operation reconcile state conflict'
            USING ERRCODE = '23505';
    END IF;

    INSERT INTO deer_runtime.runtime_external_operation_event (
        tenant_id, runtime_external_permit_id, event_id, event_sequence,
        runtime_run_id, operation_kind, intent_id, permit_attempt,
        event_type, from_status, to_status, source_fact_id,
        source_fact_version, source_fact_hash, outcome_code, evidence_kind,
        result_hash, actor, occurred_at, created_at
    ) VALUES (
        p_tenant_id, p_runtime_external_permit_id, p_reconcile_event_id, 3,
        p_runtime_run_id, p_operation_kind, p_intent_id,
        v_operation.permit_attempt, 'OUTCOME_RECONCILED', 'OUTCOME_UNKNOWN',
        p_outcome_status, p_source_fact_id, p_source_fact_version,
        p_source_fact_hash, p_outcome_code, p_evidence_kind, p_result_hash,
        p_recorded_by, v_now, v_now
    );

    RETURN QUERY
    SELECT external_intent.tenant_id,
           operation_attempt.runtime_external_permit_id,
           external_intent.runtime_run_id,
           external_intent.operation_kind,
           external_intent.intent_id,
           operation_attempt.permit_attempt,
           external_intent.task_execution_generation,
           external_intent.admission_snapshot_id,
           external_intent.admission_snapshot_hash,
           external_intent.request_hash,
           permit_attempt.lease_owner,
           permit_attempt.lease_epoch,
           operation_attempt.arm_event_id,
           operation_attempt.armed_by,
           operation_attempt.armed_at,
           operation_attempt.status,
           operation_attempt.last_event_id,
           operation_attempt.source_fact_id,
           operation_attempt.source_fact_version,
           operation_attempt.source_fact_hash,
           operation_attempt.outcome_code,
           operation_attempt.evidence_kind,
           operation_attempt.result_hash,
           operation_attempt.recorded_by,
           operation_attempt.outcome_recorded_at,
           operation_attempt.updated_at
      FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
      JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
        USING (tenant_id, runtime_external_permit_id)
      JOIN deer_runtime.runtime_external_intent AS external_intent
        ON external_intent.tenant_id = operation_attempt.tenant_id
       AND external_intent.runtime_run_id = operation_attempt.runtime_run_id
       AND external_intent.operation_kind = operation_attempt.operation_kind
       AND external_intent.intent_id = operation_attempt.intent_id
     WHERE operation_attempt.tenant_id = v_operation.tenant_id
       AND operation_attempt.runtime_external_permit_id =
           v_operation.runtime_external_permit_id;
END;
$function$;

CREATE FUNCTION deer_runtime.load_runtime_external_operation_barrier(
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
    lease_owner VARCHAR(160),
    lease_epoch BIGINT,
    dispatch_armed_count BIGINT,
    outcome_unknown_count BIGINT,
    blocking BOOLEAN,
    oldest_blocking_at TIMESTAMPTZ
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
DECLARE
    v_run deer_runtime.runtime_run%ROWTYPE;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_run_id IS NULL
       OR p_tenant_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_run_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_task_execution_generation IS NULL OR p_task_execution_generation < 1
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1 THEN
        RAISE EXCEPTION 'invalid runtime external operation barrier arguments'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run AS runtime_run
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND
       OR v_run.status NOT IN ('RUNNING', 'CANCEL_REQUESTED', 'CANCELLING')
       OR v_run.task_execution_generation IS DISTINCT FROM p_task_execution_generation
       OR v_run.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_run.lease_epoch IS DISTINCT FROM p_lease_epoch
       OR v_run.lease_until IS NULL
       OR v_run.lease_until <= CLOCK_TIMESTAMP() THEN
        RETURN;
    END IF;

    RETURN QUERY
    SELECT v_run.tenant_id,
           v_run.runtime_run_id,
           v_run.task_execution_generation,
           v_run.lease_owner,
           v_run.lease_epoch,
           COUNT(*) FILTER (WHERE operation_attempt.status = 'DISPATCH_ARMED')::BIGINT,
           COUNT(*) FILTER (WHERE operation_attempt.status = 'OUTCOME_UNKNOWN')::BIGINT,
           COUNT(*) FILTER (
               WHERE operation_attempt.status IN ('DISPATCH_ARMED', 'OUTCOME_UNKNOWN')
           ) > 0,
           MIN(operation_attempt.armed_at) FILTER (
               WHERE operation_attempt.status IN ('DISPATCH_ARMED', 'OUTCOME_UNKNOWN')
           )
      FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
     WHERE operation_attempt.tenant_id = p_tenant_id
       AND operation_attempt.runtime_run_id = p_runtime_run_id;
END;
$function$;

REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.protect_runtime_external_operation_attempt()
    FROM PUBLIC, dianlian_supervisor_executor,
         dianlian_supervisor_permit_authorizer,
         dianlian_supervisor_dispatch_authorizer,
         dianlian_supervisor_outcome_reconciler;

CREATE TRIGGER trg_runtime_external_operation_attempt_lifecycle
    BEFORE UPDATE OR DELETE ON deer_runtime.runtime_external_operation_attempt
    FOR EACH ROW EXECUTE FUNCTION
        deer_runtime.protect_runtime_external_operation_attempt();
CREATE TRIGGER trg_runtime_external_operation_attempt_no_truncate
    BEFORE TRUNCATE ON deer_runtime.runtime_external_operation_attempt
    FOR EACH STATEMENT EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();
CREATE TRIGGER trg_runtime_external_operation_event_append_only
    BEFORE UPDATE OR DELETE ON deer_runtime.runtime_external_operation_event
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();
CREATE TRIGGER trg_runtime_external_operation_event_no_truncate
    BEFORE TRUNCATE ON deer_runtime.runtime_external_operation_event
    FOR EACH STATEMENT EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

-- Migration 012 reserves the old wrapper for admission resolution. Model and
-- tool operations must pass through consume_and_arm_runtime_external_dispatch.
CREATE OR REPLACE FUNCTION deer_runtime.consume_and_authorize_runtime_external_permit(
    p_tenant_id UUID,
    p_runtime_external_permit_id UUID,
    p_runtime_run_id UUID,
    p_task_execution_generation BIGINT,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_admission_snapshot_id UUID,
    p_admission_snapshot_hash CHAR(64),
    p_operation_kind VARCHAR,
    p_intent_id UUID,
    p_request_hash CHAR(64),
    p_consume_event_id UUID,
    p_consumed_by VARCHAR
)
RETURNS TABLE
(
    tenant_id UUID,
    runtime_external_permit_id UUID,
    runtime_run_id UUID,
    runtime_thread_id UUID,
    task_step_id UUID,
    task_execution_generation BIGINT,
    admission_contract_version VARCHAR(8),
    admission_snapshot_id UUID,
    admission_snapshot_hash CHAR(64),
    operation_kind VARCHAR(32),
    intent_id UUID,
    request_hash CHAR(64),
    lease_owner VARCHAR(160),
    lease_epoch BIGINT,
    permit_attempt INTEGER,
    status VARCHAR(16),
    requested_ttl_seconds INTEGER,
    issued_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    issue_event_id UUID,
    consume_event_id UUID,
    consumed_by VARCHAR(160),
    consumed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_external_permit_id IS NULL
       OR p_runtime_run_id IS NULL OR p_admission_snapshot_id IS NULL
       OR p_intent_id IS NULL OR p_consume_event_id IS NULL
       OR p_tenant_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_external_permit_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_run_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_admission_snapshot_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_intent_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_consume_event_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_task_execution_generation IS NULL OR p_task_execution_generation < 1
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_admission_snapshot_hash IS NULL
       OR p_admission_snapshot_hash !~ '^[0-9a-f]{64}$'
       OR p_operation_kind IS DISTINCT FROM 'ADMISSION_RESOLVE'
       OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_consumed_by IS NULL OR BTRIM(p_consumed_by) = ''
       OR LENGTH(p_consumed_by) > 160 THEN
        RAISE EXCEPTION 'invalid runtime external permit consume and authorize arguments'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run AS runtime_run
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    v_now := CLOCK_TIMESTAMP();

    IF v_run.status <> 'RUNNING'
       OR v_run.task_execution_generation IS DISTINCT FROM p_task_execution_generation
       OR v_run.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_run.lease_epoch IS DISTINCT FROM p_lease_epoch
       OR v_run.lease_until IS NULL OR v_run.lease_until <= v_now THEN
        RETURN;
    END IF;

    RETURN QUERY
    SELECT consumed.*
      FROM deer_runtime.consume_runtime_external_permit(
          p_tenant_id, p_runtime_external_permit_id, p_runtime_run_id,
          p_task_execution_generation, p_lease_owner, p_lease_epoch,
          p_admission_snapshot_id, p_admission_snapshot_hash,
          p_operation_kind, p_intent_id, p_request_hash,
          p_consume_event_id, p_consumed_by
      ) AS consumed;
END;
$function$;

CREATE FUNCTION deer_runtime.consume_and_arm_runtime_external_dispatch(
    p_tenant_id UUID,
    p_runtime_external_permit_id UUID,
    p_runtime_run_id UUID,
    p_task_execution_generation BIGINT,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_admission_snapshot_id UUID,
    p_admission_snapshot_hash CHAR(64),
    p_operation_kind VARCHAR,
    p_intent_id UUID,
    p_request_hash CHAR(64),
    p_arm_event_id UUID,
    p_armed_by VARCHAR
)
RETURNS TABLE
(
    dispatch_decision VARCHAR(24),
    tenant_id UUID,
    runtime_external_permit_id UUID,
    runtime_run_id UUID,
    operation_kind VARCHAR(32),
    intent_id UUID,
    permit_attempt INTEGER,
    task_execution_generation BIGINT,
    admission_snapshot_id UUID,
    admission_snapshot_hash CHAR(64),
    request_hash CHAR(64),
    lease_owner VARCHAR(160),
    lease_epoch BIGINT,
    arm_event_id UUID,
    armed_by VARCHAR(160),
    armed_at TIMESTAMPTZ,
    status VARCHAR(32),
    last_event_id UUID,
    source_fact_id UUID,
    source_fact_version BIGINT,
    source_fact_hash CHAR(64),
    outcome_code VARCHAR(64),
    evidence_kind VARCHAR(64),
    result_hash CHAR(64),
    recorded_by VARCHAR(160),
    outcome_recorded_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
DECLARE
    v_now TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_intent deer_runtime.runtime_external_intent%ROWTYPE;
    v_permit deer_runtime.runtime_external_permit_attempt%ROWTYPE;
    v_operation deer_runtime.runtime_external_operation_attempt%ROWTYPE;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_external_permit_id IS NULL
       OR p_runtime_run_id IS NULL OR p_admission_snapshot_id IS NULL
       OR p_intent_id IS NULL OR p_arm_event_id IS NULL
       OR p_tenant_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_external_permit_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_run_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_admission_snapshot_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_intent_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_arm_event_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_task_execution_generation IS NULL OR p_task_execution_generation < 1
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_admission_snapshot_hash IS NULL
       OR p_admission_snapshot_hash !~ '^[0-9a-f]{64}$'
       OR p_operation_kind IS NULL
       OR p_operation_kind NOT IN ('MODEL_INVOKE', 'TOOL_INVOKE')
       OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_armed_by IS NULL OR BTRIM(p_armed_by) = ''
       OR LENGTH(p_armed_by) > 160 THEN
        RAISE EXCEPTION 'invalid runtime external dispatch arm arguments'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run AS runtime_run
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    SELECT * INTO v_permit
      FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
     WHERE permit_attempt.tenant_id = p_tenant_id
       AND permit_attempt.runtime_run_id = p_runtime_run_id
       AND permit_attempt.runtime_external_permit_id = p_runtime_external_permit_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    SELECT * INTO v_operation
      FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
     WHERE operation_attempt.tenant_id = p_tenant_id
       AND operation_attempt.runtime_run_id = p_runtime_run_id
       AND operation_attempt.runtime_external_permit_id = p_runtime_external_permit_id
     FOR UPDATE;
    IF FOUND THEN
        SELECT * INTO v_intent
          FROM deer_runtime.runtime_external_intent AS external_intent
         WHERE external_intent.tenant_id = v_operation.tenant_id
           AND external_intent.runtime_run_id = v_operation.runtime_run_id
           AND external_intent.operation_kind = v_operation.operation_kind
           AND external_intent.intent_id = v_operation.intent_id;
        IF v_operation.runtime_run_id IS DISTINCT FROM p_runtime_run_id
           OR v_operation.operation_kind IS DISTINCT FROM p_operation_kind
           OR v_operation.intent_id IS DISTINCT FROM p_intent_id
           OR v_operation.arm_event_id IS DISTINCT FROM p_arm_event_id
           OR v_operation.armed_by IS DISTINCT FROM p_armed_by
           OR v_intent.task_execution_generation IS DISTINCT FROM p_task_execution_generation
           OR v_intent.admission_snapshot_id IS DISTINCT FROM p_admission_snapshot_id
           OR v_intent.admission_snapshot_hash IS DISTINCT FROM p_admission_snapshot_hash
           OR v_intent.request_hash IS DISTINCT FROM p_request_hash
           OR v_permit.lease_owner IS DISTINCT FROM p_lease_owner
           OR v_permit.lease_epoch IS DISTINCT FROM p_lease_epoch
           OR v_permit.consume_event_id IS DISTINCT FROM p_arm_event_id
           OR v_permit.consumed_by IS DISTINCT FROM p_armed_by THEN
            RAISE EXCEPTION 'runtime external dispatch arm idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY
        SELECT 'DO_NOT_DISPATCH'::VARCHAR(24),
               external_intent.tenant_id,
               operation_attempt.runtime_external_permit_id,
               external_intent.runtime_run_id,
               external_intent.operation_kind,
               external_intent.intent_id,
               operation_attempt.permit_attempt,
               external_intent.task_execution_generation,
               external_intent.admission_snapshot_id,
               external_intent.admission_snapshot_hash,
               external_intent.request_hash,
               permit_attempt.lease_owner,
               permit_attempt.lease_epoch,
               operation_attempt.arm_event_id,
               operation_attempt.armed_by,
               operation_attempt.armed_at,
               operation_attempt.status,
               operation_attempt.last_event_id,
               operation_attempt.source_fact_id,
               operation_attempt.source_fact_version,
               operation_attempt.source_fact_hash,
               operation_attempt.outcome_code,
               operation_attempt.evidence_kind,
               operation_attempt.result_hash,
               operation_attempt.recorded_by,
               operation_attempt.outcome_recorded_at,
               operation_attempt.updated_at
          FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
          JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
            USING (tenant_id, runtime_external_permit_id)
          JOIN deer_runtime.runtime_external_intent AS external_intent
            ON external_intent.tenant_id = operation_attempt.tenant_id
           AND external_intent.runtime_run_id = operation_attempt.runtime_run_id
           AND external_intent.operation_kind = operation_attempt.operation_kind
           AND external_intent.intent_id = operation_attempt.intent_id
         WHERE operation_attempt.tenant_id = v_operation.tenant_id
           AND operation_attempt.runtime_external_permit_id =
               v_operation.runtime_external_permit_id;
        RETURN;
    END IF;

    v_now := CLOCK_TIMESTAMP();
    IF v_run.status <> 'RUNNING'
       OR v_run.task_execution_generation IS DISTINCT FROM p_task_execution_generation
       OR v_run.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_run.lease_epoch IS DISTINCT FROM p_lease_epoch
       OR v_run.lease_until IS NULL OR v_run.lease_until <= v_now
       OR EXISTS (
           SELECT 1
             FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
            WHERE operation_attempt.tenant_id = p_tenant_id
              AND operation_attempt.runtime_run_id = p_runtime_run_id
              AND operation_attempt.status IN ('DISPATCH_ARMED', 'OUTCOME_UNKNOWN')
       ) THEN
        RETURN;
    END IF;

    PERFORM 1
      FROM deer_runtime.consume_runtime_external_permit(
          p_tenant_id, p_runtime_external_permit_id, p_runtime_run_id,
          p_task_execution_generation, p_lease_owner, p_lease_epoch,
          p_admission_snapshot_id, p_admission_snapshot_hash,
          p_operation_kind, p_intent_id, p_request_hash,
          p_arm_event_id, p_armed_by
      ) AS consumed;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    SELECT * INTO v_permit
      FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
     WHERE permit_attempt.tenant_id = p_tenant_id
       AND permit_attempt.runtime_run_id = p_runtime_run_id
       AND permit_attempt.runtime_external_permit_id = p_runtime_external_permit_id;

    INSERT INTO deer_runtime.runtime_external_operation_attempt (
        tenant_id, runtime_external_permit_id, runtime_run_id,
        operation_kind, intent_id, permit_attempt, status,
        arm_event_id, armed_by, armed_at, last_event_id,
        source_fact_id, source_fact_version, source_fact_hash,
        outcome_code, evidence_kind, result_hash, recorded_by,
        outcome_recorded_at, updated_at
    ) VALUES (
        p_tenant_id, p_runtime_external_permit_id, p_runtime_run_id,
        p_operation_kind, p_intent_id, v_permit.permit_attempt,
        'DISPATCH_ARMED', p_arm_event_id, p_armed_by, v_permit.consumed_at,
        p_arm_event_id, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
        v_permit.consumed_at
    ) RETURNING * INTO v_operation;

    INSERT INTO deer_runtime.runtime_external_operation_event (
        tenant_id, runtime_external_permit_id, event_id, event_sequence,
        runtime_run_id, operation_kind, intent_id, permit_attempt,
        event_type, from_status, to_status, source_fact_id,
        source_fact_version, source_fact_hash, outcome_code, evidence_kind,
        result_hash, actor, occurred_at, created_at
    ) VALUES (
        p_tenant_id, p_runtime_external_permit_id, p_arm_event_id, 1,
        p_runtime_run_id, p_operation_kind, p_intent_id,
        v_permit.permit_attempt, 'DISPATCH_ARMED', NULL, 'DISPATCH_ARMED',
        NULL, NULL, NULL, NULL, NULL, NULL, p_armed_by,
        v_permit.consumed_at, v_permit.consumed_at
    );

    RETURN QUERY
    SELECT 'GRANTED_NOW'::VARCHAR(24),
           external_intent.tenant_id,
           operation_attempt.runtime_external_permit_id,
           external_intent.runtime_run_id,
           external_intent.operation_kind,
           external_intent.intent_id,
           operation_attempt.permit_attempt,
           external_intent.task_execution_generation,
           external_intent.admission_snapshot_id,
           external_intent.admission_snapshot_hash,
           external_intent.request_hash,
           permit_attempt.lease_owner,
           permit_attempt.lease_epoch,
           operation_attempt.arm_event_id,
           operation_attempt.armed_by,
           operation_attempt.armed_at,
           operation_attempt.status,
           operation_attempt.last_event_id,
           operation_attempt.source_fact_id,
           operation_attempt.source_fact_version,
           operation_attempt.source_fact_hash,
           operation_attempt.outcome_code,
           operation_attempt.evidence_kind,
           operation_attempt.result_hash,
           operation_attempt.recorded_by,
           operation_attempt.outcome_recorded_at,
           operation_attempt.updated_at
      FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt
      JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
        USING (tenant_id, runtime_external_permit_id)
      JOIN deer_runtime.runtime_external_intent AS external_intent
        ON external_intent.tenant_id = operation_attempt.tenant_id
       AND external_intent.runtime_run_id = operation_attempt.runtime_run_id
       AND external_intent.operation_kind = operation_attempt.operation_kind
       AND external_intent.intent_id = operation_attempt.intent_id
     WHERE operation_attempt.tenant_id = v_operation.tenant_id
       AND operation_attempt.runtime_external_permit_id =
           v_operation.runtime_external_permit_id;
END;
$function$;

REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.consume_runtime_external_permit(
        UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
        VARCHAR, UUID, CHAR(64), UUID, VARCHAR
    )
    FROM PUBLIC, dianlian_supervisor_executor,
         dianlian_supervisor_permit_authorizer,
         dianlian_supervisor_dispatch_authorizer,
         dianlian_supervisor_outcome_reconciler;
REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.consume_and_authorize_runtime_external_permit(
        UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
        VARCHAR, UUID, CHAR(64), UUID, VARCHAR
    )
    FROM PUBLIC, dianlian_supervisor_executor,
         dianlian_supervisor_permit_authorizer,
         dianlian_supervisor_dispatch_authorizer,
         dianlian_supervisor_outcome_reconciler;
REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.consume_and_arm_runtime_external_dispatch(
        UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
        VARCHAR, UUID, CHAR(64), UUID, VARCHAR
    )
    FROM PUBLIC, dianlian_supervisor_executor,
         dianlian_supervisor_permit_authorizer,
         dianlian_supervisor_dispatch_authorizer,
         dianlian_supervisor_outcome_reconciler;
REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.record_runtime_external_operation_outcome(
        UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
        VARCHAR, UUID, CHAR(64), UUID, VARCHAR, UUID, BIGINT, CHAR(64),
        VARCHAR, VARCHAR, CHAR(64), VARCHAR
    )
    FROM PUBLIC, dianlian_supervisor_executor,
         dianlian_supervisor_permit_authorizer,
         dianlian_supervisor_dispatch_authorizer,
         dianlian_supervisor_outcome_reconciler;
REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.reconcile_runtime_external_operation_outcome(
        UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
        VARCHAR, UUID, CHAR(64), UUID, UUID, VARCHAR, UUID, BIGINT,
        CHAR(64), VARCHAR, VARCHAR, CHAR(64), VARCHAR
    )
    FROM PUBLIC, dianlian_supervisor_executor,
         dianlian_supervisor_permit_authorizer,
         dianlian_supervisor_dispatch_authorizer,
         dianlian_supervisor_outcome_reconciler;
REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.load_runtime_external_operation_barrier(
        UUID, UUID, BIGINT, VARCHAR, BIGINT
    )
    FROM PUBLIC, dianlian_supervisor_executor,
         dianlian_supervisor_permit_authorizer,
         dianlian_supervisor_dispatch_authorizer,
         dianlian_supervisor_outcome_reconciler;

GRANT EXECUTE ON FUNCTION
    deer_runtime.consume_and_authorize_runtime_external_permit(
        UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
        VARCHAR, UUID, CHAR(64), UUID, VARCHAR
    ) TO dianlian_supervisor_permit_authorizer;
GRANT EXECUTE ON FUNCTION
    deer_runtime.consume_and_arm_runtime_external_dispatch(
        UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
        VARCHAR, UUID, CHAR(64), UUID, VARCHAR
    ) TO dianlian_supervisor_dispatch_authorizer;
GRANT EXECUTE ON FUNCTION
    deer_runtime.record_runtime_external_operation_outcome(
        UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
        VARCHAR, UUID, CHAR(64), UUID, VARCHAR, UUID, BIGINT, CHAR(64),
        VARCHAR, VARCHAR, CHAR(64), VARCHAR
    ) TO dianlian_supervisor_outcome_reconciler;
GRANT EXECUTE ON FUNCTION
    deer_runtime.reconcile_runtime_external_operation_outcome(
        UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
        VARCHAR, UUID, CHAR(64), UUID, UUID, VARCHAR, UUID, BIGINT,
        CHAR(64), VARCHAR, VARCHAR, CHAR(64), VARCHAR
    ) TO dianlian_supervisor_outcome_reconciler;
GRANT EXECUTE ON FUNCTION
    deer_runtime.load_runtime_external_operation_barrier(
        UUID, UUID, BIGINT, VARCHAR, BIGINT
    ) TO dianlian_supervisor_executor;

-- Replacements retain their existing owner and executor ACL; repeat the grant
-- here so the migration's intended terminal barrier remains explicit.
GRANT EXECUTE ON FUNCTION deer_runtime.complete_runtime_run(
    UUID, UUID, VARCHAR, BIGINT, UUID, VARCHAR, JSONB
) TO dianlian_supervisor_executor;
GRANT EXECUTE ON FUNCTION deer_runtime.fail_runtime_run(
    UUID, UUID, VARCHAR, BIGINT, UUID, VARCHAR, VARCHAR, JSONB
) TO dianlian_supervisor_executor;
GRANT EXECUTE ON FUNCTION deer_runtime.finish_runtime_run_cancellation(
    UUID, UUID, VARCHAR, BIGINT, VARCHAR, UUID, VARCHAR, JSONB
) TO dianlian_supervisor_executor;

RESET ROLE;

REVOKE TRIGGER ON TABLE
    deer_runtime.runtime_external_operation_attempt,
    deer_runtime.runtime_external_operation_event
    FROM dianlian_supervisor_routine_owner;
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner;

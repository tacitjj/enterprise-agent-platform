-- Purpose: add dormant one-shot external-operation permits to the S0 Supervisor authority.
-- Scope: PostgreSQL 15+; only deer_runtime permit facts and controlled routines are added.
-- Preconditions: migrations 000-009 are current and all named cluster roles already exist.
-- Idempotency: the migration ledger applies this immutable file once by checksum.
-- Activation: no worker, HTTP endpoint, Java client, or external dispatch is enabled here.
-- Rollback: deploy the previous runtime first; removal requires a reviewed later migration.

DO $precondition$
DECLARE
    v_authorizer pg_catalog.pg_roles%ROWTYPE;
BEGIN
    SELECT * INTO v_authorizer
      FROM pg_catalog.pg_roles
     WHERE rolname = 'dianlian_supervisor_permit_authorizer';
    IF NOT FOUND
       OR v_authorizer.rolcanlogin
       OR v_authorizer.rolsuper
       OR v_authorizer.rolcreatedb
       OR v_authorizer.rolcreaterole
       OR v_authorizer.rolinherit
       OR v_authorizer.rolreplication
       OR v_authorizer.rolbypassrls THEN
        RAISE EXCEPTION
            'dianlian_supervisor_permit_authorizer must be a restricted NOLOGIN NOINHERIT role'
            USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_auth_members
         WHERE member = v_authorizer.oid
    ) THEN
        RAISE EXCEPTION
            'dianlian_supervisor_permit_authorizer must not inherit another role'
            USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
        SELECT 1
         FROM pg_catalog.pg_auth_members
         WHERE roleid = v_authorizer.oid
           AND admin_option
    ) THEN
        RAISE EXCEPTION
            'dianlian_supervisor_permit_authorizer grants must not carry admin option'
            USING ERRCODE = '42501';
    END IF;
END;
$precondition$;

REVOKE ALL PRIVILEGES ON SCHEMA deer_runtime
    FROM dianlian_supervisor_permit_authorizer;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_permit_authorizer;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_permit_authorizer;
SET LOCAL ROLE dianlian_supervisor_routine_owner;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA deer_runtime
    FROM dianlian_supervisor_permit_authorizer;
RESET ROLE;

CREATE TABLE deer_runtime.runtime_external_intent
(
    tenant_id                    UUID         NOT NULL,
    runtime_run_id               UUID         NOT NULL,
    operation_kind               VARCHAR(32)  NOT NULL,
    intent_id                    UUID         NOT NULL,
    runtime_thread_id            UUID         NOT NULL,
    task_step_id                 UUID         NOT NULL,
    task_execution_generation    BIGINT       NOT NULL CHECK (task_execution_generation > 0),
    admission_contract_version   VARCHAR(8)   NOT NULL CHECK (admission_contract_version = '2.2'),
    admission_snapshot_id        UUID         NOT NULL,
    admission_snapshot_hash      CHAR(64)     NOT NULL
        CHECK (admission_snapshot_hash ~ '^[0-9a-f]{64}$'),
    request_hash                 CHAR(64)     NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    created_at                   TIMESTAMPTZ  NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    PRIMARY KEY (tenant_id, runtime_run_id, operation_kind, intent_id),
    FOREIGN KEY (tenant_id, runtime_run_id, runtime_thread_id)
        REFERENCES deer_runtime.runtime_run (tenant_id, runtime_run_id, runtime_thread_id),
    FOREIGN KEY (tenant_id, runtime_run_id)
        REFERENCES deer_runtime.runtime_execution_admission_ref (tenant_id, runtime_run_id),
    CHECK (operation_kind IN ('ADMISSION_RESOLVE', 'MODEL_INVOKE', 'TOOL_INVOKE')),
    CHECK (
        tenant_id <> '00000000-0000-0000-0000-000000000000'::UUID
        AND runtime_run_id <> '00000000-0000-0000-0000-000000000000'::UUID
        AND intent_id <> '00000000-0000-0000-0000-000000000000'::UUID
        AND runtime_thread_id <> '00000000-0000-0000-0000-000000000000'::UUID
        AND task_step_id <> '00000000-0000-0000-0000-000000000000'::UUID
        AND admission_snapshot_id <> '00000000-0000-0000-0000-000000000000'::UUID
    )
);

CREATE TABLE deer_runtime.runtime_external_permit_attempt
(
    tenant_id                    UUID         NOT NULL,
    runtime_external_permit_id   UUID         NOT NULL,
    runtime_run_id               UUID         NOT NULL,
    operation_kind               VARCHAR(32)  NOT NULL,
    intent_id                    UUID         NOT NULL,
    lease_owner                  VARCHAR(160) NOT NULL CHECK (BTRIM(lease_owner) <> ''),
    lease_epoch                  BIGINT       NOT NULL CHECK (lease_epoch > 0),
    permit_attempt               INTEGER      NOT NULL CHECK (permit_attempt > 0),
    status                       VARCHAR(16)  NOT NULL CHECK (status IN ('ISSUED', 'CONSUMED')),
    requested_ttl_seconds        INTEGER      NOT NULL CHECK (requested_ttl_seconds BETWEEN 1 AND 60),
    issued_at                    TIMESTAMPTZ  NOT NULL,
    expires_at                   TIMESTAMPTZ  NOT NULL,
    issue_event_id               UUID         NOT NULL,
    consume_event_id             UUID,
    consumed_by                  VARCHAR(160),
    consumed_at                  TIMESTAMPTZ,
    updated_at                   TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (tenant_id, runtime_external_permit_id),
    UNIQUE (runtime_external_permit_id),
    UNIQUE (issue_event_id),
    UNIQUE (consume_event_id),
    UNIQUE (tenant_id, runtime_run_id, operation_kind, intent_id, permit_attempt),
    FOREIGN KEY (tenant_id, runtime_run_id, operation_kind, intent_id)
        REFERENCES deer_runtime.runtime_external_intent
            (tenant_id, runtime_run_id, operation_kind, intent_id),
    CHECK (runtime_external_permit_id <> '00000000-0000-0000-0000-000000000000'::UUID),
    CHECK (issue_event_id <> '00000000-0000-0000-0000-000000000000'::UUID),
    CHECK (consume_event_id IS NULL OR consume_event_id <>
        '00000000-0000-0000-0000-000000000000'::UUID),
    CHECK (expires_at > issued_at),
    CHECK (updated_at >= issued_at),
    CHECK (
        (status = 'ISSUED'
            AND consume_event_id IS NULL AND consumed_by IS NULL AND consumed_at IS NULL)
        OR
        (status = 'CONSUMED'
            AND consume_event_id IS NOT NULL AND consumed_by IS NOT NULL
            AND BTRIM(consumed_by) <> '' AND consumed_at IS NOT NULL
            AND consumed_at >= issued_at AND consumed_at < expires_at
            AND updated_at >= consumed_at)
    )
);

CREATE UNIQUE INDEX uq_runtime_external_intent_consumed
    ON deer_runtime.runtime_external_permit_attempt
        (tenant_id, runtime_run_id, operation_kind, intent_id)
    WHERE status = 'CONSUMED';

CREATE INDEX idx_runtime_external_intent_attempt
    ON deer_runtime.runtime_external_permit_attempt
        (tenant_id, runtime_run_id, operation_kind, intent_id, permit_attempt DESC);

CREATE TABLE deer_runtime.runtime_external_permit_event
(
    tenant_id                    UUID         NOT NULL,
    runtime_external_permit_id   UUID         NOT NULL,
    event_id                     UUID         NOT NULL,
    runtime_run_id               UUID         NOT NULL,
    operation_kind               VARCHAR(32)  NOT NULL,
    intent_id                    UUID         NOT NULL,
    permit_attempt               INTEGER      NOT NULL CHECK (permit_attempt > 0),
    event_type                   VARCHAR(16)  NOT NULL CHECK (event_type IN ('ISSUED', 'CONSUMED')),
    lease_owner                  VARCHAR(160) NOT NULL CHECK (BTRIM(lease_owner) <> ''),
    lease_epoch                  BIGINT       NOT NULL CHECK (lease_epoch > 0),
    occurred_at                  TIMESTAMPTZ  NOT NULL,
    created_at                   TIMESTAMPTZ  NOT NULL DEFAULT CLOCK_TIMESTAMP(),
    PRIMARY KEY (tenant_id, runtime_external_permit_id, event_id),
    UNIQUE (event_id),
    UNIQUE (tenant_id, runtime_external_permit_id, event_type),
    FOREIGN KEY (tenant_id, runtime_external_permit_id)
        REFERENCES deer_runtime.runtime_external_permit_attempt
            (tenant_id, runtime_external_permit_id),
    FOREIGN KEY (tenant_id, runtime_run_id, operation_kind, intent_id, permit_attempt)
        REFERENCES deer_runtime.runtime_external_permit_attempt
            (tenant_id, runtime_run_id, operation_kind, intent_id, permit_attempt),
    CHECK (event_id <> '00000000-0000-0000-0000-000000000000'::UUID)
);

REVOKE ALL PRIVILEGES ON TABLE deer_runtime.runtime_external_intent FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE deer_runtime.runtime_external_permit_attempt FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE deer_runtime.runtime_external_permit_event FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE deer_runtime.runtime_external_intent
    FROM dianlian_supervisor_executor, dianlian_supervisor_permit_authorizer;
REVOKE ALL PRIVILEGES ON TABLE deer_runtime.runtime_external_permit_attempt
    FROM dianlian_supervisor_executor, dianlian_supervisor_permit_authorizer;
REVOKE ALL PRIVILEGES ON TABLE deer_runtime.runtime_external_permit_event
    FROM dianlian_supervisor_executor, dianlian_supervisor_permit_authorizer;

GRANT USAGE ON SCHEMA deer_runtime TO dianlian_supervisor_executor;
GRANT USAGE ON SCHEMA deer_runtime TO dianlian_supervisor_permit_authorizer;

GRANT SELECT, INSERT ON TABLE deer_runtime.runtime_external_intent
    TO dianlian_supervisor_routine_owner;
GRANT SELECT, INSERT ON TABLE deer_runtime.runtime_external_permit_attempt
    TO dianlian_supervisor_routine_owner;
GRANT UPDATE (status, consume_event_id, consumed_by, consumed_at, updated_at)
    ON TABLE deer_runtime.runtime_external_permit_attempt
    TO dianlian_supervisor_routine_owner;
GRANT SELECT, INSERT ON TABLE deer_runtime.runtime_external_permit_event
    TO dianlian_supervisor_routine_owner;
GRANT TRIGGER ON TABLE deer_runtime.runtime_external_intent
    TO dianlian_supervisor_routine_owner;
GRANT TRIGGER ON TABLE deer_runtime.runtime_external_permit_attempt
    TO dianlian_supervisor_routine_owner;
GRANT TRIGGER ON TABLE deer_runtime.runtime_external_permit_event
    TO dianlian_supervisor_routine_owner;
GRANT CREATE ON SCHEMA deer_runtime TO dianlian_supervisor_routine_owner;

SET LOCAL ROLE dianlian_supervisor_routine_owner;

CREATE FUNCTION deer_runtime.protect_runtime_external_permit_attempt()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, deer_runtime, pg_temp
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'runtime_external_permit_attempt cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.runtime_external_permit_id IS DISTINCT FROM OLD.runtime_external_permit_id
       OR NEW.runtime_run_id IS DISTINCT FROM OLD.runtime_run_id
       OR NEW.operation_kind IS DISTINCT FROM OLD.operation_kind
       OR NEW.intent_id IS DISTINCT FROM OLD.intent_id
       OR NEW.lease_owner IS DISTINCT FROM OLD.lease_owner
       OR NEW.lease_epoch IS DISTINCT FROM OLD.lease_epoch
       OR NEW.permit_attempt IS DISTINCT FROM OLD.permit_attempt
       OR NEW.requested_ttl_seconds IS DISTINCT FROM OLD.requested_ttl_seconds
       OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
       OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
       OR NEW.issue_event_id IS DISTINCT FROM OLD.issue_event_id
       OR OLD.status <> 'ISSUED'
       OR NEW.status <> 'CONSUMED'
       OR OLD.consume_event_id IS NOT NULL
       OR OLD.consumed_by IS NOT NULL
       OR OLD.consumed_at IS NOT NULL
       OR NEW.consume_event_id IS NULL
       OR NEW.consumed_by IS NULL
       OR BTRIM(NEW.consumed_by) = ''
       OR NEW.consumed_at IS NULL
       OR NEW.updated_at IS NULL
       OR NEW.consumed_at < OLD.issued_at
       OR NEW.consumed_at >= OLD.expires_at
       OR NEW.updated_at < NEW.consumed_at THEN
        RAISE EXCEPTION 'runtime_external_permit_attempt lifecycle mutation is invalid'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$function$;

REVOKE ALL PRIVILEGES ON FUNCTION
    deer_runtime.protect_runtime_external_permit_attempt()
    FROM PUBLIC, dianlian_supervisor_executor,
         dianlian_supervisor_permit_authorizer;
ALTER FUNCTION deer_runtime.protect_runtime_external_permit_attempt()
    OWNER TO dianlian_supervisor_routine_owner;

CREATE TRIGGER trg_runtime_external_intent_append_only
    BEFORE UPDATE OR DELETE ON deer_runtime.runtime_external_intent
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();
CREATE TRIGGER trg_runtime_external_intent_no_truncate
    BEFORE TRUNCATE ON deer_runtime.runtime_external_intent
    FOR EACH STATEMENT EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();
CREATE TRIGGER trg_runtime_external_permit_attempt_lifecycle
    BEFORE UPDATE OR DELETE ON deer_runtime.runtime_external_permit_attempt
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.protect_runtime_external_permit_attempt();
CREATE TRIGGER trg_runtime_external_permit_attempt_no_truncate
    BEFORE TRUNCATE ON deer_runtime.runtime_external_permit_attempt
    FOR EACH STATEMENT EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();
CREATE TRIGGER trg_runtime_external_permit_event_append_only
    BEFORE UPDATE OR DELETE ON deer_runtime.runtime_external_permit_event
    FOR EACH ROW EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();
CREATE TRIGGER trg_runtime_external_permit_event_no_truncate
    BEFORE TRUNCATE ON deer_runtime.runtime_external_permit_event
    FOR EACH STATEMENT EXECUTE FUNCTION deer_runtime.reject_append_only_mutation();

CREATE FUNCTION deer_runtime.issue_runtime_external_permit(
    p_tenant_id UUID,
    p_runtime_run_id UUID,
    p_lease_owner VARCHAR,
    p_lease_epoch BIGINT,
    p_runtime_external_permit_id UUID,
    p_operation_kind VARCHAR,
    p_intent_id UUID,
    p_request_hash CHAR(64),
    p_requested_ttl_seconds INTEGER,
    p_issue_event_id UUID
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
    v_expires_at TIMESTAMPTZ;
    v_run deer_runtime.runtime_run%ROWTYPE;
    v_admission deer_runtime.runtime_execution_admission_ref%ROWTYPE;
    v_intent deer_runtime.runtime_external_intent%ROWTYPE;
    v_attempt deer_runtime.runtime_external_permit_attempt%ROWTYPE;
    v_next_attempt INTEGER;
BEGIN
    IF p_tenant_id IS NULL OR p_runtime_run_id IS NULL
       OR p_runtime_external_permit_id IS NULL OR p_intent_id IS NULL
       OR p_issue_event_id IS NULL
       OR p_tenant_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_run_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_runtime_external_permit_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_intent_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_issue_event_id = '00000000-0000-0000-0000-000000000000'::UUID
       OR p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''
       OR LENGTH(p_lease_owner) > 160
       OR p_lease_epoch IS NULL OR p_lease_epoch < 1
       OR p_operation_kind IS NULL
       OR p_operation_kind NOT IN ('ADMISSION_RESOLVE', 'MODEL_INVOKE', 'TOOL_INVOKE')
       OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_requested_ttl_seconds IS NULL
       OR p_requested_ttl_seconds < 1 OR p_requested_ttl_seconds > 60 THEN
        RAISE EXCEPTION 'invalid runtime external permit issue arguments'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_run
      FROM deer_runtime.runtime_run
     WHERE runtime_run.tenant_id = p_tenant_id
       AND runtime_run.runtime_run_id = p_runtime_run_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;
    END IF;
    v_now := CLOCK_TIMESTAMP();

    SELECT * INTO v_admission
      FROM deer_runtime.runtime_execution_admission_ref AS admission_ref
     WHERE admission_ref.tenant_id = p_tenant_id
       AND admission_ref.runtime_run_id = p_runtime_run_id
       AND admission_ref.admission_contract_version = '2.2';
    IF NOT FOUND THEN
        RETURN;
    END IF;

    SELECT * INTO v_intent
      FROM deer_runtime.runtime_external_intent AS external_intent
     WHERE external_intent.tenant_id = p_tenant_id
       AND external_intent.runtime_run_id = p_runtime_run_id
       AND external_intent.operation_kind = p_operation_kind
       AND external_intent.intent_id = p_intent_id;
    IF FOUND THEN
        IF v_intent.runtime_thread_id IS DISTINCT FROM v_run.runtime_thread_id
           OR v_intent.task_step_id IS DISTINCT FROM v_run.task_step_id
           OR v_intent.task_execution_generation IS DISTINCT FROM v_run.task_execution_generation
           OR v_intent.admission_contract_version IS DISTINCT FROM '2.2'
           OR v_intent.admission_snapshot_id IS DISTINCT FROM v_admission.admission_snapshot_id
           OR v_intent.admission_snapshot_hash IS DISTINCT FROM v_admission.admission_snapshot_hash
           OR v_intent.request_hash IS DISTINCT FROM p_request_hash THEN
            RAISE EXCEPTION 'runtime external intent identity conflict'
                USING ERRCODE = '23505';
        END IF;
    END IF;

    SELECT * INTO v_attempt
      FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
     WHERE permit_attempt.runtime_external_permit_id = p_runtime_external_permit_id
     FOR UPDATE;
    IF FOUND THEN
        IF v_attempt.tenant_id IS DISTINCT FROM p_tenant_id
           OR v_attempt.runtime_run_id IS DISTINCT FROM p_runtime_run_id
           OR v_attempt.operation_kind IS DISTINCT FROM p_operation_kind
           OR v_attempt.intent_id IS DISTINCT FROM p_intent_id
           OR v_attempt.lease_owner IS DISTINCT FROM p_lease_owner
           OR v_attempt.lease_epoch IS DISTINCT FROM p_lease_epoch
           OR v_attempt.requested_ttl_seconds IS DISTINCT FROM p_requested_ttl_seconds
           OR v_attempt.issue_event_id IS DISTINCT FROM p_issue_event_id THEN
            RAISE EXCEPTION 'runtime external permit issue idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY
        SELECT external_intent.tenant_id,
               permit_attempt.runtime_external_permit_id,
               external_intent.runtime_run_id,
               external_intent.runtime_thread_id,
               external_intent.task_step_id,
               external_intent.task_execution_generation,
               external_intent.admission_contract_version,
               external_intent.admission_snapshot_id,
               external_intent.admission_snapshot_hash,
               external_intent.operation_kind,
               external_intent.intent_id,
               external_intent.request_hash,
               permit_attempt.lease_owner,
               permit_attempt.lease_epoch,
               permit_attempt.permit_attempt,
               permit_attempt.status,
               permit_attempt.requested_ttl_seconds,
               permit_attempt.issued_at,
               permit_attempt.expires_at,
               permit_attempt.issue_event_id,
               permit_attempt.consume_event_id,
               permit_attempt.consumed_by,
               permit_attempt.consumed_at,
               permit_attempt.updated_at
          FROM deer_runtime.runtime_external_intent AS external_intent
          JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
            ON permit_attempt.tenant_id = external_intent.tenant_id
           AND permit_attempt.runtime_run_id = external_intent.runtime_run_id
           AND permit_attempt.operation_kind = external_intent.operation_kind
           AND permit_attempt.intent_id = external_intent.intent_id
         WHERE permit_attempt.tenant_id = v_attempt.tenant_id
           AND permit_attempt.runtime_external_permit_id = v_attempt.runtime_external_permit_id;
        RETURN;
    END IF;

    SELECT * INTO v_attempt
      FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
     WHERE permit_attempt.tenant_id = p_tenant_id
       AND permit_attempt.runtime_run_id = p_runtime_run_id
       AND permit_attempt.operation_kind = p_operation_kind
       AND permit_attempt.intent_id = p_intent_id
       AND permit_attempt.status = 'CONSUMED'
     FOR UPDATE;
    IF FOUND THEN
        IF v_run.status <> 'RUNNING'
           OR v_run.lease_owner IS DISTINCT FROM p_lease_owner
           OR v_run.lease_epoch IS DISTINCT FROM p_lease_epoch
           OR v_run.lease_until IS NULL OR v_run.lease_until <= v_now THEN
            RETURN;
        END IF;
        RETURN QUERY
        SELECT external_intent.tenant_id,
               permit_attempt.runtime_external_permit_id,
               external_intent.runtime_run_id,
               external_intent.runtime_thread_id,
               external_intent.task_step_id,
               external_intent.task_execution_generation,
               external_intent.admission_contract_version,
               external_intent.admission_snapshot_id,
               external_intent.admission_snapshot_hash,
               external_intent.operation_kind,
               external_intent.intent_id,
               external_intent.request_hash,
               permit_attempt.lease_owner,
               permit_attempt.lease_epoch,
               permit_attempt.permit_attempt,
               permit_attempt.status,
               permit_attempt.requested_ttl_seconds,
               permit_attempt.issued_at,
               permit_attempt.expires_at,
               permit_attempt.issue_event_id,
               permit_attempt.consume_event_id,
               permit_attempt.consumed_by,
               permit_attempt.consumed_at,
               permit_attempt.updated_at
          FROM deer_runtime.runtime_external_intent AS external_intent
          JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
            ON permit_attempt.tenant_id = external_intent.tenant_id
           AND permit_attempt.runtime_run_id = external_intent.runtime_run_id
           AND permit_attempt.operation_kind = external_intent.operation_kind
           AND permit_attempt.intent_id = external_intent.intent_id
         WHERE permit_attempt.tenant_id = v_attempt.tenant_id
           AND permit_attempt.runtime_external_permit_id = v_attempt.runtime_external_permit_id;
        RETURN;
    END IF;

    IF v_run.status <> 'RUNNING'
       OR v_run.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_run.lease_epoch IS DISTINCT FROM p_lease_epoch
       OR v_run.lease_until IS NULL OR v_run.lease_until <= v_now THEN
        RETURN;
    END IF;

    v_expires_at := v_now + MAKE_INTERVAL(secs => p_requested_ttl_seconds);
    IF v_expires_at > v_run.lease_until THEN
        RETURN;
    END IF;

    IF v_intent.tenant_id IS NULL THEN
        INSERT INTO deer_runtime.runtime_external_intent (
            tenant_id, runtime_run_id, operation_kind, intent_id,
            runtime_thread_id, task_step_id, task_execution_generation,
            admission_contract_version, admission_snapshot_id,
            admission_snapshot_hash, request_hash, created_at
        ) VALUES (
            p_tenant_id, p_runtime_run_id, p_operation_kind, p_intent_id,
            v_run.runtime_thread_id, v_run.task_step_id, v_run.task_execution_generation,
            '2.2', v_admission.admission_snapshot_id,
            v_admission.admission_snapshot_hash, p_request_hash, v_now
        ) RETURNING * INTO v_intent;
    END IF;

    SELECT * INTO v_attempt
      FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
     WHERE permit_attempt.tenant_id = p_tenant_id
       AND permit_attempt.runtime_run_id = p_runtime_run_id
       AND permit_attempt.operation_kind = p_operation_kind
       AND permit_attempt.intent_id = p_intent_id
       AND permit_attempt.lease_epoch = p_lease_epoch
       AND permit_attempt.status = 'ISSUED'
       AND permit_attempt.expires_at > v_now
     ORDER BY permit_attempt.permit_attempt DESC
     LIMIT 1
     FOR UPDATE;
    IF FOUND THEN
        RAISE EXCEPTION 'live runtime external permit already exists for this lease epoch'
            USING ERRCODE = '23505';
    END IF;

    SELECT COALESCE(MAX(permit_attempt.permit_attempt), 0) + 1
      INTO v_next_attempt
      FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
     WHERE permit_attempt.tenant_id = p_tenant_id
       AND permit_attempt.runtime_run_id = p_runtime_run_id
       AND permit_attempt.operation_kind = p_operation_kind
       AND permit_attempt.intent_id = p_intent_id;

    INSERT INTO deer_runtime.runtime_external_permit_attempt (
        tenant_id, runtime_external_permit_id, runtime_run_id, operation_kind,
        intent_id, lease_owner, lease_epoch, permit_attempt, status,
        requested_ttl_seconds, issued_at, expires_at, issue_event_id,
        consume_event_id, consumed_by, consumed_at, updated_at
    ) VALUES (
        p_tenant_id, p_runtime_external_permit_id, p_runtime_run_id, p_operation_kind,
        p_intent_id, p_lease_owner, p_lease_epoch, v_next_attempt, 'ISSUED',
        p_requested_ttl_seconds, v_now, v_expires_at, p_issue_event_id,
        NULL, NULL, NULL, v_now
    ) RETURNING * INTO v_attempt;

    INSERT INTO deer_runtime.runtime_external_permit_event (
        tenant_id, runtime_external_permit_id, event_id, runtime_run_id,
        operation_kind, intent_id, permit_attempt, event_type,
        lease_owner, lease_epoch, occurred_at, created_at
    ) VALUES (
        p_tenant_id, p_runtime_external_permit_id, p_issue_event_id, p_runtime_run_id,
        p_operation_kind, p_intent_id, v_next_attempt, 'ISSUED',
        p_lease_owner, p_lease_epoch, v_now, v_now
    );

    RETURN QUERY
    SELECT external_intent.tenant_id,
           permit_attempt.runtime_external_permit_id,
           external_intent.runtime_run_id,
           external_intent.runtime_thread_id,
           external_intent.task_step_id,
           external_intent.task_execution_generation,
           external_intent.admission_contract_version,
           external_intent.admission_snapshot_id,
           external_intent.admission_snapshot_hash,
           external_intent.operation_kind,
           external_intent.intent_id,
           external_intent.request_hash,
           permit_attempt.lease_owner,
           permit_attempt.lease_epoch,
           permit_attempt.permit_attempt,
           permit_attempt.status,
           permit_attempt.requested_ttl_seconds,
           permit_attempt.issued_at,
           permit_attempt.expires_at,
           permit_attempt.issue_event_id,
           permit_attempt.consume_event_id,
           permit_attempt.consumed_by,
           permit_attempt.consumed_at,
           permit_attempt.updated_at
      FROM deer_runtime.runtime_external_intent AS external_intent
      JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
        ON permit_attempt.tenant_id = external_intent.tenant_id
       AND permit_attempt.runtime_run_id = external_intent.runtime_run_id
       AND permit_attempt.operation_kind = external_intent.operation_kind
       AND permit_attempt.intent_id = external_intent.intent_id
     WHERE permit_attempt.tenant_id = v_attempt.tenant_id
       AND permit_attempt.runtime_external_permit_id = v_attempt.runtime_external_permit_id;
END;
$function$;

CREATE FUNCTION deer_runtime.consume_runtime_external_permit(
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
    v_intent deer_runtime.runtime_external_intent%ROWTYPE;
    v_attempt deer_runtime.runtime_external_permit_attempt%ROWTYPE;
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
       OR p_operation_kind IS NULL
       OR p_operation_kind NOT IN ('ADMISSION_RESOLVE', 'MODEL_INVOKE', 'TOOL_INVOKE')
       OR p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'
       OR p_consumed_by IS NULL OR BTRIM(p_consumed_by) = ''
       OR LENGTH(p_consumed_by) > 160 THEN
        RAISE EXCEPTION 'invalid runtime external permit consume arguments'
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

    SELECT * INTO v_intent
      FROM deer_runtime.runtime_external_intent AS external_intent
     WHERE external_intent.tenant_id = p_tenant_id
       AND external_intent.runtime_run_id = p_runtime_run_id
       AND external_intent.operation_kind = p_operation_kind
       AND external_intent.intent_id = p_intent_id;
    IF NOT FOUND THEN
        IF EXISTS (
            SELECT 1
              FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
             WHERE permit_attempt.runtime_external_permit_id = p_runtime_external_permit_id
        ) THEN
            RAISE EXCEPTION 'runtime external permit consume identity conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN;
    END IF;

    SELECT * INTO v_attempt
      FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
     WHERE permit_attempt.tenant_id = p_tenant_id
       AND permit_attempt.runtime_external_permit_id = p_runtime_external_permit_id
       AND permit_attempt.runtime_run_id = p_runtime_run_id
       AND permit_attempt.operation_kind = p_operation_kind
       AND permit_attempt.intent_id = p_intent_id
     FOR UPDATE;
    IF NOT FOUND THEN
        IF EXISTS (
            SELECT 1
              FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
             WHERE permit_attempt.runtime_external_permit_id = p_runtime_external_permit_id
        ) THEN
            RAISE EXCEPTION 'runtime external permit consume identity conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN;
    END IF;

    IF v_intent.task_execution_generation IS DISTINCT FROM p_task_execution_generation
       OR v_intent.admission_contract_version IS DISTINCT FROM '2.2'
       OR v_intent.admission_snapshot_id IS DISTINCT FROM p_admission_snapshot_id
       OR v_intent.admission_snapshot_hash IS DISTINCT FROM p_admission_snapshot_hash
       OR v_intent.request_hash IS DISTINCT FROM p_request_hash
       OR v_attempt.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_attempt.lease_epoch IS DISTINCT FROM p_lease_epoch THEN
        RAISE EXCEPTION 'runtime external permit consume identity conflict'
            USING ERRCODE = '23505';
    END IF;

    IF v_attempt.status = 'CONSUMED' THEN
        IF v_attempt.consume_event_id IS DISTINCT FROM p_consume_event_id
           OR v_attempt.consumed_by IS DISTINCT FROM p_consumed_by THEN
            RAISE EXCEPTION 'runtime external permit consume idempotency conflict'
                USING ERRCODE = '23505';
        END IF;
        RETURN QUERY
        SELECT external_intent.tenant_id,
               permit_attempt.runtime_external_permit_id,
               external_intent.runtime_run_id,
               external_intent.runtime_thread_id,
               external_intent.task_step_id,
               external_intent.task_execution_generation,
               external_intent.admission_contract_version,
               external_intent.admission_snapshot_id,
               external_intent.admission_snapshot_hash,
               external_intent.operation_kind,
               external_intent.intent_id,
               external_intent.request_hash,
               permit_attempt.lease_owner,
               permit_attempt.lease_epoch,
               permit_attempt.permit_attempt,
               permit_attempt.status,
               permit_attempt.requested_ttl_seconds,
               permit_attempt.issued_at,
               permit_attempt.expires_at,
               permit_attempt.issue_event_id,
               permit_attempt.consume_event_id,
               permit_attempt.consumed_by,
               permit_attempt.consumed_at,
               permit_attempt.updated_at
          FROM deer_runtime.runtime_external_intent AS external_intent
          JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
            ON permit_attempt.tenant_id = external_intent.tenant_id
           AND permit_attempt.runtime_run_id = external_intent.runtime_run_id
           AND permit_attempt.operation_kind = external_intent.operation_kind
           AND permit_attempt.intent_id = external_intent.intent_id
         WHERE permit_attempt.tenant_id = v_attempt.tenant_id
           AND permit_attempt.runtime_external_permit_id = v_attempt.runtime_external_permit_id;
        RETURN;
    END IF;

    IF v_run.status <> 'RUNNING'
       OR v_run.task_execution_generation IS DISTINCT FROM p_task_execution_generation
       OR v_run.lease_owner IS DISTINCT FROM p_lease_owner
       OR v_run.lease_epoch IS DISTINCT FROM p_lease_epoch
       OR v_run.lease_until IS NULL OR v_run.lease_until <= v_now
       OR v_attempt.expires_at <= v_now THEN
        RETURN;
    END IF;

    UPDATE deer_runtime.runtime_external_permit_attempt AS permit_attempt
       SET status = 'CONSUMED',
           consume_event_id = p_consume_event_id,
           consumed_by = p_consumed_by,
           consumed_at = v_now,
           updated_at = v_now
     WHERE permit_attempt.tenant_id = p_tenant_id
       AND permit_attempt.runtime_external_permit_id = p_runtime_external_permit_id
       AND permit_attempt.status = 'ISSUED'
    RETURNING permit_attempt.* INTO v_attempt;
    IF NOT FOUND THEN
        RETURN;
    END IF;

    INSERT INTO deer_runtime.runtime_external_permit_event (
        tenant_id, runtime_external_permit_id, event_id, runtime_run_id,
        operation_kind, intent_id, permit_attempt, event_type,
        lease_owner, lease_epoch, occurred_at, created_at
    ) VALUES (
        p_tenant_id, p_runtime_external_permit_id, p_consume_event_id, p_runtime_run_id,
        p_operation_kind, p_intent_id, v_attempt.permit_attempt, 'CONSUMED',
        p_lease_owner, p_lease_epoch, v_now, v_now
    );

    RETURN QUERY
    SELECT external_intent.tenant_id,
           permit_attempt.runtime_external_permit_id,
           external_intent.runtime_run_id,
           external_intent.runtime_thread_id,
           external_intent.task_step_id,
           external_intent.task_execution_generation,
           external_intent.admission_contract_version,
           external_intent.admission_snapshot_id,
           external_intent.admission_snapshot_hash,
           external_intent.operation_kind,
           external_intent.intent_id,
           external_intent.request_hash,
           permit_attempt.lease_owner,
           permit_attempt.lease_epoch,
           permit_attempt.permit_attempt,
           permit_attempt.status,
           permit_attempt.requested_ttl_seconds,
           permit_attempt.issued_at,
           permit_attempt.expires_at,
           permit_attempt.issue_event_id,
           permit_attempt.consume_event_id,
           permit_attempt.consumed_by,
           permit_attempt.consumed_at,
           permit_attempt.updated_at
      FROM deer_runtime.runtime_external_intent AS external_intent
      JOIN deer_runtime.runtime_external_permit_attempt AS permit_attempt
        ON permit_attempt.tenant_id = external_intent.tenant_id
       AND permit_attempt.runtime_run_id = external_intent.runtime_run_id
       AND permit_attempt.operation_kind = external_intent.operation_kind
       AND permit_attempt.intent_id = external_intent.intent_id
     WHERE permit_attempt.tenant_id = v_attempt.tenant_id
       AND permit_attempt.runtime_external_permit_id = v_attempt.runtime_external_permit_id;
END;
$function$;

REVOKE ALL PRIVILEGES ON FUNCTION deer_runtime.issue_runtime_external_permit(
    UUID, UUID, VARCHAR, BIGINT, UUID, VARCHAR, UUID, CHAR(64), INTEGER, UUID
) FROM PUBLIC;
REVOKE ALL PRIVILEGES ON FUNCTION deer_runtime.issue_runtime_external_permit(
    UUID, UUID, VARCHAR, BIGINT, UUID, VARCHAR, UUID, CHAR(64), INTEGER, UUID
) FROM dianlian_supervisor_executor, dianlian_supervisor_permit_authorizer;
REVOKE ALL PRIVILEGES ON FUNCTION deer_runtime.consume_runtime_external_permit(
    UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
    VARCHAR, UUID, CHAR(64), UUID, VARCHAR
) FROM PUBLIC;
REVOKE ALL PRIVILEGES ON FUNCTION deer_runtime.consume_runtime_external_permit(
    UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
    VARCHAR, UUID, CHAR(64), UUID, VARCHAR
) FROM dianlian_supervisor_executor, dianlian_supervisor_permit_authorizer;

GRANT EXECUTE ON FUNCTION deer_runtime.issue_runtime_external_permit(
    UUID, UUID, VARCHAR, BIGINT, UUID, VARCHAR, UUID, CHAR(64), INTEGER, UUID
) TO dianlian_supervisor_executor;
GRANT EXECUTE ON FUNCTION deer_runtime.consume_runtime_external_permit(
    UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),
    VARCHAR, UUID, CHAR(64), UUID, VARCHAR
) TO dianlian_supervisor_permit_authorizer;

RESET ROLE;

REVOKE TRIGGER ON TABLE deer_runtime.runtime_external_intent
    FROM dianlian_supervisor_routine_owner;
REVOKE TRIGGER ON TABLE deer_runtime.runtime_external_permit_attempt
    FROM dianlian_supervisor_routine_owner;
REVOKE TRIGGER ON TABLE deer_runtime.runtime_external_permit_event
    FROM dianlian_supervisor_routine_owner;
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner;

-- Purpose: seal the dormant S0 Supervisor behind an explicit database routine boundary.
-- Scope: PostgreSQL 15+; only deer_runtime privileges and existing primitive functions.
-- Preconditions: migrations 000-005 are current and the cluster roles named below exist.
-- Idempotency: the migration ledger applies this immutable file once by checksum.
-- Activation: this migration grants no application wiring and does not enable takeover.
-- Rollback: deploy the previous runtime first; privilege rollback requires a reviewed migration.

DO $precondition$
DECLARE
    v_migrator pg_catalog.pg_roles%ROWTYPE;
    v_routine_owner pg_catalog.pg_roles%ROWTYPE;
    v_executor pg_catalog.pg_roles%ROWTYPE;
BEGIN
    SELECT * INTO v_migrator
      FROM pg_catalog.pg_roles
     WHERE rolname = CURRENT_USER;
    IF NOT FOUND
       OR NOT v_migrator.rolcanlogin
       OR v_migrator.rolsuper
       OR v_migrator.rolcreatedb
       OR v_migrator.rolcreaterole
       OR v_migrator.rolinherit
       OR v_migrator.rolreplication
       OR v_migrator.rolbypassrls THEN
        RAISE EXCEPTION 'Supervisor migrator must be a restricted NOINHERIT login'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_routine_owner
      FROM pg_catalog.pg_roles
     WHERE rolname = 'dianlian_supervisor_routine_owner';
    IF NOT FOUND
       OR v_routine_owner.rolcanlogin
       OR v_routine_owner.rolsuper
       OR v_routine_owner.rolcreatedb
       OR v_routine_owner.rolcreaterole
       OR v_routine_owner.rolinherit
       OR v_routine_owner.rolreplication
       OR v_routine_owner.rolbypassrls THEN
        RAISE EXCEPTION 'dianlian_supervisor_routine_owner must be a restricted NOLOGIN role'
            USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_auth_members
         WHERE member = v_routine_owner.oid
    ) THEN
        RAISE EXCEPTION 'dianlian_supervisor_routine_owner must not inherit another role'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_executor
      FROM pg_catalog.pg_roles
     WHERE rolname = 'dianlian_supervisor_executor';
    IF NOT FOUND
       OR v_executor.rolcanlogin
       OR v_executor.rolsuper
       OR v_executor.rolcreatedb
       OR v_executor.rolcreaterole
       OR v_executor.rolinherit
       OR v_executor.rolreplication
       OR v_executor.rolbypassrls THEN
        RAISE EXCEPTION 'dianlian_supervisor_executor must be a restricted NOLOGIN role'
            USING ERRCODE = '42501';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_catalog.pg_auth_members
         WHERE member = v_executor.oid
    ) THEN
        RAISE EXCEPTION 'dianlian_supervisor_executor must not inherit another role'
            USING ERRCODE = '42501';
    END IF;

    IF NOT pg_catalog.pg_has_role(
        CURRENT_USER,
        'dianlian_supervisor_routine_owner',
        'MEMBER'
    ) THEN
        RAISE EXCEPTION 'Supervisor migrator must be a member of the routine-owner role'
            USING ERRCODE = '42501';
    END IF;
    IF (
        SELECT COUNT(*)
          FROM pg_catalog.pg_auth_members
         WHERE member = v_migrator.oid
    ) <> 1 OR NOT EXISTS (
        SELECT 1
          FROM pg_catalog.pg_auth_members
         WHERE member = v_migrator.oid
           AND roleid = v_routine_owner.oid
           AND NOT admin_option
    ) THEN
        RAISE EXCEPTION 'Supervisor migrator may only hold non-admin routine-owner membership'
            USING ERRCODE = '42501';
    END IF;
END;
$precondition$;

REVOKE ALL PRIVILEGES ON SCHEMA deer_runtime FROM PUBLIC;
REVOKE ALL PRIVILEGES ON SCHEMA deer_runtime FROM dianlian_supervisor_executor;
REVOKE ALL PRIVILEGES ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner;

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA deer_runtime FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_executor;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_routine_owner;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA deer_runtime FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_executor;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_routine_owner;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA deer_runtime FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA deer_runtime
    FROM dianlian_supervisor_executor;

ALTER DEFAULT PRIVILEGES IN SCHEMA deer_runtime
    REVOKE ALL PRIVILEGES ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA deer_runtime
    REVOKE ALL PRIVILEGES ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES
    REVOKE ALL PRIVILEGES ON FUNCTIONS FROM PUBLIC;
SET LOCAL ROLE dianlian_supervisor_routine_owner;
ALTER DEFAULT PRIVILEGES
    REVOKE ALL PRIVILEGES ON FUNCTIONS FROM PUBLIC;
RESET ROLE;

-- The no-login owner needs only the relations touched by the controlled routines.
-- It deliberately receives no privilege on the migration ledger and no DELETE/TRUNCATE.
GRANT USAGE, CREATE ON SCHEMA deer_runtime TO dianlian_supervisor_routine_owner;
GRANT SELECT, INSERT ON TABLE deer_runtime.runtime_thread
    TO dianlian_supervisor_routine_owner;
GRANT SELECT, INSERT, UPDATE ON TABLE deer_runtime.runtime_run
    TO dianlian_supervisor_routine_owner;
GRANT SELECT, INSERT ON TABLE deer_runtime.runtime_run_control
    TO dianlian_supervisor_routine_owner;
GRANT SELECT, INSERT ON TABLE deer_runtime.runtime_run_event
    TO dianlian_supervisor_routine_owner;
GRANT SELECT, INSERT ON TABLE deer_runtime.runtime_checkpoint_ref
    TO dianlian_supervisor_routine_owner;

GRANT USAGE ON SCHEMA deer_runtime TO dianlian_supervisor_executor;

DO $primitive_boundary$
DECLARE
    v_signature TEXT;
    v_function REGPROCEDURE;
BEGIN
    FOREACH v_signature IN ARRAY ARRAY[
        'deer_runtime.admit_runtime_run(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,bigint,varchar,varchar,uuid,uuid,uuid,uuid,jsonb,uuid,bigint,varchar,varchar,character,varchar,uuid,varchar,varchar,varchar,uuid,jsonb)',
        'deer_runtime.claim_runtime_run(uuid,uuid,varchar,integer,uuid,jsonb)',
        'deer_runtime.renew_runtime_run_lease(uuid,uuid,varchar,bigint,integer)',
        'deer_runtime.takeover_runtime_run(uuid,uuid,varchar,integer,uuid,jsonb)',
        'deer_runtime.authorize_runtime_run(uuid,uuid,varchar,bigint)',
        'deer_runtime.append_runtime_run_event(uuid,uuid,varchar,bigint,uuid,varchar,smallint,jsonb)',
        'deer_runtime.record_runtime_checkpoint_ref(uuid,uuid,varchar,bigint,uuid,varchar,varchar,varchar,jsonb)',
        'deer_runtime.request_runtime_run_cancel(uuid,uuid,uuid,uuid,varchar,bigint,varchar,character,jsonb)',
        'deer_runtime.begin_runtime_run_cancellation(uuid,uuid,varchar,bigint,uuid,jsonb)',
        'deer_runtime.complete_runtime_run(uuid,uuid,varchar,bigint,uuid,varchar,jsonb)',
        'deer_runtime.fail_runtime_run(uuid,uuid,varchar,bigint,uuid,varchar,varchar,jsonb)',
        'deer_runtime.finish_runtime_run_cancellation(uuid,uuid,varchar,bigint,varchar,uuid,varchar,jsonb)'
    ]
    LOOP
        v_function := pg_catalog.to_regprocedure(v_signature);
        IF v_function IS NULL THEN
            RAISE EXCEPTION 'Supervisor primitive does not exist: %', v_signature
                USING ERRCODE = '42704';
        END IF;

        EXECUTE pg_catalog.format(
            'REVOKE ALL PRIVILEGES ON FUNCTION %s FROM PUBLIC',
            v_function
        );
        EXECUTE pg_catalog.format(
            'ALTER FUNCTION %s SECURITY DEFINER',
            v_function
        );
        EXECUTE pg_catalog.format(
            'ALTER FUNCTION %s SET search_path TO pg_catalog, deer_runtime, pg_temp',
            v_function
        );
        EXECUTE pg_catalog.format(
            'GRANT EXECUTE ON FUNCTION %s TO dianlian_supervisor_executor',
            v_function
        );
        EXECUTE pg_catalog.format(
            'ALTER FUNCTION %s OWNER TO dianlian_supervisor_routine_owner',
            v_function
        );
    END LOOP;
END;
$primitive_boundary$;

-- Trigger helpers need definer rights because deferred constraints execute at commit,
-- after the runtime caller has already returned from the public primitive. They are
-- deliberately omitted from the executor grant allowlist above.
DO $trigger_boundary$
DECLARE
    v_signature TEXT;
    v_function REGPROCEDURE;
BEGIN
    FOREACH v_signature IN ARRAY ARRAY[
        'deer_runtime.reject_append_only_mutation()',
        'deer_runtime.protect_runtime_run_identity()',
        'deer_runtime.validate_runtime_terminal_consistency()',
        'deer_runtime.reject_post_terminal_runtime_event()',
        'deer_runtime.validate_runtime_cancel_control_consistency()'
    ]
    LOOP
        v_function := pg_catalog.to_regprocedure(v_signature);
        IF v_function IS NULL THEN
            RAISE EXCEPTION 'Supervisor trigger helper does not exist: %', v_signature
                USING ERRCODE = '42704';
        END IF;

        EXECUTE pg_catalog.format(
            'REVOKE ALL PRIVILEGES ON FUNCTION %s FROM PUBLIC',
            v_function
        );
        EXECUTE pg_catalog.format(
            'ALTER FUNCTION %s SECURITY DEFINER',
            v_function
        );
        EXECUTE pg_catalog.format(
            'ALTER FUNCTION %s SET search_path TO pg_catalog, deer_runtime, pg_temp',
            v_function
        );
        EXECUTE pg_catalog.format(
            'ALTER FUNCTION %s OWNER TO dianlian_supervisor_routine_owner',
            v_function
        );
    END LOOP;
END;
$trigger_boundary$;

-- CREATE was needed only for PostgreSQL's function-owner transfer rule.
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner;

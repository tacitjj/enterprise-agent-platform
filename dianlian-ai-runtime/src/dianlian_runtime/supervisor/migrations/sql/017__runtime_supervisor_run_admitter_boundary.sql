-- Purpose: isolate durable Run admission behind a single-purpose capability role.
-- Scope: only privileges on the existing admit_runtime_run routine are changed.
-- Preconditions: migrations 000-016 are current and the sealed run-admitter role exists.
-- Idempotency: the migration ledger applies this immutable privilege change once.
-- Activation: no HTTP route, Java submitter, worker, model, tool, UI, or role flow is enabled.
-- Rollback: deploy the previous runtime first; restore privileges in a reviewed migration.

DO $precondition$
DECLARE
    v_migrator pg_catalog.pg_roles%ROWTYPE;
    v_admitter pg_catalog.pg_roles%ROWTYPE;
    v_wrapper REGPROCEDURE;
BEGIN
    SELECT * INTO v_migrator
      FROM pg_catalog.pg_roles
     WHERE rolname = CURRENT_USER;
    IF NOT FOUND
       OR NOT v_migrator.rolcanlogin
       OR v_migrator.rolinherit
       OR v_migrator.rolsuper
       OR v_migrator.rolcreatedb
       OR v_migrator.rolcreaterole
       OR v_migrator.rolreplication
       OR v_migrator.rolbypassrls THEN
        RAISE EXCEPTION 'Supervisor migrator must be a restricted NOINHERIT login'
            USING ERRCODE = '42501';
    END IF;

    SELECT * INTO v_admitter
      FROM pg_catalog.pg_roles
     WHERE rolname = 'dianlian_supervisor_run_admitter';
    IF NOT FOUND
       OR v_admitter.rolcanlogin
       OR v_admitter.rolinherit
       OR v_admitter.rolsuper
       OR v_admitter.rolcreatedb
       OR v_admitter.rolcreaterole
       OR v_admitter.rolreplication
       OR v_admitter.rolbypassrls
       OR EXISTS (
           SELECT 1
             FROM pg_catalog.pg_auth_members
            WHERE member = v_admitter.oid
       ) THEN
        RAISE EXCEPTION 'dianlian_supervisor_run_admitter must be a sealed NOLOGIN NOINHERIT role'
            USING ERRCODE = '42501';
    END IF;

    IF NOT pg_catalog.pg_has_role(
        CURRENT_USER,
        'dianlian_supervisor_routine_owner',
        'MEMBER'
    ) OR (
        SELECT COUNT(*)
          FROM pg_catalog.pg_auth_members
         WHERE member = v_migrator.oid
    ) <> 1 THEN
        RAISE EXCEPTION 'Supervisor migrator may only inherit the routine-owner role'
            USING ERRCODE = '42501';
    END IF;

    v_wrapper := pg_catalog.to_regprocedure(
        'deer_runtime.admit_runtime_run(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,bigint,varchar,varchar,uuid,uuid,uuid,uuid,jsonb,uuid,bigint,varchar,varchar,character,varchar,uuid,varchar,varchar,varchar,varchar,uuid,character,uuid,jsonb)'
    );
    IF v_wrapper IS NULL THEN
        RAISE EXCEPTION 'runtime Run admission wrapper does not exist'
            USING ERRCODE = '42704';
    END IF;
    IF (
        SELECT owner.rolname
          FROM pg_catalog.pg_proc AS procedure
          JOIN pg_catalog.pg_roles AS owner ON owner.oid = procedure.proowner
         WHERE procedure.oid = v_wrapper
    ) <> 'dianlian_supervisor_routine_owner' THEN
        RAISE EXCEPTION 'runtime Run admission wrapper owner drifted'
            USING ERRCODE = '42501';
    END IF;
END;
$precondition$;

REVOKE ALL PRIVILEGES ON SCHEMA deer_runtime
    FROM dianlian_supervisor_run_admitter;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_run_admitter;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_run_admitter;

DO $revoke_run_admitter_column_privileges$
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
            'REVOKE ALL PRIVILEGES (%I) ON TABLE %I.%I FROM dianlian_supervisor_run_admitter',
            v_column.attname,
            v_column.nspname,
            v_column.relname
        );
    END LOOP;
END;
$revoke_run_admitter_column_privileges$;

SET LOCAL ROLE dianlian_supervisor_routine_owner;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA deer_runtime
    FROM dianlian_supervisor_run_admitter;
REVOKE EXECUTE ON FUNCTION deer_runtime.admit_runtime_run(
    UUID, UUID, UUID, UUID, UUID, UUID, UUID, UUID,
    BIGINT, VARCHAR, VARCHAR, UUID, UUID, UUID, UUID, JSONB,
    UUID, BIGINT, VARCHAR, VARCHAR, CHAR(64), VARCHAR, UUID, VARCHAR,
    VARCHAR, VARCHAR, VARCHAR, UUID, CHAR(64), UUID, JSONB
) FROM PUBLIC, dianlian_supervisor_executor;
GRANT EXECUTE ON FUNCTION deer_runtime.admit_runtime_run(
    UUID, UUID, UUID, UUID, UUID, UUID, UUID, UUID,
    BIGINT, VARCHAR, VARCHAR, UUID, UUID, UUID, UUID, JSONB,
    UUID, BIGINT, VARCHAR, VARCHAR, CHAR(64), VARCHAR, UUID, VARCHAR,
    VARCHAR, VARCHAR, VARCHAR, UUID, CHAR(64), UUID, JSONB
) TO dianlian_supervisor_run_admitter;
RESET ROLE;

GRANT USAGE ON SCHEMA deer_runtime TO dianlian_supervisor_run_admitter;
REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_run_admitter;

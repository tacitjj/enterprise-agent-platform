-- Purpose: isolate durable Run cancel requests behind a single-purpose controller role.
-- Scope: only privileges on the existing request_runtime_run_cancel routine are changed.
-- Preconditions: migrations 000-014 are current and the sealed controller role exists.
-- Idempotency: the migration ledger applies this immutable privilege change once.
-- Activation: no route or Java caller is enabled by this migration.
-- Rollback: deploy the previous runtime first; restore privileges in a reviewed migration.

DO $precondition$
DECLARE
    v_migrator pg_catalog.pg_roles%ROWTYPE;
    v_controller pg_catalog.pg_roles%ROWTYPE;
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

    SELECT * INTO v_controller
      FROM pg_catalog.pg_roles
     WHERE rolname = 'dianlian_supervisor_controller';
    IF NOT FOUND
       OR v_controller.rolcanlogin
       OR v_controller.rolinherit
       OR v_controller.rolsuper
       OR v_controller.rolcreatedb
       OR v_controller.rolcreaterole
       OR v_controller.rolreplication
       OR v_controller.rolbypassrls
       OR EXISTS (
           SELECT 1
             FROM pg_catalog.pg_auth_members
            WHERE member = v_controller.oid
       ) THEN
        RAISE EXCEPTION 'dianlian_supervisor_controller must be a sealed NOLOGIN NOINHERIT role'
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
    ) <> 1 THEN
        RAISE EXCEPTION 'Supervisor migrator may only inherit the routine-owner role'
            USING ERRCODE = '42501';
    END IF;

    v_wrapper := pg_catalog.to_regprocedure(
        'deer_runtime.request_runtime_run_cancel(uuid,uuid,uuid,uuid,varchar,bigint,varchar,character,jsonb)'
    );
    IF v_wrapper IS NULL THEN
        RAISE EXCEPTION 'runtime Run cancel wrapper does not exist'
            USING ERRCODE = '42704';
    END IF;
    IF (
        SELECT owner.rolname
          FROM pg_catalog.pg_proc AS procedure
          JOIN pg_catalog.pg_roles AS owner ON owner.oid = procedure.proowner
         WHERE procedure.oid = v_wrapper
    ) <> 'dianlian_supervisor_routine_owner' THEN
        RAISE EXCEPTION 'runtime Run cancel wrapper owner drifted'
            USING ERRCODE = '42501';
    END IF;
END;
$precondition$;

REVOKE ALL PRIVILEGES ON SCHEMA deer_runtime
    FROM dianlian_supervisor_controller;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_controller;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA deer_runtime
    FROM dianlian_supervisor_controller;

DO $revoke_controller_column_privileges$
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
            'REVOKE ALL PRIVILEGES (%I) ON TABLE %I.%I FROM dianlian_supervisor_controller',
            v_column.attname,
            v_column.nspname,
            v_column.relname
        );
    END LOOP;
END;
$revoke_controller_column_privileges$;

SET LOCAL ROLE dianlian_supervisor_routine_owner;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA deer_runtime
    FROM dianlian_supervisor_controller;
REVOKE EXECUTE ON FUNCTION deer_runtime.request_runtime_run_cancel(
    UUID, UUID, UUID, UUID, VARCHAR, BIGINT, VARCHAR, CHAR(64), JSONB
) FROM PUBLIC, dianlian_supervisor_executor;
GRANT EXECUTE ON FUNCTION deer_runtime.request_runtime_run_cancel(
    UUID, UUID, UUID, UUID, VARCHAR, BIGINT, VARCHAR, CHAR(64), JSONB
) TO dianlian_supervisor_controller;
RESET ROLE;

GRANT USAGE ON SCHEMA deer_runtime TO dianlian_supervisor_controller;

from __future__ import annotations

from hashlib import sha256

import pytest

from dianlian_runtime.migrations import MIGRATION_LOCK_ID as CONTEXT_MIGRATION_LOCK_ID
from dianlian_runtime.supervisor.migrations import (
    MIGRATION_LOCK_ID,
    apply_migrations,
    load_migrations,
    main,
)


def test_supervisor_migrations_start_with_separate_history_ledger() -> None:
    migrations = load_migrations()

    assert [migration.version for migration in migrations] == [
        "000",
        "001",
        "002",
        "003",
        "004",
        "005",
        "006",
        "007",
        "008",
        "009",
        "010",
        "011",
        "012",
        "013",
        "014",
        "015",
        "016",
        "017",
        "018",
        "019",
        "020",
        "021",
        "022",
        "023",
    ]
    migration = migrations[0]
    assert migration.name == "000__migration_history.sql"
    assert migration.checksum == sha256(migration.sql.encode("utf-8")).hexdigest()
    assert "CREATE SCHEMA IF NOT EXISTS deer_runtime" in migration.sql
    assert "CREATE TABLE IF NOT EXISTS deer_runtime.schema_migration" in migration.sql
    assert "dianlian_context" not in migration.sql
    assert MIGRATION_LOCK_ID != CONTEXT_MIGRATION_LOCK_ID


def test_run_admitter_boundary_removes_worker_admission_authority() -> None:
    migration = next(
        item for item in load_migrations() if item.version == "017"
    ).sql

    assert (
        "dianlian_supervisor_run_admitter must be a sealed NOLOGIN NOINHERIT role"
        in migration
    )
    assert (
        "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA deer_runtime\n"
        "    FROM dianlian_supervisor_run_admitter"
        in migration
    )
    assert "REVOKE ALL PRIVILEGES (%I) ON TABLE %I.%I" in migration
    assert (
        "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA deer_runtime\n"
        "    FROM dianlian_supervisor_run_admitter"
        in migration
    )
    wrapper = "deer_runtime.admit_runtime_run("
    assert migration.count(wrapper) >= 3
    revoke_start = migration.index(f"REVOKE EXECUTE ON FUNCTION {wrapper}")
    revoke_end = migration.index(";", revoke_start)
    assert "dianlian_supervisor_executor" in migration[revoke_start:revoke_end]
    grant_start = migration.index(f"GRANT EXECUTE ON FUNCTION {wrapper}")
    grant_end = migration.index(";", grant_start)
    assert (
        ") TO dianlian_supervisor_run_admitter"
        in migration[grant_start:grant_end]
    )
    assert "GRANT USAGE ON SCHEMA deer_runtime TO dianlian_supervisor_run_admitter" in migration
    assert (
        "Activation: no HTTP route, Java submitter, worker, model, tool, UI, or role flow is enabled"
        in migration
    )


def test_run_observer_boundary_exposes_only_atomic_projection_read() -> None:
    migration = next(
        item for item in load_migrations() if item.version == "018"
    ).sql

    assert "dianlian_supervisor_run_observer must be a sealed NOLOGIN NOINHERIT role" in migration
    assert "CREATE FUNCTION deer_runtime.read_runtime_run_projection(" in migration
    assert "p_after_sequence < run.event_retention_floor_sequence - 1" in migration
    assert "ORDER BY event_page.sequence_no" in migration
    assert "LIMIT p_page_size" in migration
    assert ") TO dianlian_supervisor_run_observer" in migration
    assert "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA deer_runtime" in migration
    assert "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA deer_runtime" in migration
    assert migration.count("GRANT CREATE ON SCHEMA deer_runtime") == 1
    assert migration.count("REVOKE CREATE ON SCHEMA deer_runtime") == 2
    assert migration.index(
        "GRANT CREATE ON SCHEMA deer_runtime TO dianlian_supervisor_routine_owner"
    ) < migration.index("SET LOCAL ROLE dianlian_supervisor_routine_owner")
    assert migration.index("SET LOCAL ROLE dianlian_supervisor_routine_owner") < migration.index(
        "CREATE FUNCTION deer_runtime.read_runtime_run_projection("
    )
    assert migration.index("RESET ROLE") < migration.index(
        "REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner"
    )


def test_admission_permit_takeover_recovery_keeps_dispatch_single_consume() -> None:
    migration = next(
        item for item in load_migrations() if item.version == "019"
    ).sql

    assert "DROP INDEX deer_runtime.uq_runtime_external_intent_consumed" in migration
    assert "CREATE UNIQUE INDEX uq_runtime_external_dispatch_intent_consumed" in migration
    assert "operation_kind IN ('MODEL_INVOKE', 'TOOL_INVOKE')" in migration
    assert "CREATE UNIQUE INDEX uq_runtime_admission_intent_consumed_per_epoch" in migration
    assert "operation_kind = 'ADMISSION_RESOLVE'" in migration
    assert "intent_id, lease_epoch" in migration
    assert "CREATE OR REPLACE FUNCTION deer_runtime.issue_runtime_external_permit(" in migration
    assert "ORDER BY permit_attempt.permit_attempt DESC" in migration
    assert "p_operation_kind <> 'ADMISSION_RESOLVE'" in migration
    assert "p_lease_epoch <= v_attempt.lease_epoch" in migration
    assert "MODEL_INVOKE and TOOL_INVOKE remain globally single-consume" in migration


def test_structured_admission_compatibility_is_exact_and_keeps_h12_isolated() -> None:
    admission = next(
        item for item in load_migrations() if item.version == "020"
    ).sql
    permits = next(
        item for item in load_migrations() if item.version == "021"
    ).sql

    assert "admission_contract_version IN ('2.2', '3.0')" in admission
    assert "p_admission_contract_version NOT IN ('2.2', '3.0')" in admission
    assert "CREATE OR REPLACE FUNCTION deer_runtime.admit_runtime_run(" in admission
    assert "CREATE OR REPLACE FUNCTION deer_runtime.select_next_runtime_run_candidate(" in admission
    assert "CREATE OR REPLACE FUNCTION deer_runtime.load_runtime_execution_authority(" in admission
    assert "CREATE OR REPLACE FUNCTION deer_runtime.claim_runtime_run(" in admission
    assert "CREATE OR REPLACE FUNCTION deer_runtime.takeover_runtime_run(" in admission
    assert "JAVA_CAPABILITY_STRUCTURED / 3.0" in admission
    assert "no Driver, route, Provider, UI, or role is enabled" in admission

    assert "admission_contract_version IN ('2.2', '3.0')" in permits
    assert "CREATE OR REPLACE FUNCTION deer_runtime.issue_runtime_external_permit(" in permits
    assert "CREATE OR REPLACE FUNCTION deer_runtime.consume_runtime_external_permit(" in permits
    assert "v_admission.admission_contract_version" in permits
    assert "v_intent.admission_contract_version NOT IN ('2.2', '3.0')" in permits
    assert "operation and consume semantics are unchanged" in permits

    combined = admission + permits
    assert "admission_contract_version ~" not in combined
    assert "admission_contract_version <> ''" not in combined
    assert combined.count("GRANT CREATE ON SCHEMA deer_runtime") == 2
    assert combined.count("REVOKE CREATE ON SCHEMA deer_runtime") == 2


def test_runtime_thread_source_identity_separates_conversation_and_task_step() -> None:
    migration = next(
        item for item in load_migrations() if item.version == "022"
    ).sql

    assert "ADD COLUMN source_kind VARCHAR(16) NOT NULL DEFAULT 'CONVERSATION'" in migration
    assert "ALTER COLUMN conversation_id DROP NOT NULL" in migration
    assert "ck_runtime_thread_source_identity" in migration
    assert "source_kind = 'CONVERSATION' AND conversation_id IS NOT NULL" in migration
    assert "source_kind = 'TASK_STEP'" in migration
    assert "p_runtime_thread_revision <> p_task_execution_generation" in migration
    assert "runtime-run-accepted-v2" in migration
    assert "runtime-run-accepted-v3" in migration
    assert "p_runtime_type <> 'JAVA_CAPABILITY_STRUCTURED'" in migration
    assert "v_thread.source_kind IS DISTINCT FROM p_source_kind" in migration
    assert "runtime_thread.source_kind" in migration
    assert "DROP FUNCTION deer_runtime.admit_runtime_run(" in migration
    assert "DROP FUNCTION deer_runtime.load_runtime_execution_authority(" in migration
    assert "TO dianlian_supervisor_run_admitter" in migration
    assert "TO dianlian_supervisor_executor" in migration
    assert "no structured Driver, Provider, UI, or production route is enabled" in migration


def test_structured_checkpoint_primitives_reuse_ledger_without_weakening_h12() -> None:
    migration = next(
        item for item in load_migrations() if item.version == "023"
    ).sql

    assert "CREATE FUNCTION deer_runtime.load_runtime_structured_checkpoint" in migration
    assert "CREATE FUNCTION deer_runtime.save_runtime_structured_checkpoint" in migration
    assert "structured-model-driver-state-v1" in migration
    assert "admission_contract_version = '3.0'" in migration
    assert "MODEL_RECEIPT_APPENDED" in migration
    assert "runtime_h12_checkpoint" in migration
    assert migration.count("FOR UPDATE") == 1
    assert (
        "checkpoint.checkpoint_id = p_expected_checkpoint_id\n         FOR UPDATE"
        not in migration
    )
    assert "CREATE OR REPLACE FUNCTION deer_runtime.save_runtime_h12_checkpoint" not in migration
    assert "TO dianlian_supervisor_executor" in migration
    assert "no Driver, Provider, UI, or production composition is enabled" in migration


def test_existing_supervisor_ledger_skips_bootstrap_sql(monkeypatch) -> None:
    migrations = load_migrations()
    executed_sql: list[str] = []

    class Result:
        def __init__(self, *, row=None, rows=None) -> None:
            self._row = row
            self._rows = rows

        def fetchone(self):
            return self._row

        def fetchall(self):
            return self._rows

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def transaction(self):
            return self

        def execute(self, sql, _parameters=None):
            executed_sql.append(sql)
            if "to_regclass" in sql:
                return Result(row=(True,))
            if "SELECT version, checksum" in sql:
                return Result(
                    rows=[
                        (migration.version, migration.checksum)
                        for migration in migrations
                    ]
                )
            return Result()

    monkeypatch.setattr(
        "dianlian_runtime.supervisor.migrations.psycopg.connect",
        lambda _dsn: Connection(),
    )

    assert apply_migrations("postgresql://example.invalid/supervisor") == []
    assert migrations[0].sql not in executed_sql


def test_s0_schema_freezes_single_authority_and_epoch_fences() -> None:
    migration = load_migrations()[1].sql

    for table in (
        "runtime_thread",
        "runtime_run",
        "runtime_run_control",
        "runtime_run_event",
        "runtime_checkpoint_ref",
    ):
        assert f"CREATE TABLE deer_runtime.{table}" in migration
    for active_status in (
        "QUEUED",
        "RUNNING",
        "WAITING_USER_INPUT",
        "WAITING_AUTH",
        "PAUSED",
        "CANCEL_REQUESTED",
        "CANCELLING",
    ):
        assert active_status in migration
    for terminal_status in (
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "CANCEL_OUTCOME_UNKNOWN",
    ):
        assert terminal_status in migration
    assert "CREATE UNIQUE INDEX uq_runtime_run_thread_active" in migration
    assert "UNIQUE (tenant_id, runtime_thread_id, idempotency_key)" in migration
    assert "UNIQUE (tenant_id, runtime_run_id, event_id)" in migration
    assert "lease_epoch" in migration
    assert "release_epoch" not in migration
    assert "DEFERRABLE INITIALLY DEFERRED" in migration
    assert "reject_append_only_mutation" in migration
    assert "predecessor_runtime_run_id <> runtime_run_id" in migration
    assert migration.count("BEFORE TRUNCATE") == 5
    assert "runtime_run must be admitted as QUEUED" in migration
    assert "upstream" not in migration.lower()
    assert "Activation: this migration does not register a RunStore" in migration


def test_s0_lease_primitives_use_database_time_and_single_epoch() -> None:
    migration = load_migrations()[2].sql

    for function_name in (
        "claim_runtime_run",
        "renew_runtime_run_lease",
        "takeover_runtime_run",
        "authorize_runtime_run",
    ):
        assert f"CREATE FUNCTION deer_runtime.{function_name}" in migration
    assert migration.count("SECURITY INVOKER") == 4
    assert "CLOCK_TIMESTAMP()" in migration
    assert "lease_until > v_now" in migration
    assert "lease_until <= v_now" in migration
    assert "lease_epoch = lease_epoch + 1" in migration
    assert "GREATEST(" in migration
    assert "status = 'RUNNING'" in migration
    assert "RUN_STARTED" in migration
    assert "RUN_TAKEN_OVER" in migration
    assert "release_epoch" not in migration


def test_s0_progress_primitives_keep_state_events_specialized() -> None:
    migration = load_migrations()[3].sql

    assert "CREATE FUNCTION deer_runtime.append_runtime_run_event" in migration
    assert "CREATE FUNCTION deer_runtime.record_runtime_checkpoint_ref" in migration
    assert migration.count("SECURITY INVOKER") == 2
    assert "p_event_type NOT IN ('PLAN_CREATED', 'STEP_STARTED', 'STEP_PROGRESS')" in migration
    assert "'CHECKPOINT_SAVED'" in migration
    assert "current_checkpoint_sequence_no" in migration
    assert "lease_until <= v_now" in migration
    assert "FOR UPDATE" in migration
    for forbidden_generic_event in (
        "RUN_STARTED",
        "RUN_TAKEN_OVER",
        "RUN_COMPLETED",
        "RUN_FAILED",
        "RUN_CANCELLED",
        "RUN_CANCEL_REQUESTED",
        "TOOL_COMPLETED",
        "ARTIFACT_CREATED",
    ):
        assert forbidden_generic_event not in migration.split(
            "CREATE FUNCTION deer_runtime.record_runtime_checkpoint_ref",
            maxsplit=1,
        )[0]


def test_s0_terminal_primitives_keep_cancel_and_terminal_mappings_explicit() -> None:
    migration = load_migrations()[4].sql

    for function_name in (
        "request_runtime_run_cancel",
        "begin_runtime_run_cancellation",
        "complete_runtime_run",
        "fail_runtime_run",
        "finish_runtime_run_cancellation",
    ):
        assert f"CREATE FUNCTION deer_runtime.{function_name}" in migration
    assert migration.count("SECURITY INVOKER") == 8
    assert "CLOCK_TIMESTAMP()" in migration
    assert "p_expected_run_version" in migration
    assert "control_type <> 'CANCEL'" in migration
    assert "p_terminal_status NOT IN ('CANCELLED', 'CANCEL_OUTCOME_UNKNOWN')" in migration
    for event_type in (
        "RUN_CANCEL_REQUESTED",
        "RUN_CANCELLING",
        "RUN_CANCELLED",
        "RUN_CANCEL_OUTCOME_UNKNOWN",
        "RUN_COMPLETED",
        "RUN_FAILED",
    ):
        assert event_type in migration
    for terminal_status in ("COMPLETED", "FAILED"):
        assert f"status = '{terminal_status}'" in migration
    assert "status = p_terminal_status" in migration
    assert "validate_runtime_terminal_consistency" in migration
    assert "validate_runtime_cancel_control_consistency" in migration
    assert "reject_post_terminal_runtime_event" in migration
    assert migration.count("CREATE CONSTRAINT TRIGGER") == 3
    assert migration.count("lease_until > v_now") == 5
    assert migration.count("lease_owner = NULL") >= 4
    assert migration.count("heartbeat_at = NULL") >= 4
    assert "release_epoch" not in migration
    assert "transition_runtime_run" not in migration


def test_cancel_controller_boundary_removes_worker_cancel_authority() -> None:
    migration = load_migrations()[15].sql

    assert "dianlian_supervisor_controller must be a sealed" in migration
    assert "REVOKE ALL PRIVILEGES ON ALL TABLES" in migration
    assert "REVOKE ALL PRIVILEGES (%I) ON TABLE" in migration
    assert "REVOKE ALL PRIVILEGES ON ALL SEQUENCES" in migration
    assert "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS" in migration
    assert "FROM PUBLIC, dianlian_supervisor_executor" in migration
    assert "TO dianlian_supervisor_controller" in migration
    assert "request_runtime_run_cancel" in migration


def test_h12_postgres_checkpoint_is_append_only_current_fenced_and_cas_saved() -> None:
    migration = load_migrations()[16].sql

    assert "CREATE TABLE deer_runtime.runtime_h12_checkpoint" in migration
    assert "CREATE FUNCTION deer_runtime.load_runtime_h12_checkpoint" in migration
    assert "CREATE FUNCTION deer_runtime.save_runtime_h12_checkpoint" in migration
    assert "BEFORE UPDATE OR DELETE" in migration
    assert "BEFORE TRUNCATE" in migration
    assert "v_new_state_version := p_expected_state_version + 1" in migration
    assert "v_run.current_checkpoint_id IS DISTINCT FROM p_expected_checkpoint_id" in migration
    assert "runtime_run.lease_until > CLOCK_TIMESTAMP()" in migration
    assert "v_run.lease_until <= v_now" in migration
    assert "CHECKPOINT_SAVED" in migration
    assert "governed-h12-state-v1" in migration
    assert "OCTET_LENGTH(state_json::TEXT) <= 1048576" in migration
    assert "GRANT SELECT, INSERT ON TABLE deer_runtime.runtime_h12_checkpoint" in migration
    assert migration.count("TO dianlian_supervisor_executor") == 2


def test_candidate_replacements_run_as_the_sealed_routine_owner() -> None:
    for migration in load_migrations()[13:15]:
        replacement = migration.sql.index(
            "CREATE OR REPLACE FUNCTION deer_runtime.select_next_runtime_run_candidate"
        )
        set_role = migration.sql.index(
            "SET LOCAL ROLE dianlian_supervisor_routine_owner"
        )
        reset_role = migration.sql.index("RESET ROLE")
        assert set_role < replacement < reset_role
        assert "GRANT CREATE ON SCHEMA deer_runtime" in migration.sql
        assert "REVOKE CREATE ON SCHEMA deer_runtime" in migration.sql


def test_s0_admission_primitive_is_atomic_exact_and_deliberately_narrow() -> None:
    migration = load_migrations()[5].sql

    assert "CREATE FUNCTION deer_runtime.admit_runtime_run" in migration
    assert migration.count("SECURITY INVOKER") == 1
    assert "SET search_path = pg_catalog, deer_runtime" in migration
    assert migration.count("pg_advisory_xact_lock") == 2
    assert "p_tenant_id::TEXT || ':' || p_runtime_thread_id::TEXT" in migration
    assert "p_task_step_id::TEXT || ':'" in migration
    assert "|| p_runtime_thread_revision::TEXT" in migration
    assert "7619104233" in migration
    assert "7619104234" in migration
    assert migration.count("FOR UPDATE") == 1
    for thread_identity in (
        "task_run_id",
        "task_step_id",
        "agent_instance_id",
        "user_id",
        "conversation_id",
        "source_message_id",
        "runtime_thread_revision",
        "runtime_type",
        "runtime_agent_name",
        "capability_version_id",
        "prompt_version_id",
        "model_policy_id",
        "budget_reservation_id",
        "input_artifact_ids",
    ):
        assert f"v_thread.{thread_identity} IS DISTINCT FROM p_{thread_identity}" in migration
    for run_identity in (
        "runtime_run_id",
        "task_step_id",
        "task_execution_generation",
        "operation_kind",
        "multitask_strategy",
        "request_hash",
        "predecessor_runtime_run_id",
        "expected_checkpoint_id",
        "runtime_version",
        "agent_name",
    ):
        assert f"v_run.{run_identity} IS DISTINCT FROM p_{run_identity}" in migration
    assert "p_operation_kind <> 'START'" in migration
    assert "p_multitask_strategy <> 'REJECT'" in migration
    assert migration.count("USING ERRCODE = '0A000'") == 2
    assert "USING ERRCODE = '22023'" in migration
    assert "USING ERRCODE = '23505'" in migration
    assert "'RUN_ACCEPTED', 1, 1, NULL, 0, NULL" in migration
    assert "p_expected_checkpoint_id, 2, 1, 1, 0, 0" in migration
    identity_conflict_position = migration.index(
        "RAISE EXCEPTION 'runtime Run admission identity conflict'"
    )
    active_reject_position = migration.index(
        "-- REJECT is deliberately represented as no admitted row"
    )
    assert identity_conflict_position < active_reject_position
    assert "Activation: no application component invokes this function" in migration
    assert "SAFE_QUEUE" not in migration
    assert "INTERRUPT" not in migration


def test_s0_privilege_boundary_exposes_only_controlled_primitives() -> None:
    migration = load_migrations()[6].sql

    primitive_names = (
        "admit_runtime_run",
        "claim_runtime_run",
        "renew_runtime_run_lease",
        "takeover_runtime_run",
        "authorize_runtime_run",
        "append_runtime_run_event",
        "record_runtime_checkpoint_ref",
        "request_runtime_run_cancel",
        "begin_runtime_run_cancellation",
        "complete_runtime_run",
        "fail_runtime_run",
        "finish_runtime_run_cancellation",
    )
    for primitive_name in primitive_names:
        assert f"deer_runtime.{primitive_name}(" in migration
    trigger_helpers = (
        "reject_append_only_mutation",
        "protect_runtime_run_identity",
        "validate_runtime_terminal_consistency",
        "reject_post_terminal_runtime_event",
        "validate_runtime_cancel_control_consistency",
    )
    assert migration.count("'deer_runtime.") == len(primitive_names) + len(trigger_helpers)
    assert "ALTER FUNCTION %s SECURITY DEFINER" in migration
    assert (
        "ALTER FUNCTION %s SET search_path TO pg_catalog, deer_runtime, pg_temp"
        in migration
    )
    assert (
        "ALTER FUNCTION %s OWNER TO dianlian_supervisor_routine_owner"
        in migration
    )
    assert (
        "GRANT EXECUTE ON FUNCTION %s TO dianlian_supervisor_executor"
        in migration
    )
    assert "GRANT USAGE ON SCHEMA deer_runtime TO dianlian_supervisor_executor" in migration
    assert "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA deer_runtime" in migration
    assert "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA deer_runtime FROM PUBLIC" in migration
    assert "runtime_thread\n    TO dianlian_supervisor_routine_owner" in migration
    assert "runtime_run\n    TO dianlian_supervisor_routine_owner" in migration
    assert "runtime_run_control\n    TO dianlian_supervisor_routine_owner" in migration
    assert "runtime_run_event\n    TO dianlian_supervisor_routine_owner" in migration
    assert "runtime_checkpoint_ref\n    TO dianlian_supervisor_routine_owner" in migration
    assert "schema_migration\n    TO dianlian_supervisor_routine_owner" not in migration
    assert "REVOKE CREATE ON SCHEMA deer_runtime" in migration
    assert "SET LOCAL ROLE dianlian_supervisor_routine_owner" in migration
    assert migration.count("REVOKE ALL PRIVILEGES ON FUNCTIONS FROM PUBLIC") == 2
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA deer_runtime\n    REVOKE ALL PRIVILEGES ON FUNCTIONS" not in migration
    assert "RESET ROLE" in migration
    assert migration.count("REVOKE ALL PRIVILEGES ON FUNCTION %s FROM PUBLIC") == 2
    assert migration.count("FROM pg_catalog.pg_auth_members") == 4
    assert "CREATE ROLE" not in migration
    for table_name in (
        "schema_migration",
        "runtime_thread",
        "runtime_run",
        "runtime_run_control",
        "runtime_run_event",
        "runtime_checkpoint_ref",
    ):
        assert (
            f"ON TABLE deer_runtime.{table_name}\n"
            "    TO dianlian_supervisor_executor"
        ) not in migration
    trigger_boundary = migration.split("DO $trigger_boundary$", maxsplit=1)[1]
    assert "GRANT EXECUTE" not in trigger_boundary
    for trigger_helper in trigger_helpers:
        assert f"'deer_runtime.{trigger_helper}()'" in trigger_boundary


def test_s0_candidate_discovery_is_read_only_compatible_and_fifo() -> None:
    migration = load_migrations()[7].sql

    assert "CREATE INDEX idx_runtime_run_queued_candidate" in migration
    assert (
        "runtime_version,\n        agent_name,\n        created_at,\n"
        "        tenant_id,\n        runtime_run_id"
    ) in migration
    assert "WHERE status = 'QUEUED'" in migration
    assert "CREATE FUNCTION deer_runtime.select_next_runtime_run_candidate" in migration
    assert "RETURNS TABLE" in migration
    assert "LANGUAGE plpgsql" in migration
    assert "STABLE" in migration
    assert "SECURITY DEFINER" in migration
    assert "SET search_path = pg_catalog, deer_runtime, pg_temp" in migration
    assert "runtime_run.runtime_version = p_runtime_version" in migration
    assert "runtime_run.agent_name = p_agent_name" in migration
    assert (
        "ORDER BY runtime_run.created_at,\n"
        "              runtime_run.tenant_id,\n"
        "              runtime_run.runtime_run_id"
    ) in migration
    assert "LIMIT 1" in migration
    assert "FOR UPDATE" not in migration
    for mutating_keyword in ("INSERT INTO", "UPDATE deer_runtime", "DELETE FROM"):
        assert mutating_keyword not in migration
    assert "claim_runtime_run" not in migration
    assert "runtime_run_event" not in migration
    assert "FROM PUBLIC" in migration
    assert "TO dianlian_supervisor_executor" in migration
    assert "OWNER TO dianlian_supervisor_routine_owner" in migration
    assert "GRANT CREATE ON SCHEMA deer_runtime" in migration
    assert "REVOKE CREATE ON SCHEMA deer_runtime" in migration
    assert migration.index("GRANT EXECUTE ON FUNCTION") < migration.index(
        "OWNER TO dianlian_supervisor_routine_owner"
    )
    assert "Activation: no service, application lifecycle, RunStore, or worker" in migration


def test_expired_running_candidate_reuses_read_only_takeover_path() -> None:
    migration = load_migrations()[13].sql

    assert "CREATE INDEX idx_runtime_run_expired_running_candidate" in migration
    assert "WHERE status = 'RUNNING'" in migration
    assert (
        "CREATE OR REPLACE FUNCTION deer_runtime.select_next_runtime_run_candidate"
        in migration
    )
    assert "runtime_run.status = 'QUEUED'" in migration
    assert "runtime_run.status = 'RUNNING'" in migration
    assert "runtime_run.lease_until <= STATEMENT_TIMESTAMP()" in migration
    assert (
        "ORDER BY CASE WHEN runtime_run.status = 'RUNNING' THEN 0 ELSE 1 END"
        in migration
    )
    assert "STABLE" in migration
    assert "FOR UPDATE" not in migration
    for mutating_keyword in ("INSERT INTO", "UPDATE deer_runtime", "DELETE FROM"):
        assert mutating_keyword not in migration


def test_expired_cancellation_candidate_reuses_read_only_takeover_path() -> None:
    migration = load_migrations()[14].sql

    assert "CREATE INDEX idx_runtime_run_expired_cancellation_candidate" in migration
    assert "WHERE status IN ('CANCEL_REQUESTED', 'CANCELLING')" in migration
    assert (
        "CREATE OR REPLACE FUNCTION deer_runtime.select_next_runtime_run_candidate"
        in migration
    )
    assert "runtime_run.status = 'QUEUED'" in migration
    assert "'RUNNING', 'CANCEL_REQUESTED', 'CANCELLING'" in migration
    assert "runtime_run.lease_until <= STATEMENT_TIMESTAMP()" in migration
    assert "WHEN runtime_run.status IN (" in migration
    assert "'CANCEL_REQUESTED', 'CANCELLING'" in migration
    assert "STABLE" in migration
    assert "FOR UPDATE" not in migration
    for mutating_keyword in ("INSERT INTO", "UPDATE deer_runtime", "DELETE FROM"):
        assert mutating_keyword not in migration


def test_s0_execution_authority_separates_running_from_cancellation() -> None:
    migration = load_migrations()[8].sql

    assert "CREATE FUNCTION deer_runtime.authorize_runtime_run_cancellation" in migration
    assert "CREATE FUNCTION deer_runtime.load_runtime_execution_authority" in migration
    assert migration.count("RETURNS TABLE") == 2
    assert migration.count("LANGUAGE plpgsql") == 2
    assert migration.count("VOLATILE") == 2
    assert "STABLE" not in migration
    assert migration.count("SECURITY DEFINER") == 2
    assert migration.count("SET search_path = pg_catalog, deer_runtime, pg_temp") == 2
    assert migration.count("USING ERRCODE = '22023'") == 2
    assert "runtime_run.status = 'CANCELLING'" in migration
    assert "runtime_run.status = 'RUNNING'" in migration
    assert migration.count("runtime_run.lease_until > CLOCK_TIMESTAMP()") == 2
    assert "runtime_run.lease_owner = p_lease_owner" in migration
    assert "runtime_run.lease_epoch = p_lease_epoch" in migration
    assert (
        "runtime_thread.tenant_id = runtime_run.tenant_id\n"
        "       AND runtime_thread.runtime_thread_id = runtime_run.runtime_thread_id\n"
        "       AND runtime_thread.task_step_id = runtime_run.task_step_id"
    ) in migration

    cancellation_columns = migration.split(
        "CREATE FUNCTION deer_runtime.authorize_runtime_run_cancellation",
        maxsplit=1,
    )[1].split("LANGUAGE plpgsql", maxsplit=1)[0]
    cancellation_return_columns = cancellation_columns.split(
        "RETURNS TABLE",
        maxsplit=1,
    )[1].strip()[1:-1].splitlines()
    cancellation_return_columns = [
        column for column in cancellation_return_columns if column.strip()
    ]
    assert len(cancellation_return_columns) == 10
    for column in (
        "tenant_id UUID",
        "runtime_run_id UUID",
        "runtime_thread_id UUID",
        "task_step_id UUID",
        "task_execution_generation BIGINT",
        "status VARCHAR(32)",
        "lease_owner VARCHAR(160)",
        "lease_epoch BIGINT",
        "run_version BIGINT",
        "cancel_requested_at TIMESTAMPTZ",
    ):
        assert column in cancellation_columns
    assert "lease_until" not in cancellation_columns

    execution_columns = migration.split(
        "CREATE FUNCTION deer_runtime.load_runtime_execution_authority",
        maxsplit=1,
    )[1].split("LANGUAGE plpgsql", maxsplit=1)[0]
    execution_return_columns = execution_columns.split(
        "RETURNS TABLE",
        maxsplit=1,
    )[1].strip()[1:-1].splitlines()
    execution_return_columns = [
        column for column in execution_return_columns if column.strip()
    ]
    assert len(execution_return_columns) == 27
    for column in (
        "tenant_id UUID",
        "runtime_run_id UUID",
        "runtime_thread_id UUID",
        "task_run_id UUID",
        "task_step_id UUID",
        "task_execution_generation BIGINT",
        "agent_instance_id UUID",
        "user_id UUID",
        "conversation_id UUID",
        "source_message_id UUID",
        "runtime_thread_revision BIGINT",
        "runtime_type VARCHAR(32)",
        "runtime_agent_name VARCHAR(128)",
        "capability_version_id UUID",
        "prompt_version_id UUID",
        "model_policy_id UUID",
        "budget_reservation_id UUID",
        "operation_kind VARCHAR(16)",
        "multitask_strategy VARCHAR(16)",
        "request_hash CHAR(64)",
        "idempotency_key VARCHAR(200)",
        "predecessor_runtime_run_id UUID",
        "expected_checkpoint_id VARCHAR(160)",
        "runtime_version VARCHAR(128)",
        "agent_name VARCHAR(128)",
        "lease_owner VARCHAR(160)",
        "lease_epoch BIGINT",
    ):
        assert column in execution_columns
    for forbidden_authority_column in (
        "lease_until",
        "heartbeat_at",
        "current_checkpoint_id",
        "input_artifact_ids",
        "JSONB",
    ):
        assert forbidden_authority_column not in execution_columns
    assert "runtime_run.*" not in migration
    assert "runtime_thread.*" not in migration
    for mutating_keyword in ("INSERT INTO", "UPDATE deer_runtime", "DELETE FROM"):
        assert mutating_keyword not in migration

    assert migration.count("FROM PUBLIC") == 2
    assert migration.count("TO dianlian_supervisor_executor") == 2
    assert migration.count("OWNER TO dianlian_supervisor_routine_owner") == 2
    assert migration.count("GRANT CREATE ON SCHEMA deer_runtime") == 1
    assert migration.count("REVOKE CREATE ON SCHEMA deer_runtime") == 1
    assert migration.rindex("GRANT EXECUTE ON FUNCTION") < migration.index(
        "OWNER TO dianlian_supervisor_routine_owner"
    )
    assert "Activation: no service, application lifecycle, RunStore, or worker" in migration


def test_s0_admission_binding_is_append_only_exact_and_fail_closed() -> None:
    migration = load_migrations()[9].sql

    precondition = migration.split(
        "DO $legacy_active_precondition$",
        maxsplit=1,
    )[1].split("$legacy_active_precondition$;", maxsplit=1)[0]
    table = migration.split(
        "CREATE TABLE deer_runtime.runtime_execution_admission_ref (",
        maxsplit=1,
    )[1].split("\n);", maxsplit=1)[0]
    assert migration.index("DO $legacy_active_precondition$") < migration.index(
        "CREATE TABLE deer_runtime.runtime_execution_admission_ref"
    )
    assert migration.index(
        "LOCK TABLE deer_runtime.runtime_run IN SHARE ROW EXCLUSIVE MODE"
    ) < migration.index("DO $legacy_active_precondition$")
    for active_status in (
        "QUEUED",
        "RUNNING",
        "WAITING_USER_INPUT",
        "WAITING_AUTH",
        "PAUSED",
        "CANCEL_REQUESTED",
        "CANCELLING",
    ):
        assert f"'{active_status}'" in precondition
    assert "USING ERRCODE = '55000'" in precondition

    for column in (
        "tenant_id UUID NOT NULL",
        "runtime_run_id UUID NOT NULL",
        "admission_contract_version VARCHAR(8) NOT NULL",
        "admission_snapshot_id UUID NOT NULL",
        "admission_snapshot_hash CHAR(64) NOT NULL",
    ):
        assert column in table
    assert table.count(" NOT NULL") == 5
    assert "PRIMARY KEY (tenant_id, runtime_run_id)" in table
    assert "REFERENCES deer_runtime.runtime_run (tenant_id, runtime_run_id)" in table
    assert "UNIQUE (admission_snapshot_id)" in table
    assert "admission_contract_version = '2.2'" in table
    assert "admission_snapshot_hash ~ '^[0-9a-f]{64}$'" in table
    assert "00000000-0000-0000-0000-000000000000" in table
    assert "created_at" not in table
    assert "JSONB" not in table
    assert "'2.0'" not in migration
    assert "'2.1'" not in migration

    assert migration.count(
        "EXECUTE FUNCTION deer_runtime.reject_append_only_mutation()"
    ) == 2
    assert "BEFORE UPDATE OR DELETE ON deer_runtime.runtime_execution_admission_ref" in migration
    assert "BEFORE TRUNCATE ON deer_runtime.runtime_execution_admission_ref" in migration
    assert "GRANT TRIGGER ON TABLE deer_runtime.runtime_execution_admission_ref" in migration
    assert "REVOKE TRIGGER ON TABLE deer_runtime.runtime_execution_admission_ref" in migration
    assert migration.count("GRANT CREATE ON SCHEMA deer_runtime") == 1
    assert migration.count("REVOKE CREATE ON SCHEMA deer_runtime") == 1
    assert migration.index("SET LOCAL ROLE dianlian_supervisor_routine_owner") < migration.index(
        "CREATE TRIGGER trg_runtime_execution_admission_ref_append_only"
    )
    assert migration.rindex("RESET ROLE") < migration.index(
        "REVOKE TRIGGER ON TABLE deer_runtime.runtime_execution_admission_ref"
    )

    assert "DROP FUNCTION deer_runtime.admit_runtime_run(" in migration
    assert "DROP FUNCTION deer_runtime.select_next_runtime_run_candidate" in migration
    assert "DROP FUNCTION deer_runtime.load_runtime_execution_authority" in migration
    assert migration.count(") RESTRICT;") == 3
    assert "CASCADE" not in migration
    assert "ON CONFLICT" not in migration
    assert "p_admission_contract_version VARCHAR" in migration
    assert "p_admission_snapshot_id UUID" in migration
    assert "p_admission_snapshot_hash CHAR(64)" in migration
    assert "runtime Run admission receipt idempotency conflict" in migration
    assert migration.index(
        "INSERT INTO deer_runtime.runtime_execution_admission_ref"
    ) < migration.index("INSERT INTO deer_runtime.runtime_run_event", migration.index(
        "INSERT INTO deer_runtime.runtime_execution_admission_ref"
    ))

    assert (
        "select_next_runtime_run_candidate(VARCHAR, VARCHAR, VARCHAR)" in migration
    )
    assert "admission_ref.admission_contract_version = p_admission_contract_version" in migration
    assert migration.count(
        "FROM deer_runtime.runtime_execution_admission_ref\n"
        "         WHERE tenant_id = p_tenant_id"
    ) == 3
    assert migration.count("CREATE OR REPLACE FUNCTION") == 2

    execution_columns = migration.split(
        "CREATE FUNCTION deer_runtime.load_runtime_execution_authority",
        maxsplit=1,
    )[1].split("LANGUAGE plpgsql", maxsplit=1)[0]
    execution_return_columns = execution_columns.split(
        "RETURNS TABLE",
        maxsplit=1,
    )[1].strip()[1:-1].splitlines()
    execution_return_columns = [
        column for column in execution_return_columns if column.strip()
    ]
    assert len(execution_return_columns) == 30
    assert "admission_contract_version VARCHAR(8)" in execution_columns
    assert "admission_snapshot_id UUID" in execution_columns
    assert "admission_snapshot_hash CHAR(64)" in execution_columns
    assert "JOIN deer_runtime.runtime_execution_admission_ref AS admission_ref" in migration
    assert "Activation: only admission contract 2.2 is accepted" in migration


def test_supervisor_migration_cli_requires_its_own_environment_dsn(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "DIANLIAN_CONTEXT_DATABASE_DSN",
        "postgresql://example.invalid/context",
    )
    monkeypatch.delenv("DIANLIAN_SUPERVISOR_MIGRATION_DATABASE_DSN", raising=False)

    with pytest.raises(
        SystemExit,
        match="DIANLIAN_SUPERVISOR_MIGRATION_DATABASE_DSN is required",
    ):
        main([])


def test_s0_external_permits_freeze_logical_intent_and_one_shot_authority() -> None:
    migration = load_migrations()[10].sql

    for table_name in (
        "runtime_external_intent",
        "runtime_external_permit_attempt",
        "runtime_external_permit_event",
    ):
        assert f"CREATE TABLE deer_runtime.{table_name}" in migration
    for operation_kind in (
        "ADMISSION_RESOLVE",
        "MODEL_INVOKE",
        "TOOL_INVOKE",
    ):
        assert operation_kind in migration
    assert "PRIMARY KEY (tenant_id, runtime_run_id, operation_kind, intent_id)" in migration
    assert "admission_contract_version = '2.2'" in migration
    assert "WHERE status = 'CONSUMED'" in migration
    assert "status IN ('ISSUED', 'CONSUMED')" in migration
    assert "requested_ttl_seconds BETWEEN 1 AND 60" in migration
    assert "expires_at > issued_at" in migration
    assert "consumed_at < expires_at" in migration
    assert "CREATE FUNCTION deer_runtime.issue_runtime_external_permit" in migration
    assert "CREATE FUNCTION deer_runtime.consume_runtime_external_permit" in migration
    assert migration.count("RETURNS TABLE") == 2
    assert migration.count("SECURITY DEFINER") == 3
    assert migration.count("SET search_path = pg_catalog, deer_runtime, pg_temp") == 3
    assert migration.count("FOR UPDATE") >= 6
    assert "FROM deer_runtime.runtime_external_intent AS external_intent\n" in migration
    assert "external_intent.intent_id = p_intent_id\n     FOR UPDATE" not in migration
    assert "v_expires_at > v_run.lease_until" in migration
    assert "v_attempt.expires_at <= v_now" in migration
    assert "NEW.consumed_at >= OLD.expires_at" in migration
    assert "permit_attempt.status = 'CONSUMED'" in migration
    assert "live runtime external permit already exists for this lease epoch" in migration
    assert "runtime external permit consume idempotency conflict" in migration
    assert "finalize" not in migration.lower()
    assert "outcome" not in migration.lower()

    issue_definition = migration.split(
        "CREATE FUNCTION deer_runtime.issue_runtime_external_permit", maxsplit=1
    )[1].split("CREATE FUNCTION deer_runtime.consume_runtime_external_permit", maxsplit=1)[0]
    consume_definition = migration.split(
        "CREATE FUNCTION deer_runtime.consume_runtime_external_permit", maxsplit=1
    )[1].split("REVOKE ALL PRIVILEGES ON FUNCTION", maxsplit=1)[0]
    for definition in (issue_definition, consume_definition):
        return_columns = definition.split("RETURNS TABLE", maxsplit=1)[1]
        return_columns = return_columns.split("LANGUAGE plpgsql", maxsplit=1)[0]
        normalized_columns = return_columns.strip()[1:-1]
        assert len([line for line in normalized_columns.splitlines() if line.strip()]) == 24
        for binding in (
            "admission_snapshot_id UUID",
            "admission_snapshot_hash CHAR(64)",
            "task_execution_generation BIGINT",
            "lease_owner VARCHAR(160)",
            "lease_epoch BIGINT",
            "intent_id UUID",
            "request_hash CHAR(64)",
        ):
            assert binding in return_columns


def test_s0_external_permit_privileges_separate_issue_from_consume() -> None:
    migration = load_migrations()[10].sql

    assert "CREATE ROLE" not in migration
    assert "dianlian_supervisor_permit_authorizer must be a restricted NOLOGIN NOINHERIT role" in migration
    assert "FROM pg_catalog.pg_auth_members" in migration
    assert "roleid = v_authorizer.oid" in migration
    assert "AND admin_option" in migration
    assert "NOT set_option" not in migration
    assert "REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA deer_runtime" in migration
    assert "REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA deer_runtime" in migration
    assert "REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA deer_runtime" in migration
    assert "GRANT UPDATE (status, consume_event_id, consumed_by, consumed_at, updated_at)" in migration
    assert "GRANT UPDATE ON TABLE deer_runtime.runtime_external_permit_attempt" not in migration
    assert "GRANT USAGE ON SCHEMA deer_runtime TO dianlian_supervisor_permit_authorizer" in migration
    assert (
        "issue_runtime_external_permit(\n"
        "    UUID, UUID, VARCHAR, BIGINT, UUID, VARCHAR, UUID, CHAR(64), INTEGER, UUID\n"
        ") TO dianlian_supervisor_executor"
    ) in migration
    assert (
        "consume_runtime_external_permit(\n"
        "    UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),\n"
        "    VARCHAR, UUID, CHAR(64), UUID, VARCHAR\n"
        ") TO dianlian_supervisor_permit_authorizer"
    ) in migration
    assert "issue_runtime_external_permit" not in migration.split(
        ") TO dianlian_supervisor_permit_authorizer", maxsplit=1
    )[0].rsplit("GRANT EXECUTE ON FUNCTION", maxsplit=1)[-1]
    for table_name in (
        "runtime_external_intent",
        "runtime_external_permit_attempt",
        "runtime_external_permit_event",
    ):
        assert f"REVOKE ALL PRIVILEGES ON TABLE deer_runtime.{table_name}" in migration
        assert f"GRANT TRIGGER ON TABLE deer_runtime.{table_name}" in migration
        assert f"REVOKE TRIGGER ON TABLE deer_runtime.{table_name}" in migration
    assert migration.count("BEFORE TRUNCATE") == 3
    assert "runtime_external_permit_attempt lifecycle mutation is invalid" in migration
    assert (
        "REVOKE ALL PRIVILEGES ON FUNCTION\n"
        "    deer_runtime.protect_runtime_external_permit_attempt()\n"
        "    FROM PUBLIC, dianlian_supervisor_executor"
    ) in migration
    assert (
        "ALTER FUNCTION deer_runtime.protect_runtime_external_permit_attempt()\n"
        "    OWNER TO dianlian_supervisor_routine_owner"
    ) in migration
    assert migration.rindex("RESET ROLE") < migration.index(
        "REVOKE TRIGGER ON TABLE deer_runtime.runtime_external_intent"
    )


def test_s0_external_permit_current_authority_wrapper_is_exact_and_serialized() -> None:
    migration = load_migrations()[11].sql

    assert (
        "CREATE FUNCTION deer_runtime.consume_and_authorize_runtime_external_permit"
        in migration
    )
    assert migration.count("RETURNS TABLE") == 1
    assert migration.count("SECURITY DEFINER") == 1
    assert migration.count("SET search_path = pg_catalog, deer_runtime, pg_temp") == 1
    assert "invalid runtime external permit consume and authorize arguments" in migration
    for validation in (
        "p_runtime_external_permit_id = '00000000-0000-0000-0000-000000000000'::UUID",
        "p_task_execution_generation IS NULL OR p_task_execution_generation < 1",
        "p_lease_owner IS NULL OR BTRIM(p_lease_owner) = ''",
        "p_lease_epoch IS NULL OR p_lease_epoch < 1",
        "p_admission_snapshot_hash !~ '^[0-9a-f]{64}$'",
        "p_operation_kind NOT IN ('ADMISSION_RESOLVE', 'MODEL_INVOKE', 'TOOL_INVOKE')",
        "p_request_hash IS NULL OR p_request_hash !~ '^[0-9a-f]{64}$'",
        "p_consumed_by IS NULL OR BTRIM(p_consumed_by) = ''",
    ):
        assert validation in migration
    assert "FROM deer_runtime.runtime_run AS runtime_run" in migration
    assert "FOR UPDATE" in migration
    assert "v_now := CLOCK_TIMESTAMP()" in migration
    for current_fence in (
        "v_run.status <> 'RUNNING'",
        "v_run.task_execution_generation IS DISTINCT FROM p_task_execution_generation",
        "v_run.lease_owner IS DISTINCT FROM p_lease_owner",
        "v_run.lease_epoch IS DISTINCT FROM p_lease_epoch",
        "v_run.lease_until IS NULL OR v_run.lease_until <= v_now",
    ):
        assert current_fence in migration
    assert "FROM deer_runtime.consume_runtime_external_permit(" in migration

    return_columns = migration.split("RETURNS TABLE", maxsplit=1)[1]
    return_columns = return_columns.split("LANGUAGE plpgsql", maxsplit=1)[0]
    normalized_columns = return_columns.strip()[1:-1]
    assert len([line for line in normalized_columns.splitlines() if line.strip()]) == 24


def test_s0_external_permit_authorizer_can_execute_only_the_current_wrapper() -> None:
    migration = load_migrations()[11].sql
    signature = (
        "UUID, UUID, UUID, BIGINT, VARCHAR, BIGINT, UUID, CHAR(64),\n"
        "    VARCHAR, UUID, CHAR(64), UUID, VARCHAR"
    )

    assert (
        "REVOKE ALL PRIVILEGES ON FUNCTION deer_runtime.consume_runtime_external_permit(\n"
        f"    {signature}\n"
        ") FROM PUBLIC, dianlian_supervisor_executor, "
        "dianlian_supervisor_permit_authorizer"
    ) in migration
    assert (
        "GRANT EXECUTE ON FUNCTION\n"
        "    deer_runtime.consume_and_authorize_runtime_external_permit("
        in migration
    )
    wrapper_grant = migration.rsplit("GRANT EXECUTE ON FUNCTION", maxsplit=1)[1]
    assert "consume_and_authorize_runtime_external_permit" in wrapper_grant
    assert ") TO dianlian_supervisor_permit_authorizer" in wrapper_grant
    assert "consume_runtime_external_permit(" not in wrapper_grant.replace(
        "consume_and_authorize_runtime_external_permit(", ""
    )
    assert migration.rindex("RESET ROLE") < migration.rindex(
        "REVOKE CREATE ON SCHEMA deer_runtime FROM dianlian_supervisor_routine_owner"
    )


def test_s0_external_operation_outcome_barrier_is_dormant_and_one_shot() -> None:
    migration = load_migrations()[12].sql

    legacy_precondition = migration.split(
        "DO $legacy_consumed_precondition$", maxsplit=1
    )[1].split("$legacy_consumed_precondition$;", maxsplit=1)[0]
    assert migration.index(
        "LOCK TABLE deer_runtime.runtime_external_permit_attempt\n"
        "    IN SHARE ROW EXCLUSIVE MODE"
    ) < migration.index("DO $legacy_consumed_precondition$")
    assert "operation_kind IN ('MODEL_INVOKE', 'TOOL_INVOKE')" in legacy_precondition
    assert "permit_attempt.status = 'CONSUMED'" in legacy_precondition
    assert "USING ERRCODE = '55000'" in legacy_precondition
    assert (
        "FROM PUBLIC, dianlian_supervisor_executor, "
        "dianlian_supervisor_permit_authorizer, "
        "dianlian_supervisor_dispatch_authorizer, "
        "dianlian_supervisor_outcome_reconciler"
    ) in migration

    assert "CREATE TABLE deer_runtime.runtime_external_operation_attempt" in migration
    assert "CREATE TABLE deer_runtime.runtime_external_operation_event" in migration
    assert "status IN (\n        'DISPATCH_ARMED', 'NOT_DISPATCHED', 'SUCCEEDED'" in migration
    assert "'FAILED_CONFIRMED', 'OUTCOME_UNKNOWN'" in migration
    assert "operation_kind IN ('MODEL_INVOKE', 'TOOL_INVOKE')" in migration
    assert "JAVA_CANONICAL_FACT" in migration
    for forbidden_payload in ("prompt", "credential", "receipt_text", "response_body"):
        assert forbidden_payload not in migration.lower()

    arm = migration.split(
        "CREATE FUNCTION deer_runtime.consume_and_arm_runtime_external_dispatch",
        maxsplit=1,
    )[1].split("REVOKE ALL PRIVILEGES ON FUNCTION", maxsplit=1)[0]
    assert "'GRANTED_NOW'::VARCHAR(24)" in arm
    assert "'DO_NOT_DISPATCH'::VARCHAR(24)" in arm
    assert arm.index("FROM deer_runtime.runtime_run AS runtime_run") < arm.index(
        "FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt"
    ) < arm.index(
        "FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt"
    )
    assert arm.index("'DO_NOT_DISPATCH'::VARCHAR(24)") < arm.index(
        "v_run.status <> 'RUNNING'"
    )
    assert "p_operation_kind NOT IN ('MODEL_INVOKE', 'TOOL_INVOKE')" in arm
    assert "status IN ('DISPATCH_ARMED', 'OUTCOME_UNKNOWN')" in arm
    assert "FROM deer_runtime.consume_runtime_external_permit(" in arm

    old_wrapper = migration.split(
        "CREATE OR REPLACE FUNCTION deer_runtime.consume_and_authorize_runtime_external_permit",
        maxsplit=1,
    )[1].split(
        "CREATE FUNCTION deer_runtime.consume_and_arm_runtime_external_dispatch",
        maxsplit=1,
    )[0]
    assert "p_operation_kind IS DISTINCT FROM 'ADMISSION_RESOLVE'" in old_wrapper

    for function_name in (
        "record_runtime_external_operation_outcome",
        "reconcile_runtime_external_operation_outcome",
    ):
        definition = migration.split(
            f"CREATE FUNCTION deer_runtime.{function_name}", maxsplit=1
        )[1].split("CREATE FUNCTION", maxsplit=1)[0]
        assert definition.index("FROM deer_runtime.runtime_run AS runtime_run") < definition.index(
            "FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt"
        ) < definition.index(
            "FROM deer_runtime.runtime_external_operation_attempt AS operation_attempt"
        )
        assert "v_run.lease_until" not in definition
    assert "p_source_fact_version <= v_operation.source_fact_version" in migration
    assert "unknown_event.event_id = p_expected_unknown_event_id" in migration

    for terminal_name in (
        "complete_runtime_run",
        "fail_runtime_run",
        "finish_runtime_run_cancellation",
    ):
        assert f"CREATE OR REPLACE FUNCTION deer_runtime.{terminal_name}" in migration
    assert "p_failure_code <> 'EXTERNAL_OUTCOME_UNKNOWN'" in migration
    assert "p_terminal_status = 'CANCELLED'" in migration
    assert migration.count("status IN ('DISPATCH_ARMED', 'OUTCOME_UNKNOWN')") >= 4

    for role, routines in (
        ("dianlian_supervisor_permit_authorizer", ("consume_and_authorize_runtime_external_permit",)),
        ("dianlian_supervisor_dispatch_authorizer", ("consume_and_arm_runtime_external_dispatch",)),
        (
            "dianlian_supervisor_outcome_reconciler",
            (
                "record_runtime_external_operation_outcome",
                "reconcile_runtime_external_operation_outcome",
            ),
        ),
        ("dianlian_supervisor_executor", ("load_runtime_external_operation_barrier",)),
    ):
        for routine in routines:
            assert f"deer_runtime.{routine}(" in migration
            grant_start = migration.index(
                f"GRANT EXECUTE ON FUNCTION\n    deer_runtime.{routine}("
            )
            grant_end = migration.index(";", grant_start)
            assert f") TO {role}" in migration[grant_start:grant_end]
    assert "Activation: no worker, HTTP endpoint, Java client, model, or tool dispatch" in migration

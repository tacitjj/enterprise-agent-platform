from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from typing import Any, Protocol

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from dianlian_runtime.supervisor.authorizer_contracts import (
    ExternalOperationOutcomeApiResult,
    ExternalOperationOutcomeRecordRequest,
    ExternalOperationOutcomeReconcileRequest,
)
from dianlian_runtime.supervisor.contracts import (
    ExternalOperation,
    ExternalOperationAttemptStatus,
    ExternalOutcomeEvidenceKind,
    PrimitiveOutcome,
    PrimitiveResult,
    ReconcileRuntimeExternalOperationOutcomeRequest,
    RecordRuntimeExternalOperationOutcomeRequest,
    RuntimeExternalOperationAttemptFact,
    SupervisorCommandConflict,
    SupervisorIntegrityOrContractViolation,
    SupervisorInvalidCommand,
    SupervisorOutcomeUnknown,
    SupervisorPermissionBoundaryMisconfigured,
    SupervisorTransientConflict,
    SupervisorUnavailable,
    SupervisorUnsupportedCommand,
)
from dianlian_runtime.supervisor.postgres import PostgresRunSupervisorRepository


LOGGER = logging.getLogger(__name__)
_RECORD_WRAPPER = (
    "deer_runtime.record_runtime_external_operation_outcome("
    "uuid,uuid,uuid,bigint,varchar,bigint,uuid,character,varchar,uuid,"
    "character,uuid,varchar,uuid,bigint,character,varchar,varchar,"
    "character,varchar)"
)
_RECONCILE_WRAPPER = (
    "deer_runtime.reconcile_runtime_external_operation_outcome("
    "uuid,uuid,uuid,bigint,varchar,bigint,uuid,character,varchar,uuid,"
    "character,uuid,uuid,varchar,uuid,bigint,character,varchar,varchar,"
    "character,varchar)"
)
_READINESS_SQL = """
SELECT
    current_user AS login_name,
    login_role.rolcanlogin AS login_can_login,
    login_role.rolinherit AS login_inherits,
    NOT (
        login_role.rolsuper
        OR login_role.rolcreatedb
        OR login_role.rolcreaterole
        OR login_role.rolreplication
        OR login_role.rolbypassrls
    ) AS login_is_restricted,
    (
        SELECT COUNT(*) = 1
          FROM pg_catalog.pg_auth_members AS membership
         WHERE membership.member = login_role.oid
    ) AS has_exact_membership_count,
    EXISTS (
        SELECT 1
          FROM pg_catalog.pg_auth_members AS membership
          JOIN pg_catalog.pg_roles AS granted_role
            ON granted_role.oid = membership.roleid
         WHERE membership.member = login_role.oid
           AND granted_role.rolname = 'dianlian_supervisor_outcome_reconciler'
           AND NOT membership.admin_option
           AND membership.inherit_option
           AND membership.set_option
    ) AS has_exact_outcome_reconciler_membership,
    EXISTS (
        SELECT 1
          FROM pg_catalog.pg_roles AS boundary_role
         WHERE boundary_role.rolname = 'dianlian_supervisor_outcome_reconciler'
           AND NOT boundary_role.rolcanlogin
           AND NOT boundary_role.rolinherit
           AND NOT boundary_role.rolsuper
           AND NOT boundary_role.rolcreatedb
           AND NOT boundary_role.rolcreaterole
           AND NOT boundary_role.rolreplication
           AND NOT boundary_role.rolbypassrls
           AND NOT EXISTS (
               SELECT 1
                 FROM pg_catalog.pg_auth_members AS inherited_membership
                WHERE inherited_membership.member = boundary_role.oid
           )
    ) AS outcome_reconciler_role_is_sealed,
    pg_has_role(
        current_user,
        'dianlian_supervisor_outcome_reconciler',
        'MEMBER'
    ) AS is_outcome_reconciler,
    pg_has_role(current_user, 'dianlian_supervisor_permit_authorizer', 'MEMBER')
        AS is_permit_authorizer,
    pg_has_role(current_user, 'dianlian_supervisor_dispatch_authorizer', 'MEMBER')
        AS is_dispatch_authorizer,
    pg_has_role(current_user, 'dianlian_supervisor_executor', 'MEMBER')
        AS is_executor,
    has_schema_privilege(current_user, 'deer_runtime', 'USAGE') AS has_schema_usage,
    has_schema_privilege(current_user, 'deer_runtime', 'CREATE') AS has_schema_create,
    to_regprocedure(%s) IS NOT NULL AS record_wrapper_exists,
    to_regprocedure(%s) IS NOT NULL AS reconcile_wrapper_exists,
    has_function_privilege(current_user, to_regprocedure(%s), 'EXECUTE')
        AS can_execute_record_wrapper,
    has_function_privilege(current_user, to_regprocedure(%s), 'EXECUTE')
        AS can_execute_reconcile_wrapper,
    NOT EXISTS (
        SELECT 1
          FROM pg_catalog.pg_proc AS procedure
          JOIN pg_catalog.pg_namespace AS procedure_namespace
            ON procedure_namespace.oid = procedure.pronamespace
         WHERE procedure_namespace.nspname = 'deer_runtime'
           AND procedure.oid NOT IN (to_regprocedure(%s), to_regprocedure(%s))
           AND has_function_privilege(current_user, procedure.oid, 'EXECUTE')
    ) AS has_no_other_function_execute,
    NOT EXISTS (
        SELECT 1
          FROM pg_catalog.pg_class AS relation
          JOIN pg_catalog.pg_namespace AS relation_namespace
            ON relation_namespace.oid = relation.relnamespace
          CROSS JOIN unnest(ARRAY[
              'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE',
              'REFERENCES', 'TRIGGER'
          ]) AS requested_privilege(privilege_name)
         WHERE relation_namespace.nspname = 'deer_runtime'
           AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
           AND has_table_privilege(
               current_user,
               relation.oid,
               requested_privilege.privilege_name
           )
    ) AS has_no_relation_privileges,
    NOT EXISTS (
        SELECT 1
          FROM pg_catalog.pg_class AS relation
          JOIN pg_catalog.pg_namespace AS relation_namespace
            ON relation_namespace.oid = relation.relnamespace
          JOIN pg_catalog.pg_attribute AS relation_attribute
            ON relation_attribute.attrelid = relation.oid
          CROSS JOIN unnest(ARRAY[
              'SELECT', 'INSERT', 'UPDATE', 'REFERENCES'
          ]) AS requested_column_privilege(privilege_name)
         WHERE relation_namespace.nspname = 'deer_runtime'
           AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
           AND relation_attribute.attnum > 0
           AND NOT relation_attribute.attisdropped
           AND has_column_privilege(
               current_user,
               relation.oid,
               relation_attribute.attnum,
               requested_column_privilege.privilege_name
           )
    ) AS has_no_column_privileges,
    NOT EXISTS (
        SELECT 1
          FROM pg_catalog.pg_class AS sequence_relation
          JOIN pg_catalog.pg_namespace AS sequence_namespace
            ON sequence_namespace.oid = sequence_relation.relnamespace
          CROSS JOIN unnest(ARRAY[
              'SELECT', 'USAGE', 'UPDATE'
          ]) AS requested_sequence_privilege(privilege_name)
         WHERE sequence_namespace.nspname = 'deer_runtime'
           AND sequence_relation.relkind = 'S'
           AND has_sequence_privilege(
               current_user,
               sequence_relation.oid,
               requested_sequence_privilege.privilege_name
           )
    ) AS has_no_sequence_privileges
  FROM pg_catalog.pg_roles AS login_role
 WHERE login_role.rolname = current_user
"""


class ExternalOperationOutcomeInvalidCommand(RuntimeError):
    pass


class ExternalOperationOutcomeConflict(RuntimeError):
    pass


class ExternalOperationOutcomeUnavailable(RuntimeError):
    pass


class ExternalOperationOutcomeRepository(Protocol):
    def record_external_operation_outcome(
        self,
        request: RecordRuntimeExternalOperationOutcomeRequest,
    ) -> PrimitiveResult[RuntimeExternalOperationAttemptFact]: ...

    def reconcile_external_operation_outcome(
        self,
        request: ReconcileRuntimeExternalOperationOutcomeRequest,
    ) -> PrimitiveResult[RuntimeExternalOperationAttemptFact]: ...


class ExternalOperationOutcomeService(Protocol):
    @property
    def ready(self) -> bool: ...

    def record(
        self,
        request: ExternalOperationOutcomeRecordRequest,
        *,
        recorded_by: str,
    ) -> ExternalOperationOutcomeApiResult: ...

    def reconcile(
        self,
        request: ExternalOperationOutcomeReconcileRequest,
        *,
        recorded_by: str,
    ) -> ExternalOperationOutcomeApiResult: ...


class UnavailableExternalOperationOutcomeService:
    @property
    def ready(self) -> bool:
        return False

    def record(
        self,
        request: ExternalOperationOutcomeRecordRequest,
        *,
        recorded_by: str,
    ) -> ExternalOperationOutcomeApiResult:
        del request, recorded_by
        raise ExternalOperationOutcomeUnavailable(
            "external operation outcome reconciler is unavailable"
        )

    def reconcile(
        self,
        request: ExternalOperationOutcomeReconcileRequest,
        *,
        recorded_by: str,
    ) -> ExternalOperationOutcomeApiResult:
        del request, recorded_by
        raise ExternalOperationOutcomeUnavailable(
            "external operation outcome reconciler is unavailable"
        )


ConnectionFactory = Callable[[], Connection[dict[str, Any]]]


class PostgresExternalOperationOutcomeService:
    """Restricted outcome reconciler; no other Supervisor capability is accepted."""

    def __init__(
        self,
        repository: ExternalOperationOutcomeRepository,
        readiness_connection_factory: ConnectionFactory,
    ) -> None:
        if not callable(readiness_connection_factory):
            raise TypeError("readiness_connection_factory must be callable")
        self._repository = repository
        self._readiness_connection_factory = readiness_connection_factory
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def start(self) -> None:
        connection: Connection[dict[str, Any]] | None = None
        try:
            connection = self._readiness_connection_factory()
            row = connection.execute(
                _READINESS_SQL,
                (
                    _RECORD_WRAPPER,
                    _RECONCILE_WRAPPER,
                    _RECORD_WRAPPER,
                    _RECONCILE_WRAPPER,
                    _RECORD_WRAPPER,
                    _RECONCILE_WRAPPER,
                ),
            ).fetchone()
            self._ready = _readiness_row_is_valid(row)
        except Exception as exception:
            self._ready = False
            LOGGER.warning(
                "External operation outcome reconciler database is not ready; error_type=%s",
                type(exception).__name__,
            )
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def close(self) -> None:
        self._ready = False

    def record(
        self,
        request: ExternalOperationOutcomeRecordRequest,
        *,
        recorded_by: str,
    ) -> ExternalOperationOutcomeApiResult:
        self._require_ready_and_actor(recorded_by)
        try:
            command = RecordRuntimeExternalOperationOutcomeRequest(
                **_common_command_arguments(request),
                outcome_event_id=request.outcome_event_id,
                outcome_status=ExternalOperationAttemptStatus(request.outcome_status),
                source_fact_id=request.source_fact_id,
                source_fact_version=request.source_fact_version,
                source_fact_hash=request.source_fact_hash,
                outcome_code=request.outcome_code,
                evidence_kind=ExternalOutcomeEvidenceKind.JAVA_CANONICAL_FACT,
                result_hash=request.result_hash,
                recorded_by=recorded_by,
            )
            result = self._repository.record_external_operation_outcome(command)
        except Exception as exception:
            return self._translate_failure(exception)
        return self._map_record_result(result, command)

    def reconcile(
        self,
        request: ExternalOperationOutcomeReconcileRequest,
        *,
        recorded_by: str,
    ) -> ExternalOperationOutcomeApiResult:
        self._require_ready_and_actor(recorded_by)
        try:
            command = ReconcileRuntimeExternalOperationOutcomeRequest(
                **_common_command_arguments(request),
                expected_unknown_event_id=request.expected_unknown_event_id,
                reconcile_event_id=request.reconcile_event_id,
                outcome_status=ExternalOperationAttemptStatus(request.outcome_status),
                source_fact_id=request.source_fact_id,
                source_fact_version=request.source_fact_version,
                source_fact_hash=request.source_fact_hash,
                outcome_code=request.outcome_code,
                evidence_kind=ExternalOutcomeEvidenceKind.JAVA_CANONICAL_FACT,
                result_hash=request.result_hash,
                recorded_by=recorded_by,
            )
            result = self._repository.reconcile_external_operation_outcome(command)
        except Exception as exception:
            return self._translate_failure(exception)
        return self._map_reconcile_result(result, command)

    def _require_ready_and_actor(self, recorded_by: str) -> None:
        if not self._ready:
            raise ExternalOperationOutcomeUnavailable(
                "external operation outcome reconciler is unavailable"
            )
        if (
            not isinstance(recorded_by, str)
            or not recorded_by.strip()
            or recorded_by != recorded_by.strip()
            or len(recorded_by) > 160
        ):
            raise ExternalOperationOutcomeInvalidCommand(
                "external operation outcome request is invalid"
            )

    def _translate_failure(self, exception: Exception) -> ExternalOperationOutcomeApiResult:
        if isinstance(
            exception,
            (TypeError, ValueError, SupervisorInvalidCommand, SupervisorUnsupportedCommand),
        ):
            raise ExternalOperationOutcomeInvalidCommand(
                "external operation outcome request is invalid"
            ) from exception
        if isinstance(exception, (SupervisorCommandConflict, SupervisorTransientConflict)):
            raise ExternalOperationOutcomeConflict(
                "external operation outcome request conflicted"
            ) from exception
        if isinstance(
            exception,
            (
                SupervisorIntegrityOrContractViolation,
                SupervisorOutcomeUnknown,
                SupervisorPermissionBoundaryMisconfigured,
                SupervisorUnavailable,
            ),
        ):
            self._ready = False
            code = getattr(getattr(exception, "code", None), "value", "UNKNOWN")
            LOGGER.warning(
                "External operation outcome reconciler failed closed; error_type=%s code=%s",
                type(exception).__name__,
                code,
            )
            raise ExternalOperationOutcomeUnavailable(
                "external operation outcome reconciler is unavailable"
            ) from exception
        self._ready = False
        LOGGER.warning(
            "External operation outcome reconciler failed closed; error_type=%s",
            type(exception).__name__,
        )
        raise ExternalOperationOutcomeUnavailable(
            "external operation outcome reconciler is unavailable"
        ) from exception

    def _map_record_result(
        self,
        result: object,
        command: RecordRuntimeExternalOperationOutcomeRequest,
    ) -> ExternalOperationOutcomeApiResult:
        if not isinstance(result, PrimitiveResult):
            return self._fail_closed_for_contract_violation()
        if result.outcome == PrimitiveOutcome.NOT_APPLIED:
            return ExternalOperationOutcomeApiResult.NOT_APPLIED
        if not isinstance(result.fact, RuntimeExternalOperationAttemptFact) or not (
            _record_fact_matches(result.fact, command)
        ):
            return self._fail_closed_for_contract_violation()
        return ExternalOperationOutcomeApiResult.APPLIED

    def _map_reconcile_result(
        self,
        result: object,
        command: ReconcileRuntimeExternalOperationOutcomeRequest,
    ) -> ExternalOperationOutcomeApiResult:
        if not isinstance(result, PrimitiveResult):
            return self._fail_closed_for_contract_violation()
        if result.outcome == PrimitiveOutcome.NOT_APPLIED:
            return ExternalOperationOutcomeApiResult.NOT_APPLIED
        if not isinstance(result.fact, RuntimeExternalOperationAttemptFact) or not _exact_outcome_fact_matches(
            result.fact,
            command,
            event_id=command.reconcile_event_id,
        ):
            return self._fail_closed_for_contract_violation()
        return ExternalOperationOutcomeApiResult.APPLIED

    def _fail_closed_for_contract_violation(self) -> ExternalOperationOutcomeApiResult:
        self._ready = False
        LOGGER.warning(
            "External operation outcome reconciler result violated its response contract"
        )
        raise ExternalOperationOutcomeUnavailable(
            "external operation outcome reconciler is unavailable"
        )


def create_postgres_external_operation_outcome_service(
    dsn: str,
    *,
    connect_timeout_seconds: int,
    statement_timeout_seconds: int,
    lock_timeout_seconds: int,
) -> PostgresExternalOperationOutcomeService:
    if not dsn.strip():
        raise ValueError("outcome reconciler database DSN must not be blank")
    if not 1 <= lock_timeout_seconds <= statement_timeout_seconds <= 30:
        raise ValueError("outcome reconciler database timeouts are invalid")

    options = (
        f"-c statement_timeout={statement_timeout_seconds * 1000} "
        f"-c lock_timeout={lock_timeout_seconds * 1000}"
    )

    def connect() -> Connection[dict[str, Any]]:
        return psycopg.connect(
            dsn,
            row_factory=dict_row,
            connect_timeout=connect_timeout_seconds,
            options=options,
        )

    return PostgresExternalOperationOutcomeService(
        PostgresRunSupervisorRepository(connect),
        connect,
    )


def _common_command_arguments(
    request: ExternalOperationOutcomeRecordRequest | ExternalOperationOutcomeReconcileRequest,
) -> dict[str, object]:
    return {
        "tenant_id": request.tenant_id,
        "runtime_external_permit_id": request.runtime_external_permit_id,
        "runtime_run_id": request.runtime_run_id,
        "task_execution_generation": request.task_execution_generation,
        "lease_owner": request.lease_owner,
        "lease_epoch": request.lease_epoch,
        "admission_snapshot_id": request.admission_snapshot_id,
        "admission_snapshot_hash": request.admission_snapshot_hash,
        "operation_kind": ExternalOperation(request.operation_kind),
        "intent_id": request.intent_id,
        "request_hash": request.request_hash,
    }


def _readiness_row_is_valid(row: Mapping[str, object] | None) -> bool:
    if row is None:
        return False
    login_name = row.get("login_name")
    return (
        isinstance(login_name, str)
        and bool(login_name)
        and row.get("login_can_login") is True
        and row.get("login_inherits") is True
        and row.get("login_is_restricted") is True
        and row.get("has_exact_membership_count") is True
        and row.get("has_exact_outcome_reconciler_membership") is True
        and row.get("outcome_reconciler_role_is_sealed") is True
        and row.get("is_outcome_reconciler") is True
        and row.get("is_permit_authorizer") is False
        and row.get("is_dispatch_authorizer") is False
        and row.get("is_executor") is False
        and row.get("has_schema_usage") is True
        and row.get("has_schema_create") is False
        and row.get("record_wrapper_exists") is True
        and row.get("reconcile_wrapper_exists") is True
        and row.get("can_execute_record_wrapper") is True
        and row.get("can_execute_reconcile_wrapper") is True
        and row.get("has_no_other_function_execute") is True
        and row.get("has_no_relation_privileges") is True
        and row.get("has_no_column_privileges") is True
        and row.get("has_no_sequence_privileges") is True
    )


def _binding_matches(
    fact: RuntimeExternalOperationAttemptFact,
    request: (
        RecordRuntimeExternalOperationOutcomeRequest
        | ReconcileRuntimeExternalOperationOutcomeRequest
    ),
) -> bool:
    return (
        fact.tenant_id == request.tenant_id
        and fact.runtime_external_permit_id == request.runtime_external_permit_id
        and fact.runtime_run_id == request.runtime_run_id
        and fact.task_execution_generation == request.task_execution_generation
        and fact.lease_owner == request.lease_owner
        and fact.lease_epoch == request.lease_epoch
        and fact.admission_snapshot_id == request.admission_snapshot_id
        and fact.admission_snapshot_hash == request.admission_snapshot_hash
        and fact.operation_kind == request.operation_kind
        and fact.intent_id == request.intent_id
        and fact.request_hash == request.request_hash
    )


def _exact_outcome_fact_matches(
    fact: RuntimeExternalOperationAttemptFact,
    request: (
        RecordRuntimeExternalOperationOutcomeRequest
        | ReconcileRuntimeExternalOperationOutcomeRequest
    ),
    *,
    event_id: object,
) -> bool:
    return (
        _binding_matches(fact, request)
        and fact.status == request.outcome_status
        and fact.last_event_id == event_id
        and fact.source_fact_id == request.source_fact_id
        and fact.source_fact_version == request.source_fact_version
        and fact.source_fact_hash == request.source_fact_hash
        and fact.outcome_code == request.outcome_code
        and fact.evidence_kind == request.evidence_kind
        and fact.result_hash == request.result_hash
        and fact.recorded_by == request.recorded_by
    )


def _record_fact_matches(
    fact: RuntimeExternalOperationAttemptFact,
    request: RecordRuntimeExternalOperationOutcomeRequest,
) -> bool:
    if not _binding_matches(fact, request):
        return False
    if fact.last_event_id == request.outcome_event_id:
        return _exact_outcome_fact_matches(
            fact,
            request,
            event_id=request.outcome_event_id,
        )
    return (
        request.outcome_status == ExternalOperationAttemptStatus.OUTCOME_UNKNOWN
        and fact.status
        in {
            ExternalOperationAttemptStatus.NOT_DISPATCHED,
            ExternalOperationAttemptStatus.SUCCEEDED,
            ExternalOperationAttemptStatus.FAILED_CONFIRMED,
        }
        and fact.source_fact_id == request.source_fact_id
        and fact.source_fact_version is not None
        and fact.source_fact_version > request.source_fact_version
        and fact.evidence_kind == ExternalOutcomeEvidenceKind.JAVA_CANONICAL_FACT
        and fact.recorded_by == request.recorded_by
    )

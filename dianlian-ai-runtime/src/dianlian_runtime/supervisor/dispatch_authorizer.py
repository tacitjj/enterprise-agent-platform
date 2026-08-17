from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from typing import Any, Protocol

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from dianlian_runtime.supervisor.authorizer_contracts import (
    ExternalDispatchArmRequest,
)
from dianlian_runtime.supervisor.contracts import (
    ConsumeAndArmRuntimeExternalDispatchRequest,
    ExternalOperation,
    PrimitiveOutcome,
    RuntimeExternalDispatchArmResult,
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
_ARM_WRAPPER = (
    "deer_runtime.consume_and_arm_runtime_external_dispatch("
    "uuid,uuid,uuid,bigint,varchar,bigint,uuid,character,varchar,uuid,"
    "character,uuid,varchar)"
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
           AND granted_role.rolname = 'dianlian_supervisor_dispatch_authorizer'
           AND NOT membership.admin_option
           AND membership.inherit_option
           AND membership.set_option
    ) AS has_exact_dispatch_authorizer_membership,
    EXISTS (
        SELECT 1
          FROM pg_catalog.pg_roles AS boundary_role
         WHERE boundary_role.rolname = 'dianlian_supervisor_dispatch_authorizer'
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
    ) AS dispatch_authorizer_role_is_sealed,
    pg_has_role(
        current_user,
        'dianlian_supervisor_dispatch_authorizer',
        'MEMBER'
    ) AS is_dispatch_authorizer,
    pg_has_role(current_user, 'dianlian_supervisor_permit_authorizer', 'MEMBER')
        AS is_permit_authorizer,
    pg_has_role(current_user, 'dianlian_supervisor_outcome_reconciler', 'MEMBER')
        AS is_outcome_reconciler,
    pg_has_role(current_user, 'dianlian_supervisor_executor', 'MEMBER')
        AS is_executor,
    has_schema_privilege(current_user, 'deer_runtime', 'USAGE') AS has_schema_usage,
    has_schema_privilege(current_user, 'deer_runtime', 'CREATE') AS has_schema_create,
    to_regprocedure(%s) IS NOT NULL AS wrapper_exists,
    has_function_privilege(current_user, to_regprocedure(%s), 'EXECUTE')
        AS can_execute_wrapper,
    NOT EXISTS (
        SELECT 1
          FROM pg_catalog.pg_proc AS procedure
          JOIN pg_catalog.pg_namespace AS procedure_namespace
            ON procedure_namespace.oid = procedure.pronamespace
         WHERE procedure_namespace.nspname = 'deer_runtime'
           AND procedure.oid <> to_regprocedure(%s)
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


class ExternalDispatchArmInvalidCommand(RuntimeError):
    pass


class ExternalDispatchArmConflict(RuntimeError):
    pass


class ExternalDispatchArmUnavailable(RuntimeError):
    pass


class ExternalDispatchArmRepository(Protocol):
    def consume_and_arm_external_dispatch(
        self,
        request: ConsumeAndArmRuntimeExternalDispatchRequest,
    ) -> RuntimeExternalDispatchArmResult: ...


class ExternalDispatchArmService(Protocol):
    @property
    def ready(self) -> bool: ...

    def arm(
        self,
        request: ExternalDispatchArmRequest,
        *,
        armed_by: str,
    ) -> RuntimeExternalDispatchArmResult: ...


class UnavailableExternalDispatchArmService:
    @property
    def ready(self) -> bool:
        return False

    def arm(
        self,
        request: ExternalDispatchArmRequest,
        *,
        armed_by: str,
    ) -> RuntimeExternalDispatchArmResult:
        del request, armed_by
        raise ExternalDispatchArmUnavailable("external dispatch arm is unavailable")


ConnectionFactory = Callable[[], Connection[dict[str, Any]]]


class PostgresExternalDispatchArmService:
    """Restricted dispatch authorizer; no other Supervisor capability is accepted."""

    def __init__(
        self,
        repository: ExternalDispatchArmRepository,
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
                (_ARM_WRAPPER, _ARM_WRAPPER, _ARM_WRAPPER),
            ).fetchone()
            self._ready = _readiness_row_is_valid(row)
        except Exception as exception:
            self._ready = False
            LOGGER.warning(
                "External dispatch authorizer database is not ready; error_type=%s",
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

    def arm(
        self,
        request: ExternalDispatchArmRequest,
        *,
        armed_by: str,
    ) -> RuntimeExternalDispatchArmResult:
        if not self._ready:
            raise ExternalDispatchArmUnavailable("external dispatch arm is unavailable")
        if (
            not isinstance(armed_by, str)
            or not armed_by.strip()
            or armed_by != armed_by.strip()
            or len(armed_by) > 160
        ):
            raise ExternalDispatchArmInvalidCommand(
                "external dispatch arm request is invalid"
            )
        try:
            command = ConsumeAndArmRuntimeExternalDispatchRequest(
                tenant_id=request.tenant_id,
                runtime_external_permit_id=request.runtime_external_permit_id,
                runtime_run_id=request.runtime_run_id,
                task_execution_generation=request.task_execution_generation,
                lease_owner=request.lease_owner,
                lease_epoch=request.lease_epoch,
                admission_snapshot_id=request.admission_snapshot_id,
                admission_snapshot_hash=request.admission_snapshot_hash,
                operation_kind=ExternalOperation(request.operation_kind),
                intent_id=request.intent_id,
                request_hash=request.request_hash,
                arm_event_id=request.arm_event_id,
                armed_by=armed_by,
            )
            result = self._repository.consume_and_arm_external_dispatch(command)
        except (
            TypeError,
            ValueError,
            SupervisorInvalidCommand,
            SupervisorUnsupportedCommand,
        ) as exception:
            raise ExternalDispatchArmInvalidCommand(
                "external dispatch arm request is invalid"
            ) from exception
        except (SupervisorCommandConflict, SupervisorTransientConflict) as exception:
            raise ExternalDispatchArmConflict(
                "external dispatch arm conflicted"
            ) from exception
        except (
            SupervisorIntegrityOrContractViolation,
            SupervisorOutcomeUnknown,
            SupervisorPermissionBoundaryMisconfigured,
            SupervisorUnavailable,
        ) as exception:
            self._ready = False
            LOGGER.warning(
                "External dispatch arm failed closed; error_type=%s code=%s",
                type(exception).__name__,
                exception.code.value,
            )
            raise ExternalDispatchArmUnavailable(
                "external dispatch arm is unavailable"
            ) from exception
        except Exception as exception:
            self._ready = False
            LOGGER.warning(
                "External dispatch arm failed closed; error_type=%s",
                type(exception).__name__,
            )
            raise ExternalDispatchArmUnavailable(
                "external dispatch arm is unavailable"
            ) from exception

        if not isinstance(result, RuntimeExternalDispatchArmResult):
            return self._fail_closed_for_contract_violation()
        if result.outcome == PrimitiveOutcome.NOT_APPLIED:
            return result
        if result.fact is None or not _fact_matches(result.fact, command):
            return self._fail_closed_for_contract_violation()
        return result

    def _fail_closed_for_contract_violation(self) -> RuntimeExternalDispatchArmResult:
        self._ready = False
        LOGGER.warning("External dispatch arm result violated its response contract")
        raise ExternalDispatchArmUnavailable("external dispatch arm is unavailable")


def create_postgres_external_dispatch_arm_service(
    dsn: str,
    *,
    connect_timeout_seconds: int,
    statement_timeout_seconds: int,
    lock_timeout_seconds: int,
) -> PostgresExternalDispatchArmService:
    if not dsn.strip():
        raise ValueError("dispatch authorizer database DSN must not be blank")
    if not 1 <= lock_timeout_seconds <= statement_timeout_seconds <= 30:
        raise ValueError("dispatch authorizer database timeouts are invalid")

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

    return PostgresExternalDispatchArmService(
        PostgresRunSupervisorRepository(connect),
        connect,
    )


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
        and row.get("has_exact_dispatch_authorizer_membership") is True
        and row.get("dispatch_authorizer_role_is_sealed") is True
        and row.get("is_dispatch_authorizer") is True
        and row.get("is_permit_authorizer") is False
        and row.get("is_outcome_reconciler") is False
        and row.get("is_executor") is False
        and row.get("has_schema_usage") is True
        and row.get("has_schema_create") is False
        and row.get("wrapper_exists") is True
        and row.get("can_execute_wrapper") is True
        and row.get("has_no_other_function_execute") is True
        and row.get("has_no_relation_privileges") is True
        and row.get("has_no_column_privileges") is True
        and row.get("has_no_sequence_privileges") is True
    )


def _fact_matches(
    fact: RuntimeExternalOperationAttemptFact,
    request: ConsumeAndArmRuntimeExternalDispatchRequest,
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
        and fact.arm_event_id == request.arm_event_id
        and fact.armed_by == request.armed_by
    )

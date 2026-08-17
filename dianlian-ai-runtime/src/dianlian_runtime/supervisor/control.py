from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from typing import Any, NoReturn, Protocol

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from dianlian_runtime.supervisor.authorizer_contracts import (
    RuntimeRunCancelApiResult,
    RuntimeRunCancelRequest,
)
from dianlian_runtime.supervisor.contracts import (
    FrozenJsonObject,
    PrimitiveOutcome,
    PrimitiveResult,
    RequestRuntimeRunCancelRequest,
    RuntimeRunControlFact,
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
_REQUEST_CANCEL_WRAPPER = (
    "deer_runtime.request_runtime_run_cancel("
    "uuid,uuid,uuid,uuid,varchar,bigint,varchar,character,jsonb)"
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
           AND granted_role.rolname = 'dianlian_supervisor_controller'
           AND NOT membership.admin_option
           AND membership.inherit_option
           AND membership.set_option
    ) AS has_exact_controller_membership,
    EXISTS (
        SELECT 1
          FROM pg_catalog.pg_roles AS boundary_role
         WHERE boundary_role.rolname = 'dianlian_supervisor_controller'
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
    ) AS controller_role_is_sealed,
    pg_has_role(current_user, 'dianlian_supervisor_controller', 'MEMBER')
        AS is_controller,
    pg_has_role(current_user, 'dianlian_supervisor_executor', 'MEMBER')
        AS is_executor,
    pg_has_role(current_user, 'dianlian_supervisor_permit_authorizer', 'MEMBER')
        AS is_permit_authorizer,
    pg_has_role(current_user, 'dianlian_supervisor_dispatch_authorizer', 'MEMBER')
        AS is_dispatch_authorizer,
    pg_has_role(current_user, 'dianlian_supervisor_outcome_reconciler', 'MEMBER')
        AS is_outcome_reconciler,
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
          CROSS JOIN unnest(ARRAY['SELECT', 'USAGE', 'UPDATE'])
              AS requested_sequence_privilege(privilege_name)
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


class RuntimeRunCancelInvalidCommand(RuntimeError):
    pass


class RuntimeRunCancelConflict(RuntimeError):
    pass


class RuntimeRunCancelUnavailable(RuntimeError):
    pass


class RuntimeRunCancelRepository(Protocol):
    def request_cancel(
        self,
        request: RequestRuntimeRunCancelRequest,
    ) -> PrimitiveResult[RuntimeRunControlFact]: ...


class RuntimeRunCancelService(Protocol):
    @property
    def ready(self) -> bool: ...

    def request_cancel(
        self,
        request: RuntimeRunCancelRequest,
        *,
        requested_by: str,
    ) -> RuntimeRunCancelApiResult: ...


class UnavailableRuntimeRunCancelService:
    @property
    def ready(self) -> bool:
        return False

    def request_cancel(
        self,
        request: RuntimeRunCancelRequest,
        *,
        requested_by: str,
    ) -> RuntimeRunCancelApiResult:
        del request, requested_by
        raise RuntimeRunCancelUnavailable("runtime Run cancellation is unavailable")


ConnectionFactory = Callable[[], Connection[dict[str, Any]]]


class PostgresRuntimeRunCancelService:
    def __init__(
        self,
        repository: RuntimeRunCancelRepository,
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
                    _REQUEST_CANCEL_WRAPPER,
                    _REQUEST_CANCEL_WRAPPER,
                    _REQUEST_CANCEL_WRAPPER,
                ),
            ).fetchone()
            self._ready = _readiness_row_is_valid(row)
        except Exception as exception:
            self._ready = False
            LOGGER.warning(
                "Runtime Run controller database is not ready; error_type=%s",
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

    def request_cancel(
        self,
        request: RuntimeRunCancelRequest,
        *,
        requested_by: str,
    ) -> RuntimeRunCancelApiResult:
        if not self._ready:
            raise RuntimeRunCancelUnavailable("runtime Run cancellation is unavailable")
        if (
            requested_by != requested_by.strip()
            or not requested_by
            or len(requested_by) > 160
        ):
            raise RuntimeRunCancelInvalidCommand(
                "runtime Run cancel requester is invalid"
            )
        try:
            command = RequestRuntimeRunCancelRequest(
                tenant_id=request.tenant_id,
                runtime_run_id=request.runtime_run_id,
                cancel_request_id=request.cancel_request_id,
                actor_id=request.actor_id,
                reason_code=request.reason_code,
                expected_run_version=request.expected_run_version,
                idempotency_key=request.idempotency_key,
                request_hash=request.request_hash,
                event_payload=FrozenJsonObject(
                    {
                        "schemaVersion": "runtime-run-cancel-request-v1",
                        "cancelRequestId": str(request.cancel_request_id),
                        "actorId": str(request.actor_id),
                        "reasonCode": request.reason_code,
                        "requestedByService": requested_by,
                    }
                ),
            )
            result = self._repository.request_cancel(command)
        except (TypeError, ValueError, SupervisorInvalidCommand, SupervisorUnsupportedCommand) as exception:
            raise RuntimeRunCancelInvalidCommand(
                "runtime Run cancel request is invalid"
            ) from exception
        except (SupervisorCommandConflict, SupervisorTransientConflict) as exception:
            raise RuntimeRunCancelConflict("runtime Run cancel request conflicted") from exception
        except (
            SupervisorIntegrityOrContractViolation,
            SupervisorOutcomeUnknown,
            SupervisorPermissionBoundaryMisconfigured,
            SupervisorUnavailable,
        ) as exception:
            self._fail_closed(exception)
        except Exception as exception:
            self._fail_closed(exception)

        if not isinstance(result, PrimitiveResult):
            self._fail_closed(TypeError("unexpected result type"))
        if result.outcome == PrimitiveOutcome.NOT_APPLIED:
            return RuntimeRunCancelApiResult.NOT_APPLIED
        if (
            result.outcome != PrimitiveOutcome.FACT_RETURNED
            or not isinstance(result.fact, RuntimeRunControlFact)
            or not _fact_matches(result.fact, command)
        ):
            self._fail_closed(ValueError("result contract mismatch"))
        return RuntimeRunCancelApiResult.APPLIED

    def _fail_closed(self, exception: Exception) -> NoReturn:
        self._ready = False
        LOGGER.warning(
            "Runtime Run cancellation failed closed; error_type=%s",
            type(exception).__name__,
        )
        raise RuntimeRunCancelUnavailable(
            "runtime Run cancellation is unavailable"
        ) from exception


def create_postgres_runtime_run_cancel_service(
    dsn: str,
    *,
    connect_timeout_seconds: int,
    statement_timeout_seconds: int,
    lock_timeout_seconds: int,
) -> PostgresRuntimeRunCancelService:
    if not dsn.strip():
        raise ValueError("runtime Run controller database DSN must not be blank")
    if not 1 <= lock_timeout_seconds <= statement_timeout_seconds <= 30:
        raise ValueError("runtime Run controller database timeouts are invalid")

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

    return PostgresRuntimeRunCancelService(
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
        and row.get("has_exact_controller_membership") is True
        and row.get("controller_role_is_sealed") is True
        and row.get("is_controller") is True
        and row.get("is_executor") is False
        and row.get("is_permit_authorizer") is False
        and row.get("is_dispatch_authorizer") is False
        and row.get("is_outcome_reconciler") is False
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
    fact: RuntimeRunControlFact,
    request: RequestRuntimeRunCancelRequest,
) -> bool:
    return (
        fact.tenant_id == request.tenant_id
        and fact.control_id == request.cancel_request_id
        and fact.runtime_run_id == request.runtime_run_id
        and fact.control_type == "CANCEL"
        and fact.actor_id == request.actor_id
        and fact.reason_code == request.reason_code
        and fact.expected_run_version == request.expected_run_version
        and fact.idempotency_key == request.idempotency_key
        and fact.request_hash == request.request_hash
    )

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
import logging
from typing import Any, Annotated, Literal, NoReturn, Protocol
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel


LOGGER = logging.getLogger(__name__)
_MAX_BIGINT = 9_223_372_036_854_775_807
_READ_PROJECTION_WRAPPER = (
    "deer_runtime.read_runtime_run_projection("
    "uuid,uuid,uuid,bigint,character,bigint,integer)"
)


def _require_non_nil_uuid(value: UUID) -> UUID:
    if value.int == 0:
        raise ValueError("UUID must not be the nil UUID")
    return value


NonNilUuid = Annotated[UUID, AfterValidator(_require_non_nil_uuid)]
LowerSha256 = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]


class _StrictCamelContract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_alias=True,
        validate_by_name=False,
        extra="forbid",
        frozen=True,
    )


class RuntimeRunProjectionRequest(_StrictCamelContract):
    tenant_id: NonNilUuid
    runtime_run_id: NonNilUuid
    task_step_id: NonNilUuid
    task_execution_generation: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    request_hash: LowerSha256
    after_sequence: StrictInt = Field(ge=0, le=_MAX_BIGINT)
    page_size: StrictInt = Field(default=64, ge=1, le=100)


class RuntimeRunProjectionEvent(_StrictCamelContract):
    event_id: NonNilUuid
    sequence_no: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    event_type: Annotated[
        StrictStr,
        StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$"),
    ]
    event_version: StrictInt = Field(ge=1, le=32767)
    run_version: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    lease_owner: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=160),
    ] | None
    lease_epoch: StrictInt = Field(ge=0, le=_MAX_BIGINT)
    checkpoint_id: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=160),
    ] | None
    payload: dict[str, Any]
    occurred_at: datetime
    created_at: datetime

    @field_validator("lease_owner", "checkpoint_id")
    @classmethod
    def require_trimmed_optional_text(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("optional text must be trimmed")
        return value

    @model_validator(mode="after")
    def require_lease_identity_shape(self) -> "RuntimeRunProjectionEvent":
        if (self.lease_epoch == 0) is not (self.lease_owner is None):
            raise ValueError("event lease owner and epoch are inconsistent")
        if self.occurred_at.tzinfo is None or self.created_at.tzinfo is None:
            raise ValueError("event timestamps must be timezone-aware")
        return self


class RuntimeRunProjectionResponse(_StrictCamelContract):
    tenant_id: NonNilUuid
    runtime_run_id: NonNilUuid
    runtime_thread_id: NonNilUuid
    task_step_id: NonNilUuid
    task_execution_generation: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    status: Literal[
        "QUEUED",
        "RUNNING",
        "WAITING_USER_INPUT",
        "WAITING_AUTH",
        "PAUSED",
        "CANCEL_REQUESTED",
        "CANCELLING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "CANCEL_OUTCOME_UNKNOWN",
    ]
    operation_kind: Literal["START", "CONTINUE", "RETRY", "REPLAN", "REPLACE"]
    request_hash: LowerSha256
    current_checkpoint_id: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=160),
    ] | None
    current_checkpoint_sequence_no: StrictInt | None = Field(
        default=None,
        ge=1,
        le=_MAX_BIGINT,
    )
    next_event_sequence_no: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    event_retention_floor_sequence: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    run_version: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    terminal_reason: Annotated[
        StrictStr,
        StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$"),
    ] | None
    terminal_event_id: NonNilUuid | None
    lease_epoch: StrictInt = Field(ge=0, le=_MAX_BIGINT)
    attempt: StrictInt = Field(ge=0, le=2_147_483_647)
    runtime_version: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=128),
    ]
    agent_name: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=128),
    ]
    failure_code: Annotated[
        StrictStr,
        StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$"),
    ] | None
    cancel_requested_at: datetime | None
    started_at: datetime | None
    terminal_at: datetime | None
    created_at: datetime
    updated_at: datetime
    after_sequence: StrictInt = Field(ge=0, le=_MAX_BIGINT)
    next_sequence: StrictInt = Field(ge=0, le=_MAX_BIGINT)
    has_more: StrictBool
    replay_gap: StrictBool
    events: tuple[RuntimeRunProjectionEvent, ...]

    @field_validator(
        "current_checkpoint_id",
        "runtime_version",
        "agent_name",
    )
    @classmethod
    def require_trimmed_text(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("text must be trimmed")
        return value

    @model_validator(mode="after")
    def require_projection_consistency(self) -> "RuntimeRunProjectionResponse":
        if (self.current_checkpoint_id is None) is not (
            self.current_checkpoint_sequence_no is None
        ):
            raise ValueError("checkpoint identity and sequence are inconsistent")
        if self.event_retention_floor_sequence > self.next_event_sequence_no:
            raise ValueError("event retention floor exceeds the event watermark")
        expected_gap = self.after_sequence < self.event_retention_floor_sequence - 1
        if self.replay_gap != expected_gap:
            raise ValueError("replay gap does not match the retained event window")
        if self.replay_gap:
            if self.events or self.has_more or self.next_sequence != self.after_sequence:
                raise ValueError("replay gap must not expose a partial event page")
        else:
            cursor = self.after_sequence
            for event in self.events:
                if event.sequence_no != cursor + 1:
                    raise ValueError("runtime event page must be contiguous")
                if event.run_version > self.run_version:
                    raise ValueError("runtime event version exceeds the Run version")
                cursor = event.sequence_no
            if self.next_sequence != cursor:
                raise ValueError("next sequence does not match the event page")
            expected_more = self.next_event_sequence_no - 1 > self.next_sequence
            if self.has_more != expected_more:
                raise ValueError("hasMore does not match the event watermark")
        for value in (
            self.cancel_requested_at,
            self.started_at,
            self.terminal_at,
            self.created_at,
            self.updated_at,
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError("Run timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("updatedAt must not be before createdAt")
        return self


class RuntimeRunProjectionProblem(_StrictCamelContract):
    code: str
    message: str


class RuntimeRunProjectionInvalidQuery(RuntimeError):
    pass


class RuntimeRunProjectionNotFound(RuntimeError):
    pass


class RuntimeRunProjectionUnavailable(RuntimeError):
    pass


class RuntimeRunProjectionService(Protocol):
    @property
    def ready(self) -> bool: ...

    def read(
        self,
        request: RuntimeRunProjectionRequest,
    ) -> RuntimeRunProjectionResponse: ...


class UnavailableRuntimeRunProjectionService:
    @property
    def ready(self) -> bool:
        return False

    def read(
        self,
        request: RuntimeRunProjectionRequest,
    ) -> RuntimeRunProjectionResponse:
        del request
        raise RuntimeRunProjectionUnavailable("runtime Run projection is unavailable")


ConnectionFactory = Callable[[], Connection[dict[str, Any]]]


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
           AND granted_role.rolname = 'dianlian_supervisor_run_observer'
           AND NOT membership.admin_option
           AND membership.inherit_option
           AND membership.set_option
    ) AS has_exact_run_observer_membership,
    EXISTS (
        SELECT 1
          FROM pg_catalog.pg_roles AS boundary_role
         WHERE boundary_role.rolname = 'dianlian_supervisor_run_observer'
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
    ) AS run_observer_role_is_sealed,
    pg_has_role(current_user, 'dianlian_supervisor_run_observer', 'MEMBER')
        AS is_run_observer,
    pg_has_role(current_user, 'dianlian_supervisor_executor', 'MEMBER') AS is_executor,
    pg_has_role(current_user, 'dianlian_supervisor_permit_authorizer', 'MEMBER')
        AS is_permit_authorizer,
    pg_has_role(current_user, 'dianlian_supervisor_dispatch_authorizer', 'MEMBER')
        AS is_dispatch_authorizer,
    pg_has_role(current_user, 'dianlian_supervisor_outcome_reconciler', 'MEMBER')
        AS is_outcome_reconciler,
    pg_has_role(current_user, 'dianlian_supervisor_controller', 'MEMBER') AS is_controller,
    pg_has_role(current_user, 'dianlian_supervisor_run_admitter', 'MEMBER') AS is_run_admitter,
    has_schema_privilege(current_user, 'deer_runtime', 'USAGE') AS has_schema_usage,
    has_schema_privilege(current_user, 'deer_runtime', 'CREATE') AS has_schema_create,
    to_regprocedure(%s) IS NOT NULL AS wrapper_exists,
    has_function_privilege(current_user, to_regprocedure(%s), 'EXECUTE')
        AS can_execute_wrapper,
    NOT EXISTS (
        SELECT 1
          FROM pg_catalog.pg_proc AS procedure
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = procedure.pronamespace
         WHERE namespace.nspname = 'deer_runtime'
           AND procedure.oid <> to_regprocedure(%s)
           AND has_function_privilege(current_user, procedure.oid, 'EXECUTE')
    ) AS has_no_other_function_execute,
    NOT EXISTS (
        SELECT 1
          FROM pg_catalog.pg_class AS relation
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
          CROSS JOIN unnest(ARRAY[
              'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE',
              'REFERENCES', 'TRIGGER'
          ]) AS requested_privilege(privilege_name)
         WHERE namespace.nspname = 'deer_runtime'
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
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
          JOIN pg_catalog.pg_attribute AS attribute
            ON attribute.attrelid = relation.oid
          CROSS JOIN unnest(ARRAY[
              'SELECT', 'INSERT', 'UPDATE', 'REFERENCES'
          ]) AS requested_privilege(privilege_name)
         WHERE namespace.nspname = 'deer_runtime'
           AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
           AND attribute.attnum > 0
           AND NOT attribute.attisdropped
           AND has_column_privilege(
               current_user,
               relation.oid,
               attribute.attnum,
               requested_privilege.privilege_name
           )
    ) AS has_no_column_privileges,
    NOT EXISTS (
        SELECT 1
          FROM pg_catalog.pg_class AS sequence_relation
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = sequence_relation.relnamespace
          CROSS JOIN unnest(ARRAY['SELECT', 'USAGE', 'UPDATE'])
              AS requested_privilege(privilege_name)
         WHERE namespace.nspname = 'deer_runtime'
           AND sequence_relation.relkind = 'S'
           AND has_sequence_privilege(
               current_user,
               sequence_relation.oid,
               requested_privilege.privilege_name
           )
    ) AS has_no_sequence_privileges
  FROM pg_catalog.pg_roles AS login_role
 WHERE login_role.rolname = current_user
"""


class PostgresRuntimeRunProjectionService:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        if not callable(connection_factory):
            raise TypeError("connection_factory must be callable")
        self._connection_factory = connection_factory
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def start(self) -> None:
        connection: Connection[dict[str, Any]] | None = None
        try:
            connection = self._connection_factory()
            row = connection.execute(
                _READINESS_SQL,
                (
                    _READ_PROJECTION_WRAPPER,
                    _READ_PROJECTION_WRAPPER,
                    _READ_PROJECTION_WRAPPER,
                ),
            ).fetchone()
            self._ready = _readiness_row_is_valid(row)
        except Exception as exception:
            self._ready = False
            LOGGER.warning(
                "Runtime Run observer database is not ready; error_type=%s",
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

    def read(
        self,
        request: RuntimeRunProjectionRequest,
    ) -> RuntimeRunProjectionResponse:
        if not self._ready:
            raise RuntimeRunProjectionUnavailable("runtime Run projection is unavailable")
        connection: Connection[dict[str, Any]] | None = None
        try:
            connection = self._connection_factory()
            row = connection.execute(
                """
                SELECT *
                  FROM deer_runtime.read_runtime_run_projection(
                      %s, %s, %s, %s, %s, %s, %s
                  )
                """,
                (
                    request.tenant_id,
                    request.runtime_run_id,
                    request.task_step_id,
                    request.task_execution_generation,
                    request.request_hash,
                    request.after_sequence,
                    request.page_size,
                ),
            ).fetchone()
        except psycopg.errors.InvalidParameterValue as exception:
            raise RuntimeRunProjectionInvalidQuery(
                "runtime Run projection query is invalid"
            ) from exception
        except Exception as exception:
            self._fail_closed(exception)
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

        if row is None:
            raise RuntimeRunProjectionNotFound("runtime Run projection was not found")
        try:
            projection = RuntimeRunProjectionResponse.model_validate(
                _database_row_to_contract_payload(row),
                strict=True,
            )
        except (TypeError, ValueError) as exception:
            self._fail_closed(exception)
        if not _projection_matches_request(projection, request):
            self._fail_closed(ValueError("runtime Run projection identity mismatch"))
        if len(projection.events) > request.page_size:
            self._fail_closed(ValueError("runtime Run projection exceeded page size"))
        return projection

    def _fail_closed(self, exception: Exception) -> NoReturn:
        self._ready = False
        LOGGER.warning(
            "Runtime Run observer failed closed; error_type=%s",
            type(exception).__name__,
        )
        raise RuntimeRunProjectionUnavailable(
            "runtime Run projection is unavailable"
        ) from exception


def create_postgres_runtime_run_projection_service(
    dsn: str,
    *,
    connect_timeout_seconds: int,
    statement_timeout_seconds: int,
    lock_timeout_seconds: int,
) -> PostgresRuntimeRunProjectionService:
    if not dsn.strip():
        raise ValueError("runtime Run observer database DSN must not be blank")
    if not 1 <= lock_timeout_seconds <= statement_timeout_seconds <= 30:
        raise ValueError("runtime Run observer database timeouts are invalid")

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

    return PostgresRuntimeRunProjectionService(connect)


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
        and row.get("has_exact_run_observer_membership") is True
        and row.get("run_observer_role_is_sealed") is True
        and row.get("is_run_observer") is True
        and row.get("is_executor") is False
        and row.get("is_permit_authorizer") is False
        and row.get("is_dispatch_authorizer") is False
        and row.get("is_outcome_reconciler") is False
        and row.get("is_controller") is False
        and row.get("is_run_admitter") is False
        and row.get("has_schema_usage") is True
        and row.get("has_schema_create") is False
        and row.get("wrapper_exists") is True
        and row.get("can_execute_wrapper") is True
        and row.get("has_no_other_function_execute") is True
        and row.get("has_no_relation_privileges") is True
        and row.get("has_no_column_privileges") is True
        and row.get("has_no_sequence_privileges") is True
    )


def _projection_matches_request(
    projection: RuntimeRunProjectionResponse,
    request: RuntimeRunProjectionRequest,
) -> bool:
    return (
        projection.tenant_id == request.tenant_id
        and projection.runtime_run_id == request.runtime_run_id
        and projection.task_step_id == request.task_step_id
        and projection.task_execution_generation == request.task_execution_generation
        and projection.request_hash == request.request_hash
        and projection.after_sequence == request.after_sequence
    )


def _database_row_to_contract_payload(
    row: Mapping[str, object],
) -> dict[str, object]:
    payload = {to_camel(key): value for key, value in row.items()}
    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        raise TypeError("runtime Run projection events must be a JSON array")
    events: list[dict[str, object]] = []
    for raw_event in raw_events:
        if not isinstance(raw_event, Mapping):
            raise TypeError("runtime Run projection event must be a JSON object")
        event = dict(raw_event)
        event_id = event.get("eventId")
        occurred_at = event.get("occurredAt")
        created_at = event.get("createdAt")
        if not isinstance(event_id, str):
            raise TypeError("runtime Run projection eventId must be a string")
        if not isinstance(occurred_at, str) or not isinstance(created_at, str):
            raise TypeError("runtime Run projection event timestamps must be strings")
        event["eventId"] = UUID(event_id)
        event["occurredAt"] = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        event["createdAt"] = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        events.append(event)
    payload["events"] = tuple(events)
    return payload

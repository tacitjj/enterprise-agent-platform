from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from dianlian_runtime.app import create_app
from dianlian_runtime.auth import (
    InternalServicePrincipal,
    InternalServiceScope,
)
from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.supervisor.authorizer import (
    PermitAuthorizationConflict,
    PermitAuthorizationInvalidCommand,
    PermitAuthorizationUnavailable,
    PostgresPermitAuthorizationService,
    create_postgres_permit_authorization_service,
)
from dianlian_runtime.supervisor.authorizer_contracts import (
    PermitAuthorizationOutcome,
    PermitAuthorizationRequest,
)
from dianlian_runtime.supervisor.contracts import (
    ConsumeRuntimeExternalPermitRequest,
    ExternalOperation,
    ExternalPermitStatus,
    PrimitiveOutcome,
    PrimitiveResult,
    RuntimeExternalPermitFact,
    SupervisorErrorCode,
    SupervisorInvalidCommand,
    SupervisorPrimitive,
    SupervisorUnavailable,
)


ROUTE = "/internal/v1/runtime-supervisor/external-permits/consume-and-authorize"
TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
PERMIT_ID = UUID("00000000-0000-4000-8000-000000000002")
RUN_ID = UUID("00000000-0000-4000-8000-000000000003")
ADMISSION_ID = UUID("00000000-0000-4000-8000-000000000004")
INTENT_ID = UUID("00000000-0000-4000-8000-000000000005")
CONSUME_EVENT_ID = UUID("00000000-0000-4000-8000-000000000006")
HASH = "a" * 64


def _settings(*, enabled: bool) -> RuntimeSettings:
    return RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="runtime-api",
        context_enabled=False,
        agent_enabled=False,
        supervisor_enabled=False,
        permit_authorizer_enabled=enabled,
    )


def test_authorizer_settings_are_opt_in_role_bound_and_hide_the_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIANLIAN_RUNTIME_ROLE", "runtime-api")
    monkeypatch.setenv("DIANLIAN_PERMIT_AUTHORIZER_ENABLED", "true")
    monkeypatch.setenv(
        "DIANLIAN_PERMIT_AUTHORIZER_DATABASE_DSN",
        "postgresql://authorizer:secret@example.invalid/runtime",
    )
    monkeypatch.setenv(
        "DIANLIAN_PERMIT_AUTHORIZER_DATABASE_CONNECT_TIMEOUT_SECONDS",
        "4",
    )
    monkeypatch.setenv(
        "DIANLIAN_PERMIT_AUTHORIZER_DATABASE_STATEMENT_TIMEOUT_SECONDS",
        "5",
    )
    monkeypatch.setenv(
        "DIANLIAN_PERMIT_AUTHORIZER_DATABASE_LOCK_TIMEOUT_SECONDS",
        "3",
    )

    settings = RuntimeSettings.from_environment()

    assert settings.permit_authorizer_enabled is True
    assert settings.permit_authorizer_database_connect_timeout_seconds == 4
    assert settings.permit_authorizer_database_statement_timeout_seconds == 5
    assert settings.permit_authorizer_database_lock_timeout_seconds == 3
    assert "secret" not in repr(settings)

    with pytest.raises(ValueError, match="runtime-api"):
        replace(settings, role="agent-worker")
    with pytest.raises(ValueError, match="lock timeout"):
        replace(
            settings,
            permit_authorizer_database_statement_timeout_seconds=2,
            permit_authorizer_database_lock_timeout_seconds=3,
        )


def _body() -> dict[str, object]:
    return {
        "tenantId": str(TENANT_ID),
        "runtimeExternalPermitId": str(PERMIT_ID),
        "runtimeRunId": str(RUN_ID),
        "taskExecutionGeneration": 3,
        "leaseOwner": "worker-current",
        "leaseEpoch": 7,
        "admissionSnapshotId": str(ADMISSION_ID),
        "admissionSnapshotHash": HASH,
        "operationKind": "ADMISSION_RESOLVE",
        "intentId": str(INTENT_ID),
        "requestHash": HASH,
        "consumeEventId": str(CONSUME_EVENT_ID),
    }


class RecordingAuthenticator:
    def __init__(
        self,
        *,
        subject: str = "verified-java-service",
        extra_scope: InternalServiceScope | None = None,
    ) -> None:
        self.ready = True
        self.subject = subject
        self.extra_scope = extra_scope
        self.required_scopes: list[InternalServiceScope] = []

    def authorize(self, token: str, required_scope: InternalServiceScope):
        del token
        self.required_scopes.append(required_scope)
        return InternalServicePrincipal(
            subject=self.subject,
            token_id=UUID("00000000-0000-4000-8000-000000000043"),
            scopes=frozenset(
                {required_scope}
                | ({self.extra_scope} if self.extra_scope is not None else set())
            ),
            issued_at=0,
            expires_at=60,
        )


class RecordingService:
    def __init__(
        self,
        outcome: PermitAuthorizationOutcome = PermitAuthorizationOutcome.APPLIED,
        *,
        error: RuntimeError | None = None,
    ) -> None:
        self.ready = True
        self.outcome = outcome
        self.error = error
        self.calls: list[tuple[PermitAuthorizationRequest, str]] = []

    def authorize(
        self,
        request: PermitAuthorizationRequest,
        *,
        consumed_by: str,
    ) -> PermitAuthorizationOutcome:
        self.calls.append((request, consumed_by))
        if self.error is not None:
            raise self.error
        return self.outcome


def _client(service: RecordingService):
    authenticator = RecordingAuthenticator()
    app = create_app(
        _settings(enabled=True),
        internal_service_authenticator=authenticator,
        permit_authorization_service=service,
    )
    return TestClient(app), authenticator


def test_authorizer_endpoint_uses_exact_scope_and_verified_subject() -> None:
    service = RecordingService()
    client, authenticator = _client(service)

    response = client.post(
        ROUTE,
        headers={"Authorization": "Bearer opaque-test-token"},
        json=_body(),
    )

    assert response.status_code == 200
    assert response.json() == {"outcome": "APPLIED"}
    assert authenticator.required_scopes == [
        InternalServiceScope.RUNTIME_EXTERNAL_PERMIT_AUTHORIZE
    ]
    request, consumed_by = service.calls[0]
    assert request.runtime_external_permit_id == PERMIT_ID
    assert consumed_by == "verified-java-service"
    assert "consumedBy" not in _body()

    operation = client.get("/internal/v1/openapi.json").json()["paths"][ROUTE][
        "post"
    ]
    assert operation["x-required-scopes"] == [
        "runtime.external-permit.authorize"
    ]
    assert operation["security"] == [{"InternalServiceBearer": []}]
    assert "413" in operation["responses"]


def test_high_authority_endpoint_rejects_a_multi_scope_principal() -> None:
    service = RecordingService()
    authenticator = RecordingAuthenticator(
        extra_scope=InternalServiceScope.RUNTIME_EXTERNAL_DISPATCH_ARM
    )
    app = create_app(
        _settings(enabled=True),
        internal_service_authenticator=authenticator,
        permit_authorization_service=service,
    )

    response = TestClient(app).post(ROUTE, json=_body())

    assert response.status_code == 403
    assert service.calls == []


def test_not_applied_is_a_plain_200_without_permit_details() -> None:
    client, _ = _client(RecordingService(PermitAuthorizationOutcome.NOT_APPLIED))

    response = client.post(ROUTE, json=_body())

    assert response.status_code == 200
    assert response.json() == {"outcome": "NOT_APPLIED"}


def test_disabled_or_missing_authorizer_fails_closed() -> None:
    authenticator = RecordingAuthenticator()
    disabled = TestClient(
        create_app(
            _settings(enabled=False),
            internal_service_authenticator=authenticator,
        )
    )
    missing = TestClient(
        create_app(
            _settings(enabled=True),
            internal_service_authenticator=authenticator,
        )
    )

    assert disabled.post(ROUTE, json=_body()).status_code == 404
    assert ROUTE not in disabled.get("/internal/v1/openapi.json").json()["paths"]

    response = missing.post(ROUTE, json=_body())
    assert response.status_code == 503
    assert response.json() == {
        "code": "PERMIT_AUTHORIZATION_UNAVAILABLE",
        "message": "Permit authorization is unavailable",
    }
    assert missing.get("/internal/v1/health/readiness").status_code == 503


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (
            PermitAuthorizationInvalidCommand("hidden"),
            400,
            "PERMIT_AUTHORIZATION_REQUEST_INVALID",
        ),
        (
            PermitAuthorizationConflict("hidden"),
            409,
            "PERMIT_AUTHORIZATION_CONFLICT",
        ),
        (
            PermitAuthorizationUnavailable("hidden"),
            503,
            "PERMIT_AUTHORIZATION_UNAVAILABLE",
        ),
    ],
)
def test_authorizer_errors_are_generic(
    error: RuntimeError,
    expected_status: int,
    expected_code: str,
) -> None:
    client, _ = _client(RecordingService(error=error))

    response = client.post(ROUTE, json=_body())

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    assert "hidden" not in response.text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenantId", "00000000-0000-0000-0000-000000000000"),
        ("runtimeExternalPermitId", "00000000-0000-0000-0000-000000000000"),
        ("leaseOwner", " worker-current"),
        ("admissionSnapshotHash", "A" * 64),
        ("operationKind", "MODEL_INVOKE"),
        ("taskExecutionGeneration", 0),
        ("leaseEpoch", 0),
    ],
)
def test_invalid_fences_are_rejected_without_echoing_input(
    field: str,
    value: object,
) -> None:
    client, _ = _client(RecordingService())
    body = _body()
    body[field] = value

    response = client.post(ROUTE, json=body)

    assert response.status_code == 422
    assert response.json() == {
        "code": "PERMIT_AUTHORIZATION_REQUEST_INVALID",
        "message": "The permit authorization request is invalid",
    }


def test_consumed_by_and_any_unknown_body_field_are_forbidden() -> None:
    client, _ = _client(RecordingService())
    body = _body()
    body["consumedBy"] = "body-controlled-principal"

    response = client.post(ROUTE, json=body)

    assert response.status_code == 422
    assert "body-controlled-principal" not in response.text


def test_wire_contract_rejects_python_snake_case_fields() -> None:
    client, _ = _client(RecordingService())
    body = _body()
    body["runtime_run_id"] = body.pop("runtimeRunId")

    response = client.post(ROUTE, json=body)

    assert response.status_code == 422
    assert response.json() == {
        "code": "PERMIT_AUTHORIZATION_REQUEST_INVALID",
        "message": "The permit authorization request is invalid",
    }


class FakeRepository:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[ConsumeRuntimeExternalPermitRequest] = []

    def consume_and_authorize_external_permit(
        self,
        request: ConsumeRuntimeExternalPermitRequest,
    ):
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeProbeResult:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row

    def fetchone(self):
        return self.row


class FakeProbeConnection:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row
        self.closed = False
        self.statement = ""
        self.parameters: tuple[object, ...] = ()

    def execute(self, statement: str, parameters: tuple[object, ...]):
        self.statement = statement
        self.parameters = parameters
        return FakeProbeResult(self.row)

    def close(self) -> None:
        self.closed = True


def _valid_probe_row() -> dict[str, object]:
    return {
        "login_name": "dianlian_supervisor_authorizer",
        "login_can_login": True,
        "login_inherits": True,
        "login_is_restricted": True,
        "has_exact_membership_count": True,
        "has_exact_authorizer_membership": True,
        "authorizer_role_is_sealed": True,
        "is_authorizer": True,
        "is_executor": False,
        "has_schema_usage": True,
        "has_schema_create": False,
        "wrapper_exists": True,
        "can_execute_wrapper": True,
        "can_execute_old_consume": False,
        "has_no_other_function_execute": True,
        "has_no_relation_privileges": True,
        "has_no_column_privileges": True,
        "has_no_sequence_privileges": True,
    }


def _request_model() -> PermitAuthorizationRequest:
    return PermitAuthorizationRequest.model_validate(_body())


def _consumed_fact(command: ConsumeRuntimeExternalPermitRequest) -> RuntimeExternalPermitFact:
    now = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    return RuntimeExternalPermitFact(
        tenant_id=command.tenant_id,
        runtime_external_permit_id=command.runtime_external_permit_id,
        runtime_run_id=command.runtime_run_id,
        runtime_thread_id=uuid4(),
        task_step_id=uuid4(),
        task_execution_generation=command.task_execution_generation,
        admission_contract_version="2.2",
        admission_snapshot_id=command.admission_snapshot_id,
        admission_snapshot_hash=command.admission_snapshot_hash,
        operation_kind=command.operation_kind,
        intent_id=command.intent_id,
        request_hash=command.request_hash,
        lease_owner=command.lease_owner,
        lease_epoch=command.lease_epoch,
        permit_attempt=1,
        status=ExternalPermitStatus.CONSUMED,
        requested_ttl_seconds=30,
        issued_at=now,
        expires_at=now + timedelta(seconds=30),
        issue_event_id=uuid4(),
        consume_event_id=command.consume_event_id,
        consumed_by=command.consumed_by,
        consumed_at=now + timedelta(seconds=1),
        updated_at=now + timedelta(seconds=1),
    )


def _started_service(repository: FakeRepository):
    connection = FakeProbeConnection(_valid_probe_row())
    service = PostgresPermitAuthorizationService(
        repository,  # type: ignore[arg-type]
        lambda: connection,  # type: ignore[arg-type,return-value]
    )
    service.start()
    assert service.ready is True
    assert connection.closed is True
    return service, connection


def test_postgres_service_probes_only_restricted_current_wrapper() -> None:
    repository = FakeRepository(
        PrimitiveResult(outcome=PrimitiveOutcome.NOT_APPLIED, fact=None)
    )
    service, connection = _started_service(repository)

    assert "schema_migration" not in connection.statement
    assert "pg_has_role" in connection.statement
    assert "pg_catalog.pg_auth_members" in connection.statement
    assert "pg_catalog.pg_roles" in connection.statement
    assert "pg_catalog.pg_proc" in connection.statement
    assert "rolbypassrls" in connection.statement
    assert "has_function_privilege" in connection.statement
    assert "has_table_privilege" in connection.statement
    assert "has_column_privilege" in connection.statement
    assert "has_sequence_privilege" in connection.statement
    assert "has_schema_privilege" in connection.statement
    assert "pg_catalog.pg_class" in connection.statement
    assert "pg_catalog.pg_attribute" in connection.statement
    assert "relation_attribute.attnum > 0" in connection.statement
    assert "NOT relation_attribute.attisdropped" in connection.statement
    for relation_name in (
        "runtime_run",
        "runtime_thread",
        "runtime_run_control",
        "runtime_run_event",
        "runtime_checkpoint_ref",
        "runtime_execution_admission_ref",
        "runtime_external_intent",
        "runtime_external_permit_attempt",
        "runtime_external_permit_event",
        "schema_migration",
    ):
        assert relation_name not in connection.statement
    assert len(connection.parameters) == 4

    service.close()
    assert service.ready is False


def test_postgres_factory_bounds_connect_statement_and_lock_waits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeProbeConnection(_valid_probe_row())
    captured: dict[str, object] = {}

    def connect(dsn: str, **kwargs: object):
        captured["dsn"] = dsn
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(
        "dianlian_runtime.supervisor.authorizer.psycopg.connect",
        connect,
    )
    service = create_postgres_permit_authorization_service(
        "postgresql://authorizer.invalid/runtime",
        connect_timeout_seconds=4,
        statement_timeout_seconds=5,
        lock_timeout_seconds=3,
    )

    service.start()

    assert service.ready is True
    assert captured["connect_timeout"] == 4
    assert captured["options"] == (
        "-c statement_timeout=5000 -c lock_timeout=3000"
    )


@pytest.mark.parametrize(
    ("capability", "unsafe_value"),
    [
        ("login_can_login", False),
        ("login_inherits", False),
        ("login_is_restricted", False),
        ("has_exact_membership_count", False),
        ("has_exact_authorizer_membership", False),
        ("authorizer_role_is_sealed", False),
        ("has_schema_create", True),
        ("can_execute_old_consume", True),
        ("has_no_other_function_execute", False),
        ("has_no_relation_privileges", False),
        ("has_no_column_privileges", False),
        ("has_no_sequence_privileges", False),
        ("is_executor", True),
    ],
)
def test_postgres_service_rejects_unsafe_authorizer_capabilities(
    capability: str,
    unsafe_value: object,
) -> None:
    row = _valid_probe_row()
    row[capability] = unsafe_value
    connection = FakeProbeConnection(row)
    service = PostgresPermitAuthorizationService(
        FakeRepository(PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None)),
        lambda: connection,  # type: ignore[arg-type,return-value]
    )

    service.start()

    assert service.ready is False
    assert connection.closed is True


def test_postgres_service_maps_exact_fact_and_derives_consumed_by() -> None:
    class ExactRepository:
        request: ConsumeRuntimeExternalPermitRequest | None = None

        def consume_and_authorize_external_permit(self, request):
            self.request = request
            return PrimitiveResult(
                outcome=PrimitiveOutcome.FACT_RETURNED,
                fact=_consumed_fact(request),
            )

    repository = ExactRepository()
    service, _ = _started_service(repository)  # type: ignore[arg-type]

    outcome = service.authorize(
        _request_model(),
        consumed_by="verified-java-service",
    )

    assert outcome == PermitAuthorizationOutcome.APPLIED
    assert repository.request is not None
    assert repository.request.consumed_by == "verified-java-service"


def test_not_applied_and_invalid_commands_do_not_demote_readiness() -> None:
    not_applied_service, _ = _started_service(
        FakeRepository(PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None))
    )
    assert not_applied_service.authorize(
        _request_model(),
        consumed_by="verified-java-service",
    ) == PermitAuthorizationOutcome.NOT_APPLIED
    assert not_applied_service.ready is True

    invalid_service, _ = _started_service(
        FakeRepository(
            SupervisorInvalidCommand(
                SupervisorErrorCode.INVALID_COMMAND,
                SupervisorPrimitive.CONSUME_AND_AUTHORIZE_EXTERNAL_PERMIT,
                "22023",
                "must not escape",
            )
        )
    )
    with pytest.raises(PermitAuthorizationInvalidCommand):
        invalid_service.authorize(
            _request_model(),
            consumed_by="verified-java-service",
        )
    assert invalid_service.ready is True


def test_postgres_service_fails_closed_on_mismatched_fact_and_database_unknown() -> None:
    request = ConsumeRuntimeExternalPermitRequest(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=PERMIT_ID,
        runtime_run_id=RUN_ID,
        task_execution_generation=3,
        lease_owner="worker-current",
        lease_epoch=7,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=HASH,
        operation_kind=ExternalOperation.ADMISSION_RESOLVE,
        intent_id=INTENT_ID,
        request_hash=HASH,
        consume_event_id=CONSUME_EVENT_ID,
        consumed_by="verified-java-service",
    )
    mismatched = replace(_consumed_fact(request), lease_epoch=8)
    mismatch_service, _ = _started_service(
        FakeRepository(
            PrimitiveResult(
                outcome=PrimitiveOutcome.FACT_RETURNED,
                fact=mismatched,
            )
        )
    )
    with pytest.raises(PermitAuthorizationUnavailable):
        mismatch_service.authorize(
            _request_model(),
            consumed_by="verified-java-service",
        )
    assert mismatch_service.ready is False

    unavailable_service, _ = _started_service(
        FakeRepository(
            SupervisorUnavailable(
                SupervisorErrorCode.UNAVAILABLE,
                SupervisorPrimitive.CONSUME_AND_AUTHORIZE_EXTERNAL_PERMIT,
                "08006",
                "must not escape",
            )
        )
    )
    with pytest.raises(PermitAuthorizationUnavailable, match="unavailable"):
        unavailable_service.authorize(
            _request_model(),
            consumed_by="verified-java-service",
        )
    assert unavailable_service.ready is False

    invalid_service, _ = _started_service(
        FakeRepository(
            SupervisorInvalidCommand(
                SupervisorErrorCode.INVALID_COMMAND,
                SupervisorPrimitive.CONSUME_AND_AUTHORIZE_EXTERNAL_PERMIT,
                "22023",
                "must not escape",
            )
        )
    )
    with pytest.raises(PermitAuthorizationInvalidCommand, match="invalid"):
        invalid_service.authorize(
            _request_model(),
            consumed_by="verified-java-service",
        )
    assert invalid_service.ready is True

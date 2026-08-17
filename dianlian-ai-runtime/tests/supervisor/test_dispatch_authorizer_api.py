from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from dianlian_runtime.app import create_app
from dianlian_runtime.auth import InternalServicePrincipal, InternalServiceScope
from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.supervisor.authorizer_contracts import (
    ExternalDispatchArmApiDecision,
    ExternalDispatchArmRequest,
)
from dianlian_runtime.supervisor.contracts import (
    ConsumeAndArmRuntimeExternalDispatchRequest,
    ExternalDispatchArmDecision,
    ExternalOperation,
    ExternalOperationAttemptStatus,
    ExternalOutcomeEvidenceKind,
    PrimitiveOutcome,
    RuntimeExternalDispatchArmResult,
    RuntimeExternalOperationAttemptFact,
    SupervisorErrorCode,
    SupervisorInvalidCommand,
    SupervisorPrimitive,
    SupervisorUnavailable,
)
from dianlian_runtime.supervisor.dispatch_authorizer import (
    ExternalDispatchArmConflict,
    ExternalDispatchArmInvalidCommand,
    ExternalDispatchArmUnavailable,
    PostgresExternalDispatchArmService,
    create_postgres_external_dispatch_arm_service,
)


ROUTE = "/internal/v1/runtime-supervisor/external-dispatches/consume-and-arm"
TENANT_ID = UUID("00000000-0000-4000-8000-000000000101")
PERMIT_ID = UUID("00000000-0000-4000-8000-000000000102")
RUN_ID = UUID("00000000-0000-4000-8000-000000000103")
ADMISSION_ID = UUID("00000000-0000-4000-8000-000000000104")
INTENT_ID = UUID("00000000-0000-4000-8000-000000000105")
ARM_EVENT_ID = UUID("00000000-0000-4000-8000-000000000106")
HASH = "a" * 64


def _settings(*, enabled: bool) -> RuntimeSettings:
    return RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="runtime-api",
        context_enabled=False,
        agent_enabled=False,
        supervisor_enabled=False,
        dispatch_authorizer_enabled=enabled,
    )


def test_dispatch_authorizer_settings_are_independent_and_hide_the_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIANLIAN_RUNTIME_ROLE", "runtime-api")
    monkeypatch.setenv("DIANLIAN_DISPATCH_AUTHORIZER_ENABLED", "true")
    monkeypatch.setenv(
        "DIANLIAN_DISPATCH_AUTHORIZER_DATABASE_DSN",
        "postgresql://dispatch:secret@example.invalid/runtime",
    )
    monkeypatch.setenv(
        "DIANLIAN_DISPATCH_AUTHORIZER_DATABASE_CONNECT_TIMEOUT_SECONDS", "4"
    )
    monkeypatch.setenv(
        "DIANLIAN_DISPATCH_AUTHORIZER_DATABASE_STATEMENT_TIMEOUT_SECONDS", "5"
    )
    monkeypatch.setenv(
        "DIANLIAN_DISPATCH_AUTHORIZER_DATABASE_LOCK_TIMEOUT_SECONDS", "3"
    )

    settings = RuntimeSettings.from_environment()

    assert settings.dispatch_authorizer_enabled is True
    assert settings.permit_authorizer_enabled is False
    assert settings.dispatch_authorizer_database_connect_timeout_seconds == 4
    assert settings.dispatch_authorizer_database_statement_timeout_seconds == 5
    assert settings.dispatch_authorizer_database_lock_timeout_seconds == 3
    assert "secret" not in repr(settings)
    with pytest.raises(ValueError, match="runtime-api"):
        replace(settings, role="agent-worker")
    with pytest.raises(ValueError, match="lock timeout"):
        replace(
            settings,
            dispatch_authorizer_database_statement_timeout_seconds=2,
            dispatch_authorizer_database_lock_timeout_seconds=3,
        )


def _body(operation_kind: str = "MODEL_INVOKE") -> dict[str, object]:
    return {
        "tenantId": str(TENANT_ID),
        "runtimeExternalPermitId": str(PERMIT_ID),
        "runtimeRunId": str(RUN_ID),
        "taskExecutionGeneration": 3,
        "leaseOwner": "worker-current",
        "leaseEpoch": 7,
        "admissionSnapshotId": str(ADMISSION_ID),
        "admissionSnapshotHash": HASH,
        "operationKind": operation_kind,
        "intentId": str(INTENT_ID),
        "requestHash": HASH,
        "armEventId": str(ARM_EVENT_ID),
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
            token_id=UUID("00000000-0000-4000-8000-000000000143"),
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
        decision: ExternalDispatchArmApiDecision = (
            ExternalDispatchArmApiDecision.GRANTED_NOW
        ),
        *,
        error: RuntimeError | None = None,
    ) -> None:
        self.ready = True
        self.decision = decision
        self.error = error
        self.calls: list[tuple[ExternalDispatchArmRequest, str]] = []

    def arm(
        self,
        request: ExternalDispatchArmRequest,
        *,
        armed_by: str,
    ) -> RuntimeExternalDispatchArmResult:
        self.calls.append((request, armed_by))
        if self.error is not None:
            raise self.error
        if self.decision == ExternalDispatchArmApiDecision.NOT_APPLIED:
            return RuntimeExternalDispatchArmResult(
                outcome=PrimitiveOutcome.NOT_APPLIED,
                decision=None,
                fact=None,
            )
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
        return RuntimeExternalDispatchArmResult(
            outcome=PrimitiveOutcome.FACT_RETURNED,
            decision=ExternalDispatchArmDecision(self.decision.value),
            fact=_attempt_fact(command),
        )


def _expected_grant_fact(operation_kind: str = "MODEL_INVOKE") -> dict[str, object]:
    return {
        "tenantId": str(TENANT_ID),
        "runtimeExternalPermitId": str(PERMIT_ID),
        "runtimeRunId": str(RUN_ID),
        "taskExecutionGeneration": 3,
        "leaseOwner": "worker-current",
        "leaseEpoch": 7,
        "admissionSnapshotId": str(ADMISSION_ID),
        "admissionSnapshotHash": HASH,
        "operationKind": operation_kind,
        "intentId": str(INTENT_ID),
        "requestHash": HASH,
        "armEventId": str(ARM_EVENT_ID),
        "attemptStatus": "DISPATCH_ARMED",
    }


def _client(service: RecordingService):
    authenticator = RecordingAuthenticator()
    app = create_app(
        _settings(enabled=True),
        internal_service_authenticator=authenticator,
        external_dispatch_arm_service=service,
    )
    return TestClient(app), authenticator


@pytest.mark.parametrize("operation_kind", ["MODEL_INVOKE", "TOOL_INVOKE"])
def test_endpoint_uses_exact_scope_and_verified_subject(operation_kind: str) -> None:
    service = RecordingService()
    client, authenticator = _client(service)

    response = client.post(ROUTE, json=_body(operation_kind))

    assert response.status_code == 200
    assert response.json() == {
        "decision": "GRANTED_NOW",
        "grantFact": _expected_grant_fact(operation_kind),
    }
    assert authenticator.required_scopes == [
        InternalServiceScope.RUNTIME_EXTERNAL_DISPATCH_ARM
    ]
    request, armed_by = service.calls[0]
    assert request.operation_kind == operation_kind
    assert armed_by == "verified-java-service"
    assert "armedBy" not in _body()
    operation = client.get("/internal/v1/openapi.json").json()["paths"][ROUTE]["post"]
    assert operation["x-required-scopes"] == ["runtime.external-dispatch.arm"]
    assert operation["security"] == [{"InternalServiceBearer": []}]
    assert "413" in operation["responses"]


def test_high_authority_endpoint_rejects_a_multi_scope_principal() -> None:
    service = RecordingService()
    authenticator = RecordingAuthenticator(
        extra_scope=InternalServiceScope.RUNTIME_EXTERNAL_PERMIT_AUTHORIZE
    )
    client = TestClient(
        create_app(
            _settings(enabled=True),
            internal_service_authenticator=authenticator,
            external_dispatch_arm_service=service,
        )
    )

    response = client.post(ROUTE, json=_body())

    assert response.status_code == 403
    assert service.calls == []


@pytest.mark.parametrize(
    "decision",
    [
        ExternalDispatchArmApiDecision.GRANTED_NOW,
        ExternalDispatchArmApiDecision.DO_NOT_DISPATCH,
        ExternalDispatchArmApiDecision.NOT_APPLIED,
    ],
)
def test_response_returns_the_closed_decision_with_its_exact_grant_fact(
    decision: ExternalDispatchArmApiDecision,
) -> None:
    client, _ = _client(RecordingService(decision))

    response = client.post(ROUTE, json=_body())

    assert response.status_code == 200
    assert response.json() == {
        "decision": decision.value,
        "grantFact": (
            None
            if decision == ExternalDispatchArmApiDecision.NOT_APPLIED
            else _expected_grant_fact()
        ),
    }
    assert "outcome" not in response.json()


def test_disabled_or_missing_dispatch_authorizer_fails_closed() -> None:
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
    assert disabled.post(
        ROUTE,
        content=b"{" + b" " * (8 * 1024),
        headers={"Content-Type": "application/json"},
    ).status_code == 404
    assert disabled.post(
        ROUTE,
        content='{"tenantId":"first","tenantId":"second"}',
        headers={"Content-Type": "application/json"},
    ).status_code == 404
    assert ROUTE not in disabled.get("/internal/v1/openapi.json").json()["paths"]
    response = missing.post(ROUTE, json=_body())
    assert response.status_code == 503
    assert response.json() == {
        "code": "EXTERNAL_DISPATCH_ARM_UNAVAILABLE",
        "message": "External dispatch arm is unavailable",
    }
    assert missing.get("/internal/v1/health/readiness").status_code == 503


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (
            ExternalDispatchArmInvalidCommand("hidden"),
            400,
            "EXTERNAL_DISPATCH_ARM_REQUEST_INVALID",
        ),
        (
            ExternalDispatchArmConflict("hidden"),
            409,
            "EXTERNAL_DISPATCH_ARM_CONFLICT",
        ),
        (
            ExternalDispatchArmUnavailable("hidden"),
            503,
            "EXTERNAL_DISPATCH_ARM_UNAVAILABLE",
        ),
    ],
)
def test_errors_are_generic(
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
        ("leaseOwner", " worker-current"),
        ("admissionSnapshotHash", "A" * 64),
        ("operationKind", "ADMISSION_RESOLVE"),
        ("operationKind", "UNKNOWN"),
        ("taskExecutionGeneration", 0),
        ("leaseEpoch", 0),
    ],
)
def test_invalid_fences_and_operation_kinds_are_rejected(
    field: str,
    value: object,
) -> None:
    client, _ = _client(RecordingService())
    body = _body()
    body[field] = value

    response = client.post(ROUTE, json=body)

    assert response.status_code == 422
    assert response.content == (
        b'{"code":"EXTERNAL_DISPATCH_ARM_REQUEST_INVALID",'
        b'"message":"The external dispatch arm request is invalid"}'
    )


@pytest.mark.parametrize("field", ["armedBy", "runtime_run_id"])
def test_body_forbids_identity_injection_and_snake_case(field: str) -> None:
    client, _ = _client(RecordingService())
    body = _body()
    if field == "armedBy":
        body[field] = "body-controlled-principal"
    else:
        body[field] = body.pop("runtimeRunId")

    response = client.post(ROUTE, json=body)

    assert response.status_code == 422
    assert "body-controlled-principal" not in response.text


@pytest.mark.parametrize(
    ("raw_body", "route"),
    [
        (
            '{"tenantId":"first","tenantId":"second"}',
            ROUTE,
        ),
        (
            '{"extra":{"value":1,"value":2}}',
            ROUTE,
        ),
        (
            '{"tenantId":"first","tenantId":"second"}',
            "/internal/v1/runtime-supervisor/external-permits/consume-and-authorize",
        ),
        (
            '{"extra":{"value":1,"value":2}}',
            "/internal/v1/runtime-supervisor/external-permits/consume-and-authorize",
        ),
    ],
)
def test_high_authority_routes_reject_duplicate_json_keys(
    raw_body: str,
    route: str,
) -> None:
    dispatch_service = RecordingService()
    authenticator = RecordingAuthenticator()
    app = create_app(
        RuntimeSettings(
            service_name="dianlian-ai-runtime",
            service_version="test",
            role="runtime-api",
            context_enabled=False,
            agent_enabled=False,
            supervisor_enabled=False,
            permit_authorizer_enabled=True,
            dispatch_authorizer_enabled=True,
        ),
        internal_service_authenticator=authenticator,
        external_dispatch_arm_service=dispatch_service,
    )

    response = TestClient(app).post(
        route,
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["code"] in {
        "PERMIT_AUTHORIZATION_REQUEST_INVALID",
        "EXTERNAL_DISPATCH_ARM_REQUEST_INVALID",
    }
    assert dispatch_service.calls == []
    assert authenticator.required_scopes == []


def test_high_authority_body_limit_accepts_boundary_and_rejects_larger_streams() -> None:
    service = RecordingService()
    client, authenticator = _client(service)
    compact = json.dumps(_body(), separators=(",", ":"))
    boundary = compact + " " * (8 * 1024 - len(compact.encode("utf-8")))

    accepted = client.post(
        ROUTE,
        content=boundary,
        headers={"Content-Type": "application/json"},
    )
    too_large_with_length = client.post(
        ROUTE,
        content=boundary + " ",
        headers={"Content-Type": "application/json"},
    )
    too_large_streamed = client.post(
        ROUTE,
        content=(
            chunk
            for chunk in (
                compact.encode("utf-8"),
                b" " * (8 * 1024),
            )
        ),
        headers={"Content-Type": "application/json"},
    )

    assert accepted.status_code == 200
    assert too_large_with_length.status_code == 413
    assert too_large_streamed.status_code == 413
    assert too_large_with_length.json() == too_large_streamed.json() == {
        "code": "EXTERNAL_DISPATCH_ARM_REQUEST_TOO_LARGE",
        "message": "The external dispatch arm request is too large",
    }
    assert len(service.calls) == 1
    assert authenticator.required_scopes == [
        InternalServiceScope.RUNTIME_EXTERNAL_DISPATCH_ARM
    ]


def test_guard_recursion_failure_is_a_generic_422_before_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = RecordingService()
    client, authenticator = _client(service)
    monkeypatch.setattr(
        "dianlian_runtime.app.json.loads",
        lambda *args, **kwargs: (_ for _ in ()).throw(RecursionError()),
    )

    response = client.post(
        ROUTE,
        json=_body(),
    )

    assert response.status_code == 422
    assert response.content == (
        b'{"code":"EXTERNAL_DISPATCH_ARM_REQUEST_INVALID",'
        b'"message":"The external dispatch arm request is invalid"}'
    )
    assert service.calls == []
    assert authenticator.required_scopes == []


@pytest.mark.parametrize("raw_body", ["[]", "true", "null", '"value"', "1"])
def test_non_object_json_is_rejected_before_authentication(raw_body: str) -> None:
    service = RecordingService()
    client, authenticator = _client(service)

    response = client.post(
        ROUTE,
        content=raw_body,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert service.calls == []
    assert authenticator.required_scopes == []


class FakeRepository:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[ConsumeAndArmRuntimeExternalDispatchRequest] = []

    def consume_and_arm_external_dispatch(
        self,
        request: ConsumeAndArmRuntimeExternalDispatchRequest,
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
        "login_name": "dianlian_supervisor_dispatch_login",
        "login_can_login": True,
        "login_inherits": True,
        "login_is_restricted": True,
        "has_exact_membership_count": True,
        "has_exact_dispatch_authorizer_membership": True,
        "dispatch_authorizer_role_is_sealed": True,
        "is_dispatch_authorizer": True,
        "is_permit_authorizer": False,
        "is_outcome_reconciler": False,
        "is_executor": False,
        "has_schema_usage": True,
        "has_schema_create": False,
        "wrapper_exists": True,
        "can_execute_wrapper": True,
        "has_no_other_function_execute": True,
        "has_no_relation_privileges": True,
        "has_no_column_privileges": True,
        "has_no_sequence_privileges": True,
    }


def _request_model() -> ExternalDispatchArmRequest:
    return ExternalDispatchArmRequest.model_validate(_body())


def _attempt_fact(
    command: ConsumeAndArmRuntimeExternalDispatchRequest,
    *,
    status: ExternalOperationAttemptStatus = (
        ExternalOperationAttemptStatus.DISPATCH_ARMED
    ),
) -> RuntimeExternalOperationAttemptFact:
    now = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    terminal = status != ExternalOperationAttemptStatus.DISPATCH_ARMED
    return RuntimeExternalOperationAttemptFact(
        tenant_id=command.tenant_id,
        runtime_external_permit_id=command.runtime_external_permit_id,
        runtime_run_id=command.runtime_run_id,
        operation_kind=command.operation_kind,
        intent_id=command.intent_id,
        permit_attempt=1,
        task_execution_generation=command.task_execution_generation,
        admission_snapshot_id=command.admission_snapshot_id,
        admission_snapshot_hash=command.admission_snapshot_hash,
        request_hash=command.request_hash,
        lease_owner=command.lease_owner,
        lease_epoch=command.lease_epoch,
        arm_event_id=command.arm_event_id,
        armed_by=command.armed_by,
        armed_at=now,
        status=status,
        last_event_id=(
            UUID("00000000-0000-4000-8000-000000000107")
            if terminal
            else command.arm_event_id
        ),
        source_fact_id=(
            UUID("00000000-0000-4000-8000-000000000108") if terminal else None
        ),
        source_fact_version=1 if terminal else None,
        source_fact_hash=HASH if terminal else None,
        outcome_code="CANONICAL_OUTCOME" if terminal else None,
        evidence_kind=(
            ExternalOutcomeEvidenceKind.JAVA_CANONICAL_FACT if terminal else None
        ),
        result_hash=None,
        recorded_by="dianlian-platform" if terminal else None,
        outcome_recorded_at=now if terminal else None,
        updated_at=now,
    )


def _started_service(repository: FakeRepository):
    connection = FakeProbeConnection(_valid_probe_row())
    service = PostgresExternalDispatchArmService(
        repository,  # type: ignore[arg-type]
        lambda: connection,  # type: ignore[arg-type,return-value]
    )
    service.start()
    assert service.ready is True
    assert connection.closed is True
    return service, connection


def test_readiness_probes_only_the_restricted_dispatch_wrapper() -> None:
    repository = FakeRepository(
        RuntimeExternalDispatchArmResult(
            outcome=PrimitiveOutcome.NOT_APPLIED,
            decision=None,
            fact=None,
        )
    )
    service, connection = _started_service(repository)

    assert "dianlian_supervisor_dispatch_authorizer" in connection.statement
    assert "dianlian_supervisor_permit_authorizer" in connection.statement
    assert "dianlian_supervisor_outcome_reconciler" in connection.statement
    assert "pg_catalog.pg_attribute" in connection.statement
    assert "has_column_privilege" in connection.statement
    assert "relation_attribute.attnum > 0" in connection.statement
    assert len(connection.parameters) == 3
    assert all("consume_and_arm_runtime_external_dispatch" in p for p in connection.parameters)
    service.close()
    assert service.ready is False


@pytest.mark.parametrize(
    ("capability", "unsafe_value"),
    [
        ("has_exact_membership_count", False),
        ("has_exact_dispatch_authorizer_membership", False),
        ("dispatch_authorizer_role_is_sealed", False),
        ("is_permit_authorizer", True),
        ("is_outcome_reconciler", True),
        ("is_executor", True),
        ("has_schema_create", True),
        ("has_no_other_function_execute", False),
        ("has_no_relation_privileges", False),
        ("has_no_column_privileges", False),
        ("has_no_sequence_privileges", False),
    ],
)
def test_readiness_rejects_unsafe_dispatch_capabilities(
    capability: str,
    unsafe_value: object,
) -> None:
    row = _valid_probe_row()
    row[capability] = unsafe_value
    connection = FakeProbeConnection(row)
    service = PostgresExternalDispatchArmService(
        FakeRepository(object()),
        lambda: connection,  # type: ignore[arg-type,return-value]
    )

    service.start()

    assert service.ready is False
    assert connection.closed is True


def test_factory_uses_independent_bounded_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeProbeConnection(_valid_probe_row())
    captured: dict[str, object] = {}

    def connect(dsn: str, **kwargs: object):
        captured["dsn"] = dsn
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(
        "dianlian_runtime.supervisor.dispatch_authorizer.psycopg.connect",
        connect,
    )
    service = create_postgres_external_dispatch_arm_service(
        "postgresql://dispatch.invalid/runtime",
        connect_timeout_seconds=4,
        statement_timeout_seconds=5,
        lock_timeout_seconds=3,
    )

    service.start()

    assert service.ready is True
    assert captured["connect_timeout"] == 4
    assert captured["options"] == "-c statement_timeout=5000 -c lock_timeout=3000"


@pytest.mark.parametrize(
    ("repository_decision", "status"),
    [
        (
            ExternalDispatchArmDecision.GRANTED_NOW,
            ExternalOperationAttemptStatus.DISPATCH_ARMED,
        ),
        (
            ExternalDispatchArmDecision.DO_NOT_DISPATCH,
            ExternalOperationAttemptStatus.DISPATCH_ARMED,
        ),
    ],
)
def test_service_maps_exact_typed_decisions_and_derives_armed_by(
    repository_decision: ExternalDispatchArmDecision,
    status: ExternalOperationAttemptStatus,
) -> None:
    class ExactRepository:
        request: ConsumeAndArmRuntimeExternalDispatchRequest | None = None

        def consume_and_arm_external_dispatch(self, request):
            self.request = request
            return RuntimeExternalDispatchArmResult(
                outcome=PrimitiveOutcome.FACT_RETURNED,
                decision=repository_decision,
                fact=_attempt_fact(request, status=status),
            )

    repository = ExactRepository()
    service, _ = _started_service(repository)  # type: ignore[arg-type]

    result = service.arm(_request_model(), armed_by="verified-java-service")

    assert result.decision == repository_decision
    assert result.fact is not None
    assert result.fact.status == status
    assert repository.request is not None
    assert repository.request.armed_by == "verified-java-service"


def test_not_applied_and_invalid_command_keep_readiness() -> None:
    not_applied_service, _ = _started_service(
        FakeRepository(
            RuntimeExternalDispatchArmResult(
                outcome=PrimitiveOutcome.NOT_APPLIED,
                decision=None,
                fact=None,
            )
        )
    )
    not_applied_result = not_applied_service.arm(
        _request_model(), armed_by="verified-java-service"
    )
    assert not_applied_result.outcome == PrimitiveOutcome.NOT_APPLIED
    assert not_applied_result.decision is None
    assert not_applied_result.fact is None
    assert not_applied_service.ready is True

    invalid_service, _ = _started_service(
        FakeRepository(
            SupervisorInvalidCommand(
                SupervisorErrorCode.INVALID_COMMAND,
                SupervisorPrimitive.CONSUME_AND_ARM_EXTERNAL_DISPATCH,
                "22023",
                "must not escape",
            )
        )
    )
    with pytest.raises(ExternalDispatchArmInvalidCommand):
        invalid_service.arm(_request_model(), armed_by="verified-java-service")
    assert invalid_service.ready is True


def test_service_fails_closed_on_bad_fact_subject_and_unknown_outcome() -> None:
    class MismatchedRepository:
        def consume_and_arm_external_dispatch(self, request):
            fact = replace(_attempt_fact(request), lease_epoch=request.lease_epoch + 1)
            return RuntimeExternalDispatchArmResult(
                outcome=PrimitiveOutcome.FACT_RETURNED,
                decision=ExternalDispatchArmDecision.GRANTED_NOW,
                fact=fact,
            )

    mismatch_service, _ = _started_service(MismatchedRepository())  # type: ignore[arg-type]
    with pytest.raises(ExternalDispatchArmUnavailable):
        mismatch_service.arm(_request_model(), armed_by="verified-java-service")
    assert mismatch_service.ready is False

    subject_service, _ = _started_service(FakeRepository(object()))
    with pytest.raises(ExternalDispatchArmInvalidCommand):
        subject_service.arm(_request_model(), armed_by=" untrusted")
    assert subject_service.ready is True

    unknown_service, _ = _started_service(
        FakeRepository(
            SupervisorUnavailable(
                SupervisorErrorCode.UNAVAILABLE,
                SupervisorPrimitive.CONSUME_AND_ARM_EXTERNAL_DISPATCH,
                "08006",
                "must not escape",
            )
        )
    )
    with pytest.raises(ExternalDispatchArmUnavailable):
        unknown_service.arm(_request_model(), armed_by="verified-java-service")
    assert unknown_service.ready is False

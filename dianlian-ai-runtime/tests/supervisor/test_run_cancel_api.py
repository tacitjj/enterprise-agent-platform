from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

from fastapi.testclient import TestClient
import pytest

from dianlian_runtime.app import create_app
from dianlian_runtime.auth import InternalServicePrincipal, InternalServiceScope
from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.supervisor.authorizer_contracts import (
    RuntimeRunCancelApiResult,
    RuntimeRunCancelRequest,
)
from dianlian_runtime.supervisor.control import (
    PostgresRuntimeRunCancelService,
    RuntimeRunCancelInvalidCommand,
    RuntimeRunCancelUnavailable,
)
from dianlian_runtime.supervisor.contracts import (
    PrimitiveOutcome,
    PrimitiveResult,
    RequestRuntimeRunCancelRequest,
    RuntimeRunControlFact,
)


ROUTE = "/internal/v1/runtime-supervisor/run-cancellations/request"
TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
RUN_ID = UUID("00000000-0000-4000-8000-000000000002")
CANCEL_ID = UUID("00000000-0000-4000-8000-000000000003")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000004")
THREAD_ID = UUID("00000000-0000-4000-8000-000000000005")
HASH = "a" * 64


def _settings(*, enabled: bool) -> RuntimeSettings:
    return RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="runtime-api",
        context_enabled=False,
        agent_enabled=False,
        supervisor_enabled=False,
        run_controller_enabled=enabled,
    )


def _body() -> dict[str, object]:
    return {
        "tenantId": str(TENANT_ID),
        "runtimeRunId": str(RUN_ID),
        "cancelRequestId": str(CANCEL_ID),
        "actorId": str(ACTOR_ID),
        "reasonCode": "USER_REQUESTED",
        "expectedRunVersion": 7,
        "idempotencyKey": "cancel-command-0001",
        "requestHash": HASH,
    }


class RecordingAuthenticator:
    def __init__(self, *, extra_scope: InternalServiceScope | None = None) -> None:
        self.ready = True
        self.extra_scope = extra_scope
        self.required_scopes: list[InternalServiceScope] = []

    def authorize(self, token: str, required_scope: InternalServiceScope):
        del token
        self.required_scopes.append(required_scope)
        scopes = {required_scope}
        if self.extra_scope is not None:
            scopes.add(self.extra_scope)
        return InternalServicePrincipal(
            subject="verified-java-service",
            token_id=UUID("00000000-0000-4000-8000-000000000006"),
            scopes=frozenset(scopes),
            issued_at=0,
            expires_at=60,
        )


class RecordingService:
    def __init__(
        self,
        outcome: RuntimeRunCancelApiResult = RuntimeRunCancelApiResult.APPLIED,
    ) -> None:
        self.ready = True
        self.outcome = outcome
        self.calls: list[tuple[RuntimeRunCancelRequest, str]] = []

    def request_cancel(
        self,
        request: RuntimeRunCancelRequest,
        *,
        requested_by: str,
    ) -> RuntimeRunCancelApiResult:
        self.calls.append((request, requested_by))
        return self.outcome


def test_run_cancel_endpoint_uses_exact_scope_and_verified_service_subject() -> None:
    service = RecordingService()
    authenticator = RecordingAuthenticator()
    client = TestClient(
        create_app(
            _settings(enabled=True),
            internal_service_authenticator=authenticator,
            runtime_run_cancel_service=service,
        )
    )

    response = client.post(ROUTE, json=_body())

    assert response.status_code == 200
    assert response.json() == {"outcome": "APPLIED"}
    assert authenticator.required_scopes == [InternalServiceScope.RUNTIME_RUN_CANCEL]
    assert service.calls[0][1] == "verified-java-service"
    operation = client.get("/internal/v1/openapi.json").json()["paths"][ROUTE]["post"]
    assert operation["x-required-scopes"] == ["runtime.run.cancel"]
    assert "413" in operation["responses"]


def test_run_cancel_is_default_hidden_and_missing_service_fails_closed() -> None:
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
    assert missing.post(ROUTE, json=_body()).status_code == 503
    assert missing.get("/internal/v1/health/readiness").status_code == 503


def test_run_cancel_rejects_multi_scope_duplicate_and_unknown_fields() -> None:
    service = RecordingService()
    multi_scope = TestClient(
        create_app(
            _settings(enabled=True),
            internal_service_authenticator=RecordingAuthenticator(
                extra_scope=InternalServiceScope.RUNTIME_EXTERNAL_DISPATCH_ARM
            ),
            runtime_run_cancel_service=service,
        )
    )
    assert multi_scope.post(ROUTE, json=_body()).status_code == 403
    assert service.calls == []

    client = TestClient(
        create_app(
            _settings(enabled=True),
            internal_service_authenticator=RecordingAuthenticator(),
            runtime_run_cancel_service=service,
        )
    )
    duplicate = client.post(
        ROUTE,
        content=(
            '{"tenantId":"%s","tenantId":"%s"}' % (TENANT_ID, TENANT_ID)
        ),
        headers={"Content-Type": "application/json"},
    )
    assert duplicate.status_code == 422
    body = _body()
    body["eventPayload"] = {"bodyControlled": True}
    assert client.post(ROUTE, json=body).status_code == 422
    assert service.calls == []


def test_run_cancel_not_applied_is_plain_200() -> None:
    client = TestClient(
        create_app(
            _settings(enabled=True),
            internal_service_authenticator=RecordingAuthenticator(),
            runtime_run_cancel_service=RecordingService(
                RuntimeRunCancelApiResult.NOT_APPLIED
            ),
        )
    )

    response = client.post(ROUTE, json=_body())

    assert response.status_code == 200
    assert response.json() == {"outcome": "NOT_APPLIED"}


def test_run_controller_settings_are_opt_in_role_bound_and_hide_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIANLIAN_RUNTIME_ROLE", "runtime-api")
    monkeypatch.setenv("DIANLIAN_RUN_CONTROLLER_ENABLED", "true")
    monkeypatch.setenv(
        "DIANLIAN_RUN_CONTROLLER_DATABASE_DSN",
        "postgresql://controller:secret@example.invalid/runtime",
    )

    settings = RuntimeSettings.from_environment()

    assert settings.run_controller_enabled is True
    assert "secret" not in repr(settings)
    with pytest.raises(ValueError, match="runtime-api"):
        replace(settings, role="agent-worker")


class FakeRepository:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[RequestRuntimeRunCancelRequest] = []

    def request_cancel(self, request: RequestRuntimeRunCancelRequest):
        self.requests.append(request)
        return self.result


class ReadinessConnection:
    def execute(self, _sql: str, _parameters: object):
        return self

    def fetchone(self):
        return {
            "login_name": "dianlian_supervisor_controller_login",
            "login_can_login": True,
            "login_inherits": True,
            "login_is_restricted": True,
            "has_exact_membership_count": True,
            "has_exact_controller_membership": True,
            "controller_role_is_sealed": True,
            "is_controller": True,
            "is_executor": False,
            "is_permit_authorizer": False,
            "is_dispatch_authorizer": False,
            "is_outcome_reconciler": False,
            "has_schema_usage": True,
            "has_schema_create": False,
            "wrapper_exists": True,
            "can_execute_wrapper": True,
            "has_no_other_function_execute": True,
            "has_no_relation_privileges": True,
            "has_no_column_privileges": True,
            "has_no_sequence_privileges": True,
        }

    def close(self) -> None:
        return None


def test_postgres_run_cancel_service_builds_fixed_event_and_verifies_fact() -> None:
    fact = RuntimeRunControlFact(
        tenant_id=TENANT_ID,
        control_id=CANCEL_ID,
        runtime_run_id=RUN_ID,
        runtime_thread_id=THREAD_ID,
        control_type="CANCEL",
        actor_id=ACTOR_ID,
        reason_code="USER_REQUESTED",
        expected_run_version=7,
        idempotency_key="cancel-command-0001",
        request_hash=HASH,
        created_at=datetime.now(timezone.utc),
    )
    repository = FakeRepository(PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, fact))
    service = PostgresRuntimeRunCancelService(repository, ReadinessConnection)
    service.start()

    result = service.request_cancel(
        RuntimeRunCancelRequest.model_validate(_body()),
        requested_by="verified-java-service",
    )

    assert result == RuntimeRunCancelApiResult.APPLIED
    payload = repository.requests[0].event_payload.to_builtin()
    assert payload == {
        "schemaVersion": "runtime-run-cancel-request-v1",
        "cancelRequestId": str(CANCEL_ID),
        "actorId": str(ACTOR_ID),
        "reasonCode": "USER_REQUESTED",
        "requestedByService": "verified-java-service",
    }

    with pytest.raises(RuntimeRunCancelInvalidCommand):
        service.request_cancel(
            RuntimeRunCancelRequest.model_validate(_body()),
            requested_by=" invalid-service ",
        )
    assert len(repository.requests) == 1

    repository.result = PrimitiveResult(
        PrimitiveOutcome.FACT_RETURNED,
        replace(fact, actor_id=UUID("00000000-0000-4000-8000-000000000099")),
    )
    with pytest.raises(RuntimeRunCancelUnavailable):
        service.request_cancel(
            RuntimeRunCancelRequest.model_validate(_body()),
            requested_by="verified-java-service",
        )
    assert service.ready is False

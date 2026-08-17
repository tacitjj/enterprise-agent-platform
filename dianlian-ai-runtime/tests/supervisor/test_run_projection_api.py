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
from dianlian_runtime.supervisor.run_projection import (
    PostgresRuntimeRunProjectionService,
    RuntimeRunProjectionNotFound,
    RuntimeRunProjectionRequest,
    RuntimeRunProjectionResponse,
    RuntimeRunProjectionUnavailable,
)


ROUTE = "/internal/v1/runtime-supervisor/run-projections/read"
HASH = "a" * 64


def _uuid(value: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{value:012d}")


def _settings(*, enabled: bool) -> RuntimeSettings:
    return RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="runtime-api",
        context_enabled=False,
        agent_enabled=False,
        supervisor_enabled=False,
        run_observer_enabled=enabled,
    )


def _body() -> dict[str, object]:
    return {
        "tenantId": str(_uuid(1)),
        "runtimeRunId": str(_uuid(2)),
        "taskStepId": str(_uuid(3)),
        "taskExecutionGeneration": 4,
        "requestHash": HASH,
        "afterSequence": 0,
        "pageSize": 64,
    }


def _projection_payload() -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "tenantId": str(_uuid(1)),
        "runtimeRunId": str(_uuid(2)),
        "runtimeThreadId": str(_uuid(5)),
        "taskStepId": str(_uuid(3)),
        "taskExecutionGeneration": 4,
        "status": "RUNNING",
        "operationKind": "START",
        "requestHash": HASH,
        "currentCheckpointId": None,
        "currentCheckpointSequenceNo": None,
        "nextEventSequenceNo": 2,
        "eventRetentionFloorSequence": 1,
        "runVersion": 2,
        "terminalReason": None,
        "terminalEventId": None,
        "leaseEpoch": 1,
        "attempt": 1,
        "runtimeVersion": "runtime-v1",
        "agentName": "agent-worker",
        "failureCode": None,
        "cancelRequestedAt": None,
        "startedAt": now,
        "terminalAt": None,
        "createdAt": now,
        "updatedAt": now,
        "afterSequence": 0,
        "nextSequence": 1,
        "hasMore": False,
        "replayGap": False,
        "events": [
            {
                "eventId": str(_uuid(6)),
                "sequenceNo": 1,
                "eventType": "RUN_STARTED",
                "eventVersion": 1,
                "runVersion": 2,
                "leaseOwner": "agent-worker",
                "leaseEpoch": 1,
                "checkpointId": None,
                "payload": {"source": "test"},
                "occurredAt": now,
                "createdAt": now,
            }
        ],
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
            subject="dianlian-platform",
            token_id=_uuid(99),
            scopes=frozenset(scopes),
            issued_at=1,
            expires_at=2,
        )


class RecordingProjectionService:
    ready = True

    def __init__(self) -> None:
        self.calls: list[RuntimeRunProjectionRequest] = []

    def read(self, request: RuntimeRunProjectionRequest) -> RuntimeRunProjectionResponse:
        self.calls.append(request)
        return RuntimeRunProjectionResponse.model_validate(_projection_payload())


def test_projection_route_is_default_hidden_and_enabled_route_is_exact_scoped() -> None:
    disabled = create_app(
        settings=_settings(enabled=False),
        internal_service_authenticator=RecordingAuthenticator(),
    )
    with TestClient(disabled) as client:
        assert client.post(ROUTE, content=b"{" * 9000).status_code == 404

    authenticator = RecordingAuthenticator()
    service = RecordingProjectionService()
    enabled = create_app(
        settings=_settings(enabled=True),
        internal_service_authenticator=authenticator,
        runtime_run_projection_service=service,
    )
    with TestClient(enabled) as client:
        response = client.post(ROUTE, json=_body())
        assert response.status_code == 200
        assert response.json()["runtimeRunId"] == str(_uuid(2))
        assert response.json()["events"][0]["sequenceNo"] == 1
        operation = client.get("/internal/v1/openapi.json").json()["paths"][ROUTE]["post"]
        assert operation["x-required-scopes"] == ["runtime.run.observe"]
        assert "413" in operation["responses"]
    assert authenticator.required_scopes == [InternalServiceScope.RUNTIME_RUN_OBSERVE]
    assert len(service.calls) == 1


def test_projection_route_rejects_multi_scope_duplicate_and_oversized_requests() -> None:
    service = RecordingProjectionService()
    multi_scope = create_app(
        settings=_settings(enabled=True),
        internal_service_authenticator=RecordingAuthenticator(
            extra_scope=InternalServiceScope.RUNTIME_RUN_ADMIT
        ),
        runtime_run_projection_service=service,
    )
    with TestClient(multi_scope) as client:
        assert client.post(ROUTE, json=_body()).status_code == 403
    assert service.calls == []

    exact = create_app(
        settings=_settings(enabled=True),
        internal_service_authenticator=RecordingAuthenticator(),
        runtime_run_projection_service=service,
    )
    duplicate = json.dumps(_body(), separators=(",", ":"))[:-1] + ',"pageSize":1}'
    with TestClient(exact) as client:
        response = client.post(
            ROUTE,
            content=duplicate,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "RUNTIME_RUN_PROJECTION_REQUEST_INVALID"
        response = client.post(
            ROUTE,
            content=json.dumps(_body()).encode() + b" " * (8 * 1024),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
    assert service.calls == []


class FakeConnection:
    def __init__(self, row: dict[str, object] | None) -> None:
        self.row = row
        self.parameters: object | None = None
        self.closed = False

    def execute(self, _sql: str, parameters: object):
        self.parameters = parameters
        return self

    def fetchone(self):
        return self.row

    def close(self) -> None:
        self.closed = True


def _readiness_row() -> dict[str, object]:
    return {
        "login_name": "dianlian_supervisor_run_observer_login",
        "login_can_login": True,
        "login_inherits": True,
        "login_is_restricted": True,
        "has_exact_membership_count": True,
        "has_exact_run_observer_membership": True,
        "run_observer_role_is_sealed": True,
        "is_run_observer": True,
        "is_executor": False,
        "is_permit_authorizer": False,
        "is_dispatch_authorizer": False,
        "is_outcome_reconciler": False,
        "is_controller": False,
        "is_run_admitter": False,
        "has_schema_usage": True,
        "has_schema_create": False,
        "wrapper_exists": True,
        "can_execute_wrapper": True,
        "has_no_other_function_execute": True,
        "has_no_relation_privileges": True,
        "has_no_column_privileges": True,
        "has_no_sequence_privileges": True,
    }


def _database_row() -> dict[str, object]:
    payload = _projection_payload()
    return {
        "tenant_id": UUID(str(payload["tenantId"])),
        "runtime_run_id": UUID(str(payload["runtimeRunId"])),
        "runtime_thread_id": UUID(str(payload["runtimeThreadId"])),
        "task_step_id": UUID(str(payload["taskStepId"])),
        "task_execution_generation": payload["taskExecutionGeneration"],
        "status": payload["status"],
        "operation_kind": payload["operationKind"],
        "request_hash": payload["requestHash"],
        "current_checkpoint_id": None,
        "current_checkpoint_sequence_no": None,
        "next_event_sequence_no": payload["nextEventSequenceNo"],
        "event_retention_floor_sequence": payload["eventRetentionFloorSequence"],
        "run_version": payload["runVersion"],
        "terminal_reason": None,
        "terminal_event_id": None,
        "lease_epoch": payload["leaseEpoch"],
        "attempt": payload["attempt"],
        "runtime_version": payload["runtimeVersion"],
        "agent_name": payload["agentName"],
        "failure_code": None,
        "cancel_requested_at": None,
        "started_at": datetime.fromisoformat(str(payload["startedAt"])),
        "terminal_at": None,
        "created_at": datetime.fromisoformat(str(payload["createdAt"])),
        "updated_at": datetime.fromisoformat(str(payload["updatedAt"])),
        "after_sequence": payload["afterSequence"],
        "next_sequence": payload["nextSequence"],
        "has_more": payload["hasMore"],
        "replay_gap": payload["replayGap"],
        "events": payload["events"],
    }


def test_postgres_projection_service_uses_exact_query_and_fails_closed_on_drift() -> None:
    readiness = FakeConnection(_readiness_row())
    query = FakeConnection(_database_row())
    connections = iter([readiness, query])
    service = PostgresRuntimeRunProjectionService(lambda: next(connections))
    service.start()
    request = RuntimeRunProjectionRequest.model_validate(_body())

    projection = service.read(request)

    assert projection.runtime_run_id == _uuid(2)
    assert query.parameters == (_uuid(1), _uuid(2), _uuid(3), 4, HASH, 0, 64)
    assert readiness.closed is True
    assert query.closed is True

    mismatch = _database_row()
    mismatch["task_step_id"] = _uuid(999)
    readiness = FakeConnection(_readiness_row())
    query = FakeConnection(mismatch)
    connections = iter([readiness, query])
    service = PostgresRuntimeRunProjectionService(lambda: next(connections))
    service.start()
    with pytest.raises(RuntimeRunProjectionUnavailable):
        service.read(request)
    assert service.ready is False


def test_postgres_projection_service_keeps_not_found_distinct_from_unavailable() -> None:
    connections = iter([FakeConnection(_readiness_row()), FakeConnection(None)])
    service = PostgresRuntimeRunProjectionService(lambda: next(connections))
    service.start()

    with pytest.raises(RuntimeRunProjectionNotFound):
        service.read(RuntimeRunProjectionRequest.model_validate(_body()))
    assert service.ready is True


def test_run_observer_settings_are_opt_in_role_bound_and_hide_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIANLIAN_RUNTIME_ROLE", "runtime-api")
    monkeypatch.setenv("DIANLIAN_RUN_OBSERVER_ENABLED", "true")
    monkeypatch.setenv(
        "DIANLIAN_RUN_OBSERVER_DATABASE_DSN",
        "postgresql://run-observer:secret@example.invalid/runtime",
    )

    settings = RuntimeSettings.from_environment()

    assert settings.run_observer_enabled is True
    assert "secret" not in repr(settings)
    with pytest.raises(ValueError, match="runtime-api"):
        replace(settings, role="agent-worker")

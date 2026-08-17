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
    RuntimeRunAdmissionApiResult,
    RuntimeRunAdmissionRequest,
)
from dianlian_runtime.supervisor.contracts import (
    AdmitRuntimeRunRequest,
    MultitaskStrategy,
    OperationKind,
    PrimitiveOutcome,
    PrimitiveResult,
    RuntimeRunFact,
    RuntimeStatus,
)
from dianlian_runtime.supervisor.run_admitter import (
    PostgresRuntimeRunAdmissionService,
    RuntimeRunAdmissionUnavailable,
)


ROUTE = "/internal/v1/runtime-supervisor/run-admissions/admit"
HASH = "a" * 64
PROFILE_HASH = "b" * 64


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
        run_admitter_enabled=enabled,
    )


def _body(*, artifact_count: int = 2) -> dict[str, object]:
    artifact_ids = [str(_uuid(100 + index)) for index in range(artifact_count)]
    body: dict[str, object] = {
        "tenantId": str(_uuid(1)),
        "runtimeThreadId": str(_uuid(2)),
        "taskRunId": str(_uuid(3)),
        "taskStepId": str(_uuid(4)),
        "agentInstanceId": str(_uuid(5)),
        "userId": str(_uuid(6)),
        "sourceKind": "CONVERSATION",
        "conversationId": str(_uuid(7)),
        "sourceMessageId": str(_uuid(8)),
        "runtimeThreadRevision": 9,
        "runtimeType": "DEERFLOW",
        "runtimeAgentName": "runtime-agent",
        "capabilityVersionId": str(_uuid(10)),
        "promptVersionId": str(_uuid(11)),
        "modelPolicyId": str(_uuid(12)),
        "budgetReservationId": str(_uuid(13)),
        "inputArtifactIds": artifact_ids,
        "runtimeRunId": str(_uuid(14)),
        "taskExecutionGeneration": 15,
        "operationKind": "START",
        "multitaskStrategy": "REJECT",
        "requestHash": HASH,
        "idempotencyKey": "runtime-run-admission-0001",
        "predecessorRuntimeRunId": None,
        "expectedCheckpointId": None,
        "runtimeVersion": "runtime-v1",
        "agentName": "agent-worker",
        "admissionContractVersion": "2.2",
        "admissionSnapshotId": str(_uuid(16)),
        "admissionSnapshotHash": HASH,
        "acceptedEventId": str(_uuid(17)),
    }
    body["acceptedEventPayload"] = {
        "schemaVersion": "runtime-run-accepted-v2",
        "runtimeThreadId": body["runtimeThreadId"],
        "runtimeThreadRevision": body["runtimeThreadRevision"],
        "runtimeRunId": body["runtimeRunId"],
        "taskRunId": body["taskRunId"],
        "taskStepId": body["taskStepId"],
        "agentInstanceId": body["agentInstanceId"],
        "taskExecutionGeneration": body["taskExecutionGeneration"],
        "admissionSnapshotId": body["admissionSnapshotId"],
        "admissionSnapshotHash": body["admissionSnapshotHash"],
        "requestHash": body["requestHash"],
        "executionPlanVersion": 3,
        "executionTemplateCode": "QUOTATION",
        "executionTemplateVersion": "v3",
        "stepKey": "INITIAL_ANALYSIS",
        "executionProfileHash": PROFILE_HASH,
        "inputArtifactIds": artifact_ids,
    }
    return body


def _structured_body(*, artifact_count: int = 2) -> dict[str, object]:
    body = _body(artifact_count=artifact_count)
    body["sourceKind"] = "TASK_STEP"
    body["conversationId"] = None
    body["sourceMessageId"] = None
    body["runtimeThreadRevision"] = body["taskExecutionGeneration"]
    body["runtimeType"] = "JAVA_CAPABILITY_STRUCTURED"
    body["admissionContractVersion"] = "3.0"
    event = dict(body["acceptedEventPayload"])  # type: ignore[arg-type]
    event["schemaVersion"] = "runtime-run-accepted-v3"
    event["sourceKind"] = "TASK_STEP"
    event["runtimeThreadRevision"] = body["runtimeThreadRevision"]
    body["acceptedEventPayload"] = event
    return body


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
            token_id=_uuid(18),
            scopes=frozenset(scopes),
            issued_at=0,
            expires_at=60,
        )


class RecordingService:
    def __init__(
        self,
        outcome: RuntimeRunAdmissionApiResult = RuntimeRunAdmissionApiResult.APPLIED,
    ) -> None:
        self.ready = True
        self.outcome = outcome
        self.calls: list[RuntimeRunAdmissionRequest] = []

    def admit(
        self,
        request: RuntimeRunAdmissionRequest,
    ) -> RuntimeRunAdmissionApiResult:
        self.calls.append(request)
        return self.outcome


def test_run_admission_endpoint_is_exact_scope_and_default_hidden() -> None:
    service = RecordingService()
    authenticator = RecordingAuthenticator()
    client = TestClient(
        create_app(
            _settings(enabled=True),
            internal_service_authenticator=authenticator,
            runtime_run_admission_service=service,
        )
    )

    response = client.post(ROUTE, json=_body())

    assert response.status_code == 200
    assert response.json() == {"outcome": "APPLIED"}
    assert authenticator.required_scopes == [InternalServiceScope.RUNTIME_RUN_ADMIT]
    assert len(service.calls) == 1
    operation = client.get("/internal/v1/openapi.json").json()["paths"][ROUTE]["post"]
    assert operation["x-required-scopes"] == ["runtime.run.admit"]
    assert "413" in operation["responses"]

    structured = client.post(ROUTE, json=_structured_body())
    assert structured.status_code == 200
    assert service.calls[-1].admission_contract_version == "3.0"
    assert service.calls[-1].source_kind.value == "TASK_STEP"
    assert service.calls[-1].conversation_id is None

    disabled = TestClient(
        create_app(
            _settings(enabled=False),
            internal_service_authenticator=authenticator,
        )
    )
    assert disabled.post(ROUTE, json=_body()).status_code == 404
    assert ROUTE not in disabled.get("/internal/v1/openapi.json").json()["paths"]


def test_run_admission_missing_service_and_multi_scope_fail_closed() -> None:
    authenticator = RecordingAuthenticator()
    missing = TestClient(
        create_app(
            _settings(enabled=True),
            internal_service_authenticator=authenticator,
        )
    )
    assert missing.post(ROUTE, json=_body()).status_code == 503
    assert missing.get("/internal/v1/health/readiness").status_code == 503

    service = RecordingService()
    multi_scope = TestClient(
        create_app(
            _settings(enabled=True),
            internal_service_authenticator=RecordingAuthenticator(
                extra_scope=InternalServiceScope.RUNTIME_RUN_CANCEL
            ),
            runtime_run_admission_service=service,
        )
    )
    assert multi_scope.post(ROUTE, json=_body()).status_code == 403
    assert service.calls == []


def test_run_admission_rejects_ambiguous_or_mismatched_json() -> None:
    service = RecordingService()
    client = TestClient(
        create_app(
            _settings(enabled=True),
            internal_service_authenticator=RecordingAuthenticator(),
            runtime_run_admission_service=service,
        )
    )

    duplicate = client.post(
        ROUTE,
        content=(
            '{"tenantId":"%s","tenantId":"%s"}' % (_uuid(1), _uuid(1))
        ),
        headers={"Content-Type": "application/json"},
    )
    assert duplicate.status_code == 422

    unknown = _body()
    unknown["submittedBy"] = "body-must-not-control-authority"
    assert client.post(ROUTE, json=unknown).status_code == 422

    mismatched = _body()
    event = dict(mismatched["acceptedEventPayload"])  # type: ignore[arg-type]
    event["requestHash"] = "c" * 64
    mismatched["acceptedEventPayload"] = event
    assert client.post(ROUTE, json=mismatched).status_code == 422

    fake_conversation = _structured_body()
    fake_conversation["conversationId"] = str(_uuid(7))
    assert client.post(ROUTE, json=fake_conversation).status_code == 422
    assert service.calls == []


def test_run_admission_uses_a_bounded_larger_body_without_changing_other_routes() -> None:
    service = RecordingService()
    client = TestClient(
        create_app(
            _settings(enabled=True),
            internal_service_authenticator=RecordingAuthenticator(),
            runtime_run_admission_service=service,
        )
    )
    body = _body(artifact_count=120)
    compact = json.dumps(body, separators=(",", ":")).encode()
    assert 8 * 1024 < len(compact) < 32 * 1024

    assert client.post(
        ROUTE,
        content=compact,
        headers={"Content-Type": "application/json"},
    ).status_code == 200
    oversized = compact + b" " * (32 * 1024 - len(compact) + 1)
    response = client.post(
        ROUTE,
        content=oversized,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "RUNTIME_RUN_ADMISSION_REQUEST_TOO_LARGE"
    assert len(service.calls) == 1


class FakeRepository:
    def __init__(self, result: object) -> None:
        self.result = result
        self.requests: list[AdmitRuntimeRunRequest] = []

    def admit(self, request: AdmitRuntimeRunRequest):
        self.requests.append(request)
        return self.result


class ReadinessConnection:
    def execute(self, _sql: str, _parameters: object):
        return self

    def fetchone(self):
        return {
            "login_name": "dianlian_supervisor_run_admitter_login",
            "login_can_login": True,
            "login_inherits": True,
            "login_is_restricted": True,
            "has_exact_membership_count": True,
            "has_exact_run_admitter_membership": True,
            "run_admitter_role_is_sealed": True,
            "is_run_admitter": True,
            "is_executor": False,
            "is_permit_authorizer": False,
            "is_dispatch_authorizer": False,
            "is_outcome_reconciler": False,
            "is_controller": False,
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


def _fact() -> RuntimeRunFact:
    now = datetime.now(timezone.utc)
    return RuntimeRunFact(
        tenant_id=_uuid(1),
        runtime_run_id=_uuid(14),
        runtime_thread_id=_uuid(2),
        task_step_id=_uuid(4),
        task_execution_generation=15,
        status=RuntimeStatus.QUEUED,
        operation_kind=OperationKind.START,
        multitask_strategy=MultitaskStrategy.REJECT,
        request_hash=HASH,
        idempotency_key="runtime-run-admission-0001",
        predecessor_runtime_run_id=None,
        expected_checkpoint_id=None,
        current_checkpoint_id=None,
        current_checkpoint_sequence_no=None,
        next_event_sequence_no=2,
        event_retention_floor_sequence=1,
        run_version=1,
        terminal_reason=None,
        terminal_event_id=None,
        lease_owner=None,
        lease_until=None,
        lease_epoch=0,
        heartbeat_at=None,
        attempt=0,
        runtime_version="runtime-v1",
        agent_name="agent-worker",
        failure_code=None,
        cancel_requested_at=None,
        started_at=None,
        terminal_at=None,
        created_at=now,
        updated_at=now,
    )


def test_postgres_run_admission_service_builds_exact_command_and_verifies_fact() -> None:
    repository = FakeRepository(
        PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, _fact())
    )
    service = PostgresRuntimeRunAdmissionService(repository, ReadinessConnection)
    service.start()

    result = service.admit(RuntimeRunAdmissionRequest.model_validate(_body()))

    assert result == RuntimeRunAdmissionApiResult.APPLIED
    command = repository.requests[0]
    assert command.input_artifact_ids.to_builtin() == [str(_uuid(100)), str(_uuid(101))]
    assert command.accepted_event_payload.to_builtin() == _body()["acceptedEventPayload"]

    repository.result = PrimitiveResult(
        PrimitiveOutcome.FACT_RETURNED,
        replace(_fact(), runtime_thread_id=_uuid(999)),
    )
    with pytest.raises(RuntimeRunAdmissionUnavailable):
        service.admit(RuntimeRunAdmissionRequest.model_validate(_body()))
    assert service.ready is False


def test_run_admitter_settings_are_opt_in_role_bound_and_hide_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIANLIAN_RUNTIME_ROLE", "runtime-api")
    monkeypatch.setenv("DIANLIAN_RUN_ADMITTER_ENABLED", "true")
    monkeypatch.setenv(
        "DIANLIAN_RUN_ADMITTER_DATABASE_DSN",
        "postgresql://run-admitter:secret@example.invalid/runtime",
    )

    settings = RuntimeSettings.from_environment()

    assert settings.run_admitter_enabled is True
    assert "secret" not in repr(settings)
    with pytest.raises(ValueError, match="runtime-api"):
        replace(settings, role="agent-worker")

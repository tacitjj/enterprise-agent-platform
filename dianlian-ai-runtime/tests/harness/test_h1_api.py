from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from dianlian_runtime.app import create_app
from dianlian_runtime.auth import InternalServicePrincipal
from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.harness.h1_contracts import (
    H1ExecutionEvent,
    H1ExecutionSnapshot,
)


class _TrustedAuthenticator:
    ready = True

    def authorize(self, token, required_scope):
        del token
        return InternalServicePrincipal(
            subject="dianlian-platform",
            token_id=UUID("00000000-0000-4000-8000-000000000043"),
            scopes=frozenset({required_scope}),
            issued_at=0,
            expires_at=60,
        )


def _create_test_app(*args, **kwargs):
    kwargs["internal_service_authenticator"] = _TrustedAuthenticator()
    return create_app(*args, **kwargs)


class _FakeH1Runtime:
    ready = False

    def __init__(self) -> None:
        self.snapshot: H1ExecutionSnapshot | None = None

    async def __aenter__(self):
        self.ready = True
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        self.ready = False

    async def start_execution(self, request):
        now = datetime(2026, 8, 12, tzinfo=UTC)
        self.snapshot = H1ExecutionSnapshot(
            contract_version=request.contract_version,
            execution_id=request.execution_id,
            admission_snapshot_id=request.admission_snapshot_id,
            idempotency_key=request.idempotency_key,
            state="SUCCEEDED",
            output="报价摘要完成",
            failure_code=None,
            accepted_at=now,
            updated_at=now,
        )
        return self.snapshot

    async def get_execution(self, execution_id: UUID):
        if self.snapshot is None or self.snapshot.execution_id != execution_id:
            raise KeyError(execution_id)
        return self.snapshot

    async def stream_events(self, execution_id: UUID, *, after_sequence: int):
        await self.get_execution(execution_id)
        events = [
            H1ExecutionEvent(1, "dianlian.h1.started", "lifecycle", {}),
            H1ExecutionEvent(2, "dianlian.h1.model.completed", "lifecycle", {}),
        ]
        return [event for event in events if event.sequence > after_sequence]


def _payload() -> dict[str, object]:
    return {
        "contractVersion": "2.0",
        "runtimeProfile": "DEERFLOW_H1_TEXT",
        "executionId": "20000000-0000-4000-8000-000000000001",
        "taskId": "20000000-0000-4000-8000-000000000002",
        "taskStepId": "20000000-0000-4000-8000-000000000003",
        "executionGeneration": 1,
        "admissionSnapshotId": "20000000-0000-4000-8000-000000000004",
        "idempotencyKey": "h1-create-001",
        "requestHash": "1" * 64,
        "tenantId": "20000000-0000-4000-8000-000000000005",
        "actorUserId": "20000000-0000-4000-8000-000000000006",
        "inputSnapshotId": "20000000-0000-4000-8000-000000000007",
        "enterpriseAgentId": "20000000-0000-4000-8000-000000000008",
        "agentVersionId": "20000000-0000-4000-8000-000000000009",
        "configurationVersionId": "20000000-0000-4000-8000-000000000010",
        "pointReservationId": "20000000-0000-4000-8000-000000000011",
        "modelRoute": {
            "routeBindingId": "20000000-0000-4000-8000-000000000012",
            "routeStateVersion": 3,
            "modelDefinitionId": "20000000-0000-4000-8000-000000000013",
            "modelConfigurationVersion": 4,
            "reservationCeilingMicroCredit": 500,
        },
        "prompt": {
            "promptSnapshotId": "20000000-0000-4000-8000-000000000014",
            "systemInstruction": "只输出纯文本报价摘要",
            "messages": [{"role": "HUMAN", "text": "生成一份报价摘要"}],
            "hash": "2" * 64,
        },
        "context": {
            "contextSnapshotId": "20000000-0000-4000-8000-000000000015",
            "mode": "EMPTY",
            "hash": "3" * 64,
        },
        "toolPolicy": {
            "toolPolicySnapshotId": "20000000-0000-4000-8000-000000000016",
            "allowedTools": [],
            "hash": "4" * 64,
        },
        "snapshotHash": "5" * 64,
    }


def _settings(tmp_path: Path, *, enabled: bool) -> RuntimeSettings:
    return RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="runtime-api",
        context_enabled=False,
        agent_enabled=False,
        supervisor_enabled=False,
        deerflow_h1_enabled=enabled,
        deerflow_h1_data_dir=tmp_path / "data" if enabled else None,
        deerflow_source_root=tmp_path / "upstream" if enabled else None,
        runtime_model_service_base_url=(
            "https://platform.internal" if enabled else None
        ),
        runtime_model_service_jwt_key_id="kid" if enabled else None,
        runtime_model_service_jwt_private_key_path=(
            tmp_path / "private.pem" if enabled else None
        ),
    )


def _v21_payload() -> dict[str, object]:
    payload = _payload()
    payload["contractVersion"] = "2.1"
    payload["toolPolicy"] = {
        "toolPolicySnapshotId": "20000000-0000-4000-8000-000000000016",
        "schemaVersion": "runtime-tool-policy-v1",
        "mode": "ALLOW_LIST",
        "configurationPolicyId": "20000000-0000-4000-8000-000000000017",
        "configurationPolicyHash": "6" * 64,
        "allowedTools": [
            {
                "ordinal": 1,
                "toolDefinitionId": "20000000-0000-4000-8000-000000000018",
                "toolKey": "CALENDAR.READ",
                "definitionVersion": 1,
                "sideEffectMode": "NO_SIDE_EFFECT",
            }
        ],
        "hash": "d0d5114635fdd8cd424a8a28e4a5fe49d8c128aa65912712d8a6c7499b0c633f",
    }
    return payload


def _v22_payload() -> dict[str, object]:
    payload = _v21_payload()
    payload["contractVersion"] = "2.2"
    payload["orchestrationPolicy"] = {
        "orchestrationPolicySnapshotId": "20000000-0000-4000-8000-000000000019",
        "schemaVersion": "runtime-orchestration-policy-v1",
        "maxModelCalls": 2,
        "maxToolCalls": 1,
        "modelCallReservationCeiling": 500,
        "totalModelReservationCeiling": 1000,
        "hash": "1680f02fdfafed9004fcaf555bfcc0b45202c315e097017a52d8befaa33b5862",
    }
    return payload


def test_h1_v2_create_get_and_cursor_events_match_java_contract(tmp_path: Path) -> None:
    runtime = _FakeH1Runtime()
    payload = _payload()
    execution_id = payload["executionId"]

    with TestClient(
        _create_test_app(
            _settings(tmp_path, enabled=True),
            agent_h1_runtime=runtime,
        )
    ) as client:
        created = client.post("/internal/v2/agent-runtime/executions", json=payload)
        snapshot = client.get(
            f"/internal/v2/agent-runtime/executions/{execution_id}"
        )
        events = client.get(
            f"/internal/v2/agent-runtime/executions/{execution_id}/events",
            params={"afterSequence": 1},
        )

    assert created.status_code == 200
    assert created.json() == snapshot.json()
    assert created.json()["contractVersion"] == "2.0"
    assert created.json()["runtimeProfile"] == "DEERFLOW_H1_TEXT"
    assert created.json()["productionTakeoverEnabled"] is False
    assert events.status_code == 200
    assert events.json()["afterSequence"] == 1
    assert events.json()["nextSequence"] == 2
    assert events.json()["events"][0]["eventType"] == "dianlian.h1.model.completed"


def test_h1_v2_routes_are_not_registered_when_default_disabled(tmp_path: Path) -> None:
    client = TestClient(_create_test_app(_settings(tmp_path, enabled=False)))

    response = client.post("/internal/v2/agent-runtime/executions", json={})

    assert response.status_code == 404


def test_h1_v21_create_get_and_events_echo_persisted_contract_version(
    tmp_path: Path,
) -> None:
    runtime = _FakeH1Runtime()
    payload = _v21_payload()
    execution_id = payload["executionId"]

    with TestClient(
        _create_test_app(
            _settings(tmp_path, enabled=True),
            agent_h1_runtime=runtime,
        )
    ) as client:
        created = client.post("/internal/v2/agent-runtime/executions", json=payload)
        snapshot = client.get(
            f"/internal/v2/agent-runtime/executions/{execution_id}"
        )
        events = client.get(
            f"/internal/v2/agent-runtime/executions/{execution_id}/events"
        )

    assert created.status_code == 200
    assert created.json()["contractVersion"] == "2.1"
    assert snapshot.json()["contractVersion"] == "2.1"
    assert events.json()["contractVersion"] == "2.1"


def test_h1_v22_uses_the_same_routes_and_echoes_persisted_contract_version(
    tmp_path: Path,
) -> None:
    runtime = _FakeH1Runtime()
    payload = _v22_payload()
    execution_id = payload["executionId"]

    with TestClient(
        _create_test_app(
            _settings(tmp_path, enabled=True),
            agent_h1_runtime=runtime,
        )
    ) as client:
        created = client.post("/internal/v2/agent-runtime/executions", json=payload)
        snapshot = client.get(
            f"/internal/v2/agent-runtime/executions/{execution_id}"
        )
        events = client.get(
            f"/internal/v2/agent-runtime/executions/{execution_id}/events",
            params={"afterSequence": 1},
        )

    assert created.status_code == 200
    assert created.json()["contractVersion"] == "2.2"
    assert snapshot.json()["contractVersion"] == "2.2"
    assert events.json()["contractVersion"] == "2.2"
    assert events.json()["afterSequence"] == 1
    assert events.json()["nextSequence"] == 2

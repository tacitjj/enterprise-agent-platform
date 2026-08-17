from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.harness import DeerFlowH0Runtime
from dianlian_runtime.harness.contracts import (
    ExecutionEvent,
    ExecutionSnapshot,
    StartExecutionRequest,
)
from dianlian_runtime.harness.h0_runtime import (
    GuidanceOutcomeUnknown,
    GuidancePreconditionRejected,
)
from tests.internal_auth_testkit import create_test_app


class _FakeH0Runtime:
    def __init__(self) -> None:
        self.ready = False
        self.request: StartExecutionRequest | None = None
        self.snapshot: ExecutionSnapshot | None = None
        self.guidance_error: Exception | None = None

    async def __aenter__(self):
        self.ready = True
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        self.ready = False

    async def start_execution(self, request: StartExecutionRequest) -> ExecutionSnapshot:
        self.request = request
        now = datetime(2026, 8, 12, tzinfo=UTC)
        self.snapshot = ExecutionSnapshot(
            execution_id=request.execution_id,
            idempotency_key=request.idempotency_key,
            thread_id=request.thread_id,
            request_hash=request.request_hash,
            deerflow_run_id="hidden-upstream-run",
            status="WAITING_GUIDANCE",
            checkpoint_id="checkpoint-h0-1",
            result=None,
            cancel_action=None,
            accepted_at=now,
            updated_at=now,
        )
        return self.snapshot

    async def get_execution(self, execution_id: str) -> ExecutionSnapshot:
        if self.snapshot is None or self.snapshot.execution_id != execution_id:
            raise KeyError(execution_id)
        return self.snapshot

    async def guide(self, execution_id: str, **kwargs) -> ExecutionSnapshot:
        del kwargs
        if self.guidance_error is not None:
            raise self.guidance_error
        return await self.get_execution(execution_id)

    async def cancel(self, execution_id: str, **kwargs) -> ExecutionSnapshot:
        del kwargs
        return await self.get_execution(execution_id)

    async def stream_events(self, execution_id: str, **kwargs) -> list[ExecutionEvent]:
        del kwargs
        await self.get_execution(execution_id)
        return [ExecutionEvent(1, "dianlian.h0.started", "lifecycle", {})]


def _settings(tmp_path: Path, *, enabled: bool) -> RuntimeSettings:
    return RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="runtime-api",
        context_enabled=False,
        agent_enabled=False,
        supervisor_enabled=False,
        deerflow_h0_enabled=enabled,
        deerflow_source_root=tmp_path / "pinned-upstream" if enabled else None,
        deerflow_data_dir=tmp_path / "runtime-data" if enabled else None,
    )


def test_authenticated_h0_route_uses_dianlian_contract_without_upstream_dto(
    tmp_path: Path,
) -> None:
    runtime = _FakeH0Runtime()
    payload = {
        "contractVersion": "1.0",
        "executionId": "20000000-0000-4000-8000-000000000001",
        "idempotencyKey": "runtime-h0-001",
        "threadId": "10000000-0000-4000-8000-000000000001",
        "executionGeneration": 1,
        "tenantId": "30000000-0000-4000-8000-000000000001",
        "actorUserId": "40000000-0000-4000-8000-000000000001",
        "requestHash": "sha256:test-request",
    }

    with TestClient(
        create_test_app(
            _settings(tmp_path, enabled=True),
            agent_harness_runtime=runtime,
        )
    ) as client:
        created = client.post("/internal/v1/agent-runtime/executions", json=payload)
        events = client.get(
            f"/internal/v1/agent-runtime/executions/{payload['executionId']}/events"
        )

    assert created.status_code == 200
    assert created.json()["executionId"] == payload["executionId"]
    assert created.json()["productionTakeoverEnabled"] is False
    assert "deerflowRunId" not in created.json()
    assert runtime.request is not None
    assert runtime.request.request_hash == payload["requestHash"]
    assert events.status_code == 200
    assert events.json()["events"][0]["sequence"] == 1


def test_h0_routes_are_not_registered_when_disabled(tmp_path: Path) -> None:
    client = TestClient(create_test_app(_settings(tmp_path, enabled=False)))

    response = client.post("/internal/v1/agent-runtime/executions", json={})

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("runtime_error", "expected_status", "expected_code"),
    [
        (
            GuidancePreconditionRejected(
                GuidancePreconditionRejected.CHECKPOINT_STALE_CODE,
                "checkpoint changed before guidance was applied",
            ),
            409,
            "RUNTIME_GUIDANCE_CHECKPOINT_STALE",
        ),
        (
            GuidanceOutcomeUnknown("guidance invocation outcome is unknown"),
            503,
            "RUNTIME_GUIDANCE_OUTCOME_UNKNOWN",
        ),
    ],
)
def test_h0_guidance_route_preserves_safe_rejection_and_unknown_outcome(
    tmp_path: Path,
    runtime_error: Exception,
    expected_status: int,
    expected_code: str,
) -> None:
    runtime = _FakeH0Runtime()
    runtime.guidance_error = runtime_error
    execution_id = "20000000-0000-4000-8000-000000000001"

    with TestClient(
        create_test_app(
            _settings(tmp_path, enabled=True),
            agent_harness_runtime=runtime,
        )
    ) as client:
        response = client.post(
            f"/internal/v1/agent-runtime/executions/{execution_id}/guidance",
            json={
                "contractVersion": "1.0",
                "expectedCheckpointId": "checkpoint-h0-1",
                "guidance": "补充品牌约束",
            },
        )

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code


class _ExplodingGraph:
    def __init__(self) -> None:
        self.invoked = False

    async def ainvoke(self, *args, **kwargs):
        del args, kwargs
        self.invoked = True
        raise RuntimeError("graph outcome cannot be confirmed")


class _ClassifyingH0Runtime(DeerFlowH0Runtime):
    def __init__(self, *, status: str, checkpoint_id: str = "checkpoint-h0-1") -> None:
        self._lock = asyncio.Lock()
        self._graph = _ExplodingGraph()
        self._row = {
            "execution_id": "execution-h0-1",
            "status": status,
            "checkpoint_id": checkpoint_id,
            "deerflow_run_id": "run-h0-1",
            "thread_id": "thread-h0-1",
        }

    def _ensure_ready(self) -> None:
        return None

    async def _find_by_execution_id(self, execution_id: str):
        del execution_id
        return self._row


def test_h0_runtime_only_marks_pre_dispatch_conflicts_as_safe() -> None:
    async def verify() -> None:
        not_waiting = _ClassifyingH0Runtime(status="RUNNING")
        with pytest.raises(GuidancePreconditionRejected) as not_waiting_error:
            await not_waiting.guide(
                "execution-h0-1",
                expected_checkpoint_id="checkpoint-h0-1",
                guidance="补充约束",
            )
        assert not_waiting_error.value.code == GuidancePreconditionRejected.NOT_WAITING_CODE
        assert not_waiting._graph.invoked is False

        stale = _ClassifyingH0Runtime(status="WAITING_GUIDANCE")
        with pytest.raises(GuidancePreconditionRejected) as stale_error:
            await stale.guide(
                "execution-h0-1",
                expected_checkpoint_id="checkpoint-old",
                guidance="补充约束",
            )
        assert stale_error.value.code == GuidancePreconditionRejected.CHECKPOINT_STALE_CODE
        assert stale._graph.invoked is False

        dispatched = _ClassifyingH0Runtime(status="WAITING_GUIDANCE")
        with pytest.raises(GuidanceOutcomeUnknown):
            await dispatched.guide(
                "execution-h0-1",
                expected_checkpoint_id="checkpoint-h0-1",
                guidance="补充约束",
            )
        assert dispatched._graph.invoked is True

    asyncio.run(verify())

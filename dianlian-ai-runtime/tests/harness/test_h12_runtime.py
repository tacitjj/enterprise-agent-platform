from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
from uuid import UUID

import httpx
import pytest

from dianlian_runtime.harness.h1_runtime import DeerFlowH1Runtime
from dianlian_runtime.harness.h12_contracts import CreateH12ExecutionRequest
from dianlian_runtime.harness.h12_durable import (
    stable_model_call_id,
    stable_tool_call_id,
)
from dianlian_runtime.harness.h12_gateway import JavaH12GatewayClient
from dianlian_runtime.harness.model_gateway import IssuedRuntimeModelJwt


_UPSTREAM_ROOT_VALUE = os.getenv("DEERFLOW_UPSTREAM_ROOT")
UPSTREAM_ROOT = Path(_UPSTREAM_ROOT_VALUE or "deerflow-upstream-not-configured")
_UPSTREAM_SKIP_REASON = "set DEERFLOW_UPSTREAM_ROOT to the pinned DeerFlow checkout"
EXECUTION_ID = UUID("22000000-0000-4000-8000-000000000001")
SELECTION_ID = UUID("22000000-0000-4000-8000-000000000002")
POLICY_HASH_100000 = "6cf57e7fa121d4edaeb1c379df87fb5ae08e693d40c1639d3fad8ae964c9b66c"


class _UnusedLegacyModel:
    async def aclose(self) -> None:
        return None


class _RecordingIssuer:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def issue(self, *, scope: str, now=None) -> IssuedRuntimeModelJwt:
        del now
        self.scopes.append(scope)
        issued_at = datetime.now(UTC)
        return IssuedRuntimeModelJwt(
            f"token-{scope}-{len(self.scopes)}",
            issued_at,
            issued_at + timedelta(seconds=30),
        )


class _SimulatedProcessCrash(BaseException):
    pass


def _admission_payload() -> dict[str, object]:
    return {
        "contractVersion": "2.2",
        "runtimeProfile": "DEERFLOW_H1_TEXT",
        "executionId": str(EXECUTION_ID),
        "taskId": "22000000-0000-4000-8000-000000000003",
        "taskStepId": "22000000-0000-4000-8000-000000000004",
        "executionGeneration": 1,
        "admissionSnapshotId": "22000000-0000-4000-8000-000000000005",
        "idempotencyKey": "h12-create",
        "requestHash": "1" * 64,
        "tenantId": "22000000-0000-4000-8000-000000000006",
        "actorUserId": "22000000-0000-4000-8000-000000000007",
        "inputSnapshotId": "22000000-0000-4000-8000-000000000008",
        "enterpriseAgentId": "22000000-0000-4000-8000-000000000009",
        "agentVersionId": "22000000-0000-4000-8000-00000000000a",
        "configurationVersionId": "22000000-0000-4000-8000-00000000000b",
        "pointReservationId": "22000000-0000-4000-8000-00000000000c",
        "modelRoute": {
            "routeBindingId": "22000000-0000-4000-8000-00000000000d",
            "routeStateVersion": 1,
            "modelDefinitionId": "22000000-0000-4000-8000-00000000000e",
            "modelConfigurationVersion": 1,
            "reservationCeilingMicroCredit": 100000,
        },
        "prompt": {
            "promptSnapshotId": "22000000-0000-4000-8000-00000000000f",
            "systemInstruction": "Answer the user.",
            "messages": [{"role": "HUMAN", "text": "Calculate 1.2 + 2.3"}],
            "hash": "2" * 64,
        },
        "context": {
            "contextSnapshotId": "22000000-0000-4000-8000-000000000010",
            "mode": "EMPTY",
            "hash": "3" * 64,
        },
        "toolPolicy": {
            "toolPolicySnapshotId": "22000000-0000-4000-8000-000000000011",
            "schemaVersion": "runtime-tool-policy-v1",
            "mode": "ALLOW_LIST",
            "configurationPolicyId": "22000000-0000-4000-8000-000000000012",
            "configurationPolicyHash": "4" * 64,
            "allowedTools": [
                {
                    "ordinal": 1,
                    "toolDefinitionId": "ca1c0000-0000-4000-8000-000000000001",
                    "toolKey": "SYSTEM.CALCULATE",
                    "definitionVersion": 1,
                    "sideEffectMode": "NO_SIDE_EFFECT",
                }
            ],
            "hash": "34e2623c8fa2c67dd3c346a6086e741c6a685d258a3c289fa5b43b250013f3b8",
        },
        "orchestrationPolicy": {
            "orchestrationPolicySnapshotId": "22000000-0000-4000-8000-000000000013",
            "schemaVersion": "runtime-orchestration-policy-v1",
            "maxModelCalls": 2,
            "maxToolCalls": 1,
            "modelCallReservationCeiling": 100000,
            "totalModelReservationCeiling": 200000,
            "hash": POLICY_HASH_100000,
        },
        "snapshotHash": "5" * 64,
    }


def _model_response(
    model_call_id: UUID,
    *,
    status: str = "RESPONSE_RECEIVED",
    response_kind: str | None = "FINAL_TEXT",
    assistant_text: str | None = "3.5",
    model_tool_selection_id: UUID | None = None,
    failure_code: str | None = None,
    usage_confirmed: bool = True,
) -> dict[str, object]:
    return {
        "contractVersion": "1.1",
        "modelCallId": str(model_call_id),
        "status": status,
        "responseKind": response_kind,
        "modelToolSelectionId": (
            str(model_tool_selection_id) if model_tool_selection_id else None
        ),
        "assistantText": assistant_text,
        "providerRequestId": "provider-request-1" if response_kind else None,
        "providerModelName": "provider-model-1" if response_kind else None,
        "finishReason": "stop" if response_kind else None,
        "inputTokens": 2 if usage_confirmed else 0,
        "outputTokens": 1 if usage_confirmed else 0,
        "usageConfirmed": usage_confirmed,
        "capturedAmount": 3 if usage_confirmed else 100000,
        "failureCode": failure_code,
        "replayed": False,
    }


def _tool_response() -> dict[str, object]:
    return {
        "contractVersion": "1.1",
        "toolInvocationId": str(stable_tool_call_id(EXECUTION_ID)),
        "status": "SUCCEEDED",
        "output": {"value": 3.5},
        "failureCode": None,
        "replayed": False,
    }


def _runtime(
    data_dir: Path,
    gateway: JavaH12GatewayClient,
) -> DeerFlowH1Runtime:
    return DeerFlowH1Runtime(
        data_dir=data_dir,
        upstream_root=UPSTREAM_ROOT,
        model=_UnusedLegacyModel(),  # type: ignore[arg-type]
        h12_gateway=gateway,
    )


def _gateway(handler) -> tuple[JavaH12GatewayClient, httpx.AsyncClient, _RecordingIssuer]:
    issuer = _RecordingIssuer()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        JavaH12GatewayClient(
            base_url="https://platform.internal",
            jwt_issuer=issuer,  # type: ignore[arg-type]
            timeout_seconds=10,
            client=client,
        ),
        client,
        issuer,
    )


@pytest.mark.skipif(not UPSTREAM_ROOT.is_dir(), reason=_UPSTREAM_SKIP_REASON)
def test_h12_model_one_final_is_durable_idempotent_and_event_replayable(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            body = json.loads(request.content)
            assert set(body).isdisjoint({"systemInstruction", "messages", "continuation"})
            return httpx.Response(
                200,
                json=_model_response(stable_model_call_id(EXECUTION_ID, 1)),
            )

        gateway, client, issuer = _gateway(handler)
        data_dir = tmp_path / "runtime"
        admission = CreateH12ExecutionRequest.model_validate(_admission_payload())
        async with _runtime(data_dir, gateway) as runtime:
            completed = await runtime.start_execution(admission)
            replayed = await runtime.start_execution(admission)
            events = await runtime.stream_events(EXECUTION_ID, after_sequence=1)
        await client.aclose()

        assert completed.state == replayed.state == "SUCCEEDED"
        assert completed.contract_version == "2.2"
        assert completed.output == "3.5"
        assert len(requests) == 1
        assert issuer.scopes == ["model.invoke"]
        assert [event.sequence for event in events] == [2]
        assert events[0].event_type == "dianlian.h1.model.completed"
        with sqlite3.connect(data_dir / "h12-runtime.db") as database:
            assert database.execute("SELECT COUNT(*) FROM h12_model_call").fetchone() == (1,)
            assert database.execute("SELECT COUNT(*) FROM h12_tool_call").fetchone() == (0,)

    asyncio.run(verify())


@pytest.mark.skipif(not UPSTREAM_ROOT.is_dir(), reason=_UPSTREAM_SKIP_REASON)
def test_h12_model_selection_runs_exactly_one_tool_then_model_two(tmp_path: Path) -> None:
    async def verify() -> None:
        bodies: list[dict[str, object]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            bodies.append(body)
            if request.url.path.endswith("/tool-calls"):
                assert set(body).isdisjoint({"tool", "input"})
                return httpx.Response(200, json=_tool_response())
            if body["callIndex"] == 1:
                return httpx.Response(
                    200,
                    json=_model_response(
                        stable_model_call_id(EXECUTION_ID, 1),
                        response_kind="TOOL_SELECTION",
                        assistant_text=None,
                        model_tool_selection_id=SELECTION_ID,
                    ),
                )
            assert set(body).isdisjoint({"systemInstruction", "messages", "continuation"})
            return httpx.Response(
                200,
                json=_model_response(
                    stable_model_call_id(EXECUTION_ID, 2),
                    assistant_text="tool result is 3.5",
                ),
            )

        gateway, client, issuer = _gateway(handler)
        data_dir = tmp_path / "runtime"
        admission = CreateH12ExecutionRequest.model_validate(_admission_payload())
        async with _runtime(data_dir, gateway) as runtime:
            completed = await runtime.start_execution(admission)
        await client.aclose()

        assert completed.state == "SUCCEEDED"
        assert completed.output == "tool result is 3.5"
        assert [body.get("callIndex", "tool") for body in bodies] == [1, "tool", 2]
        assert issuer.scopes == ["model.invoke", "tool.invoke", "model.invoke"]
        assert bodies[0]["modelCallId"] == str(stable_model_call_id(EXECUTION_ID, 1))
        assert bodies[1]["toolInvocationId"] == str(stable_tool_call_id(EXECUTION_ID))
        assert bodies[2]["modelCallId"] == str(stable_model_call_id(EXECUTION_ID, 2))
        with sqlite3.connect(data_dir / "h12-runtime.db") as database:
            assert database.execute("SELECT COUNT(*) FROM h12_model_call").fetchone() == (2,)
            assert database.execute("SELECT COUNT(*) FROM h12_tool_call").fetchone() == (1,)

    asyncio.run(verify())


@pytest.mark.parametrize(
    ("status", "response_kind", "failure_code", "usage_confirmed", "expected_code"),
    [
        ("USAGE_PENDING", "FINAL_TEXT", None, False, "MODEL_USAGE_RECONCILIATION_REQUIRED"),
        ("RESPONSE_REJECTED", "RESPONSE_REJECTED", "MODEL_RESPONSE_REJECTED", True, "MODEL_RESPONSE_REJECTED"),
        ("FAILED_SAFE", None, "MODEL_ROUTE_SNAPSHOT_MISMATCH", False, "MODEL_ROUTE_SNAPSHOT_MISMATCH"),
        ("OUTCOME_UNKNOWN", None, "MODEL_PROVIDER_OUTCOME_UNKNOWN", False, "MODEL_PROVIDER_OUTCOME_UNKNOWN"),
    ],
)
@pytest.mark.skipif(not UPSTREAM_ROOT.is_dir(), reason=_UPSTREAM_SKIP_REASON)
def test_h12_non_continuable_model_status_never_dispatches_downstream(
    tmp_path: Path,
    status: str,
    response_kind: str | None,
    failure_code: str | None,
    usage_confirmed: bool,
    expected_code: str,
) -> None:
    async def verify() -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            del request
            calls += 1
            return httpx.Response(
                200,
                json=_model_response(
                    stable_model_call_id(EXECUTION_ID, 1),
                    status=status,
                    response_kind=response_kind,
                    assistant_text=(
                        "pending result" if status == "USAGE_PENDING" else None
                    ),
                    failure_code=failure_code,
                    usage_confirmed=usage_confirmed,
                ),
            )

        gateway, client, issuer = _gateway(handler)
        data_dir = tmp_path / status.lower()
        admission = CreateH12ExecutionRequest.model_validate(_admission_payload())
        async with _runtime(data_dir, gateway) as runtime:
            completed = await runtime.start_execution(admission)
        await client.aclose()

        assert completed.state == "FAILED"
        assert completed.failure_code == expected_code
        assert calls == 1
        assert issuer.scopes == ["model.invoke"]
        with sqlite3.connect(data_dir / "h12-runtime.db") as database:
            assert database.execute("SELECT COUNT(*) FROM h12_model_call").fetchone() == (1,)
            assert database.execute("SELECT COUNT(*) FROM h12_tool_call").fetchone() == (0,)

    asyncio.run(verify())


@pytest.mark.skipif(not UPSTREAM_ROOT.is_dir(), reason=_UPSTREAM_SKIP_REASON)
def test_h12_model_in_flight_is_unknown_and_never_creates_a_downstream_slot(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        bodies: list[dict[str, object]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(409, json={"code": "MODEL_CALL_IN_FLIGHT"})

        gateway, client, issuer = _gateway(handler)
        data_dir = tmp_path / "model-in-flight"
        admission = CreateH12ExecutionRequest.model_validate(_admission_payload())
        async with _runtime(data_dir, gateway) as runtime:
            completed = await runtime.start_execution(admission)
        await client.aclose()

        assert completed.state == "FAILED"
        assert completed.failure_code == "MODEL_CALL_IN_FLIGHT"
        assert issuer.scopes == ["model.invoke"]
        assert len(bodies) == 1
        assert bodies[0]["modelCallId"] == str(
            stable_model_call_id(EXECUTION_ID, 1)
        )
        with sqlite3.connect(data_dir / "h12-runtime.db") as database:
            row = database.execute(
                "SELECT model_call_id, java_status, response_payload "
                "FROM h12_model_call"
            ).fetchone()
            assert row[:2] == (
                str(stable_model_call_id(EXECUTION_ID, 1)),
                "OUTCOME_UNKNOWN",
            )
            assert json.loads(row[2])["failureCode"] == "MODEL_CALL_IN_FLIGHT"
            assert database.execute("SELECT COUNT(*) FROM h12_tool_call").fetchone() == (0,)

    asyncio.run(verify())


@pytest.mark.skipif(not UPSTREAM_ROOT.is_dir(), reason=_UPSTREAM_SKIP_REASON)
def test_h12_tool_in_flight_is_unknown_and_never_dispatches_model_two(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        bodies: list[dict[str, object]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            bodies.append(body)
            if request.url.path.endswith("/tool-calls"):
                return httpx.Response(
                    409,
                    json={"code": "TOOL_INVOCATION_IN_FLIGHT"},
                )
            return httpx.Response(
                200,
                json=_model_response(
                    stable_model_call_id(EXECUTION_ID, 1),
                    response_kind="TOOL_SELECTION",
                    assistant_text=None,
                    model_tool_selection_id=SELECTION_ID,
                ),
            )

        gateway, client, issuer = _gateway(handler)
        data_dir = tmp_path / "tool-in-flight"
        admission = CreateH12ExecutionRequest.model_validate(_admission_payload())
        async with _runtime(data_dir, gateway) as runtime:
            completed = await runtime.start_execution(admission)
        await client.aclose()

        assert completed.state == "FAILED"
        assert completed.failure_code == "TOOL_INVOCATION_IN_FLIGHT"
        assert issuer.scopes == ["model.invoke", "tool.invoke"]
        assert [body.get("callIndex", "tool") for body in bodies] == [1, "tool"]
        assert bodies[1]["toolInvocationId"] == str(
            stable_tool_call_id(EXECUTION_ID)
        )
        with sqlite3.connect(data_dir / "h12-runtime.db") as database:
            tool = database.execute(
                "SELECT tool_invocation_id, java_status, response_payload "
                "FROM h12_tool_call"
            ).fetchone()
            assert tool[:2] == (
                str(stable_tool_call_id(EXECUTION_ID)),
                "OUTCOME_UNKNOWN",
            )
            assert json.loads(tool[2])["failureCode"] == "TOOL_INVOCATION_IN_FLIGHT"
            assert database.execute(
                "SELECT COUNT(*) FROM h12_model_call WHERE call_index = 2"
            ).fetchone() == (0,)

    asyncio.run(verify())


@pytest.mark.skipif(not UPSTREAM_ROOT.is_dir(), reason=_UPSTREAM_SKIP_REASON)
def test_h12_restart_replays_only_the_exact_persisted_dispatching_intent(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        first_requests: list[httpx.Request] = []

        async def crashing_handler(request: httpx.Request) -> httpx.Response:
            first_requests.append(request)
            raise _SimulatedProcessCrash()

        data_dir = tmp_path / "runtime"
        admission = CreateH12ExecutionRequest.model_validate(_admission_payload())
        first_gateway, first_client, _ = _gateway(crashing_handler)
        async with _runtime(data_dir, first_gateway) as first:
            with pytest.raises(_SimulatedProcessCrash):
                await first.start_execution(admission)
        await first_client.aclose()

        replay_requests: list[httpx.Request] = []

        async def replay_handler(request: httpx.Request) -> httpx.Response:
            replay_requests.append(request)
            return httpx.Response(
                200,
                json=_model_response(stable_model_call_id(EXECUTION_ID, 1)),
            )

        replay_gateway, replay_client, issuer = _gateway(replay_handler)
        async with _runtime(data_dir, replay_gateway) as restarted:
            recovered = await restarted.get_execution(EXECUTION_ID)
            events = await restarted.stream_events(EXECUTION_ID, after_sequence=0)
        await replay_client.aclose()

        assert recovered.state == "SUCCEEDED"
        assert len(first_requests) == len(replay_requests) == 1
        assert first_requests[0].url == replay_requests[0].url
        assert first_requests[0].content == replay_requests[0].content
        assert issuer.scopes == ["model.invoke"]
        assert [event.sequence for event in events] == [1, 2]
        with sqlite3.connect(data_dir / "h12-runtime.db") as database:
            row = database.execute(
                "SELECT model_call_id, request_hash, local_state FROM h12_model_call"
            ).fetchone()
            assert row == (
                str(stable_model_call_id(EXECUTION_ID, 1)),
                json.loads(first_requests[0].content)["requestHash"],
                "TERMINAL",
            )

    asyncio.run(verify())


@pytest.mark.skipif(not UPSTREAM_ROOT.is_dir(), reason=_UPSTREAM_SKIP_REASON)
def test_h12_restart_reconciles_only_unmapped_h1_run_before_recreating_execution(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        first_requests: list[httpx.Request] = []

        async def unused_handler(request: httpx.Request) -> httpx.Response:
            first_requests.append(request)
            raise AssertionError("crash before local admission persistence cannot dispatch HTTP")

        data_dir = tmp_path / "unmapped-run"
        admission = CreateH12ExecutionRequest.model_validate(_admission_payload())
        first_gateway, first_client, _ = _gateway(unused_handler)
        async with _runtime(data_dir, first_gateway) as first:
            from deerflow.runtime.runs.schemas import RunStatus

            other_run = await first._run_manager.create_or_reject(  # noqa: SLF001
                "33000000-0000-4000-8000-000000000001",
                metadata={"runtime_profile": "OTHER_RUNTIME"},
                user_id="33000000-0000-4000-8000-000000000001",
            )
            await first._run_manager.try_start(other_run.run_id)  # noqa: SLF001
            terminal_run = await first._run_manager.create_or_reject(  # noqa: SLF001
                "33000000-0000-4000-8000-000000000002",
                metadata={"runtime_profile": "DEERFLOW_H1_TEXT"},
                user_id="33000000-0000-4000-8000-000000000002",
            )
            await first._run_manager.try_start(terminal_run.run_id)  # noqa: SLF001
            await first._run_manager.set_status(  # noqa: SLF001
                terminal_run.run_id,
                RunStatus.success,
            )
            original_put_event = first._put_event  # noqa: SLF001

            async def crash_before_local_admission_commit(*args, **kwargs):
                await original_put_event(*args, **kwargs)
                raise _SimulatedProcessCrash()

            first._put_event = crash_before_local_admission_commit  # noqa: SLF001
            with pytest.raises(_SimulatedProcessCrash):
                await first.start_execution(admission)
            orphan_runs = await first._run_store.list_by_thread(  # noqa: SLF001
                str(EXECUTION_ID),
                user_id=str(EXECUTION_ID),
            )
            orphan_run_id = orphan_runs[0]["run_id"]
        await first_client.aclose()

        replay_requests: list[httpx.Request] = []

        async def replay_handler(request: httpx.Request) -> httpx.Response:
            replay_requests.append(request)
            return httpx.Response(
                200,
                json=_model_response(stable_model_call_id(EXECUTION_ID, 1)),
            )

        replay_gateway, replay_client, issuer = _gateway(replay_handler)
        async with _runtime(data_dir, replay_gateway) as restarted:
            reconciled = await restarted._run_store.get(  # noqa: SLF001
                orphan_run_id,
                user_id=str(EXECUTION_ID),
            )
            untouched_other = await restarted._run_store.get(  # noqa: SLF001
                other_run.run_id,
                user_id="33000000-0000-4000-8000-000000000001",
            )
            untouched_terminal = await restarted._run_store.get(  # noqa: SLF001
                terminal_run.run_id,
                user_id="33000000-0000-4000-8000-000000000002",
            )
            completed = await restarted.start_execution(admission)
            events = await restarted.stream_events(EXECUTION_ID)
        await replay_client.aclose()

        assert first_requests == []
        assert len(replay_requests) == 1
        assert issuer.scopes == ["model.invoke"]
        assert reconciled["status"] == "error"
        assert reconciled["error"] == "H1_ADMISSION_PERSISTENCE_INTERRUPTED"
        assert untouched_other["status"] == "running"
        assert untouched_terminal["status"] == "success"
        assert completed.state == "SUCCEEDED"
        assert [event.sequence for event in events] == [2, 3]
        assert [event.event_type for event in events] == [
            "dianlian.h1.started",
            "dianlian.h1.model.completed",
        ]

    asyncio.run(verify())

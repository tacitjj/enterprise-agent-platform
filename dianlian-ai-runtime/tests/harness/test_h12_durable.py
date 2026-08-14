from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from dianlian_runtime.harness.h12_contracts import (
    CreateH12ExecutionRequest,
    FrozenOrchestrationPolicySnapshot,
)

from dianlian_runtime.harness.h12_durable import (
    H12CausalFenceRejected,
    H12DurableSlots,
    H12IntentConflict,
    ModelOutcome,
    ModelPhase,
    RecoveryAction,
    canonical_intent,
    stable_model_call_id,
    stable_tool_call_id,
)


EXECUTION_ID = UUID("22000000-0000-4000-8000-000000000001")
SELECTION_ID = UUID("22000000-0000-4000-8000-000000000002")
POLICY_HASH_100000 = "6cf57e7fa121d4edaeb1c379df87fb5ae08e693d40c1639d3fad8ae964c9b66c"


def _intent(kind: str, index: int) -> dict[str, object]:
    return {
        "contractVersion": "1.1",
        "executionId": str(EXECUTION_ID),
        "kind": kind,
        "index": index,
    }


def _h12_admission_payload() -> dict[str, object]:
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


def test_h12_uses_stable_three_slot_ids_and_canonical_hashes() -> None:
    assert str(stable_model_call_id(EXECUTION_ID, 1)) == (
        "098aa8f7-d949-5f2f-ab85-e7b30265b759"
    )
    assert str(stable_tool_call_id(EXECUTION_ID)) == (
        "c65dafff-c002-52bd-a135-63d2edc900c6"
    )
    assert str(stable_model_call_id(EXECUTION_ID, 2)) == (
        "8d45e294-a9a5-5229-af18-8354a74173c3"
    )
    first, first_hash = canonical_intent({"b": 2, "a": 1})
    second, second_hash = canonical_intent({"a": 1, "b": 2})
    assert first == second == '{"a":1,"b":2}'
    assert first_hash == second_hash


def test_h12_admission_requires_exact_frozen_orchestration_and_tool_policy() -> None:
    request = CreateH12ExecutionRequest.model_validate(_h12_admission_payload())
    assert request.orchestration_policy.hash == POLICY_HASH_100000
    assert request.tool_policy.allowed_tools[0].tool_key == "SYSTEM.CALCULATE"

    wrong_hash = _h12_admission_payload()
    wrong_hash["orchestrationPolicy"] = {
        **wrong_hash["orchestrationPolicy"],  # type: ignore[arg-type]
        "hash": "0" * 64,
    }
    with pytest.raises(ValidationError, match="orchestration policy hash"):
        CreateH12ExecutionRequest.model_validate(wrong_hash)

    deny_all = _h12_admission_payload()
    deny_all["toolPolicy"] = {
        **deny_all["toolPolicy"],  # type: ignore[arg-type]
        "mode": "DENY_ALL",
        "allowedTools": [],
    }
    with pytest.raises(ValidationError):
        CreateH12ExecutionRequest.model_validate(deny_all)


def test_h12_durable_happy_path_survives_restart(tmp_path: Path) -> None:
    async def verify() -> None:
        database = tmp_path / "h12.db"
        async with H12DurableSlots(database) as slots:
            call_one = await slots.prepare_model(
                EXECUTION_ID,
                1,
                ModelPhase.TOOL_DECISION,
                _intent("model", 1),
            )
            assert call_one.intent_id == stable_model_call_id(EXECUTION_ID, 1)
            await slots.mark_model_dispatching(EXECUTION_ID, 1)
            assert (await slots.next_action(EXECUTION_ID)).action == RecoveryAction.REPLAY_MODEL_1
            await slots.complete_model(
                EXECUTION_ID,
                1,
                java_status="RESPONSE_RECEIVED",
                outcome=ModelOutcome.TOOL_SELECTION,
                model_tool_selection_id=SELECTION_ID,
                response_payload={"outcome": {"type": "TOOL_SELECTION"}},
            )
            with pytest.raises(H12IntentConflict):
                await slots.complete_model(
                    EXECUTION_ID,
                    1,
                    java_status="RESPONSE_RECEIVED",
                    outcome=ModelOutcome.FINAL_TEXT,
                    response_payload={"outcome": {"type": "TOOL_SELECTION"}},
                )
            assert (await slots.next_action(EXECUTION_ID)).action == RecoveryAction.DISPATCH_TOOL_1
            await slots.prepare_tool(
                EXECUTION_ID,
                source_model_call_id=call_one.intent_id,
                model_tool_selection_id=SELECTION_ID,
                request_without_hash=_intent("tool", 1),
            )
            await slots.mark_tool_dispatching(EXECUTION_ID)
            await slots.complete_tool(
                EXECUTION_ID,
                java_status="SUCCEEDED",
                response_payload={"status": "SUCCEEDED"},
            )

        async with H12DurableSlots(database) as recovered:
            assert (await recovered.next_action(EXECUTION_ID)).action == RecoveryAction.DISPATCH_MODEL_2
            await recovered.prepare_model(
                EXECUTION_ID,
                2,
                ModelPhase.FINAL_AFTER_TOOL,
                _intent("model", 2),
            )
            await recovered.mark_model_dispatching(EXECUTION_ID, 2)
            await recovered.complete_model(
                EXECUTION_ID,
                2,
                java_status="RESPONSE_RECEIVED",
                outcome=ModelOutcome.FINAL_TEXT,
                response_payload={"outcome": {"type": "FINAL_TEXT"}},
            )
            decision = await recovered.next_action(EXECUTION_ID)
            assert decision.action == RecoveryAction.COMPLETE_FINAL
            assert decision.intent is not None
            assert decision.intent.intent_id == stable_model_call_id(EXECUTION_ID, 2)

    asyncio.run(verify())


def test_h12_final_text_and_unknown_results_block_downstream_slots(tmp_path: Path) -> None:
    async def verify() -> None:
        async with H12DurableSlots(tmp_path / "final.db") as slots:
            await slots.prepare_model(
                EXECUTION_ID,
                1,
                ModelPhase.TOOL_DECISION,
                _intent("model", 1),
            )
            await slots.mark_model_dispatching(EXECUTION_ID, 1)
            await slots.complete_model(
                EXECUTION_ID,
                1,
                java_status="RESPONSE_RECEIVED",
                outcome=ModelOutcome.FINAL_TEXT,
                response_payload={"outcome": {"type": "FINAL_TEXT"}},
            )
            assert (await slots.next_action(EXECUTION_ID)).action == RecoveryAction.COMPLETE_FINAL
            with pytest.raises(H12CausalFenceRejected):
                await slots.prepare_tool(
                    EXECUTION_ID,
                    source_model_call_id=stable_model_call_id(EXECUTION_ID, 1),
                    model_tool_selection_id=SELECTION_ID,
                    request_without_hash=_intent("tool", 1),
                )

        other = UUID("22000000-0000-4000-8000-000000000099")
        async with H12DurableSlots(tmp_path / "unknown.db") as slots:
            await slots.prepare_model(other, 1, ModelPhase.TOOL_DECISION, _intent("model", 1))
            await slots.mark_model_dispatching(other, 1)
            await slots.complete_model(
                other,
                1,
                java_status="OUTCOME_UNKNOWN",
                outcome=None,
                response_payload={"status": "OUTCOME_UNKNOWN"},
            )
            decision = await slots.next_action(other)
            assert decision.action == RecoveryAction.FAIL_TERMINAL
            assert decision.failure_code == "OUTCOME_UNKNOWN"

    asyncio.run(verify())


def test_h12_usage_pending_preserves_response_but_cannot_continue(tmp_path: Path) -> None:
    async def verify() -> None:
        async with H12DurableSlots(tmp_path / "usage-pending.db") as slots:
            call = await slots.prepare_model(
                EXECUTION_ID,
                1,
                ModelPhase.TOOL_DECISION,
                _intent("model", 1),
            )
            await slots.mark_model_dispatching(EXECUTION_ID, 1)
            await slots.complete_model(
                EXECUTION_ID,
                1,
                java_status="USAGE_PENDING",
                outcome=ModelOutcome.TOOL_SELECTION,
                model_tool_selection_id=SELECTION_ID,
                response_payload={"status": "USAGE_PENDING"},
            )
            decision = await slots.next_action(EXECUTION_ID)
            assert decision.action == RecoveryAction.FAIL_TERMINAL
            assert decision.failure_code == "USAGE_PENDING"
            with pytest.raises(H12CausalFenceRejected):
                await slots.prepare_tool(
                    EXECUTION_ID,
                    source_model_call_id=call.intent_id,
                    model_tool_selection_id=SELECTION_ID,
                    request_without_hash=_intent("tool", 1),
                )

    asyncio.run(verify())


def test_h12_reuses_only_the_exact_persisted_intent(tmp_path: Path) -> None:
    async def verify() -> None:
        async with H12DurableSlots(tmp_path / "conflict.db") as slots:
            original = await slots.prepare_model(
                EXECUTION_ID,
                1,
                ModelPhase.TOOL_DECISION,
                _intent("model", 1),
            )
            replay = await slots.prepare_model(
                EXECUTION_ID,
                1,
                ModelPhase.TOOL_DECISION,
                _intent("model", 1),
            )
            assert replay == original
            with pytest.raises(H12IntentConflict):
                await slots.prepare_model(
                    EXECUTION_ID,
                    1,
                    ModelPhase.TOOL_DECISION,
                    {**_intent("model", 1), "changed": True},
                )

    asyncio.run(verify())


def test_h12_rejects_secret_shaped_persisted_payloads(tmp_path: Path) -> None:
    async def verify() -> None:
        async with H12DurableSlots(tmp_path / "secret.db") as slots:
            for forbidden in ("apiKey", "Authorization", "password", "bearer"):
                with pytest.raises(ValueError, match="forbidden key"):
                    await slots.prepare_model(
                        EXECUTION_ID,
                        1,
                        ModelPhase.TOOL_DECISION,
                        {**_intent("model", 1), forbidden: "never-persist"},
                    )

    asyncio.run(verify())

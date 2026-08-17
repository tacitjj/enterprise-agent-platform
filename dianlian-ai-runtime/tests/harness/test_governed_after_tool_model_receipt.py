from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from dianlian_runtime.harness.governed_model_gateway import (
    GovernedInitialModelCallResponse,
    GovernedInitialModelGatewayClient,
)
from dianlian_runtime.harness.governed_model_intent import (
    GovernedAfterToolModelIntent,
)
from dianlian_runtime.harness.governed_model_receipt import (
    GovernedAfterToolModelRequestReceipt,
)
from dianlian_runtime.harness.h12_durable import (
    H12CausalFenceRejected,
    H12DurableSlots,
    ModelOutcome,
    ModelPhase,
    canonical_intent,
    stable_model_call_id,
)
from dianlian_runtime.harness.model_gateway import IssuedRuntimeModelJwt
from dianlian_runtime.supervisor.contracts import ExternalOperation
from dianlian_runtime.supervisor.driver import DriverFence
from dianlian_runtime.supervisor.model_permit_issuer import ModelPermitReceipt


EXECUTION_ID = UUID("e1000000-0000-4000-8000-000000000001")
ADMISSION_ID = UUID("e1000000-0000-4000-8000-000000000002")


def test_after_tool_receipt_keeps_authority_out_of_the_logical_hash() -> None:
    intent = _intent()
    first = GovernedAfterToolModelRequestReceipt.create(
        EXECUTION_ID,
        intent,
        _permit(intent, lease_epoch=3),
    )
    takeover = GovernedAfterToolModelRequestReceipt.create(
        EXECUTION_ID,
        intent,
        _permit(intent, lease_epoch=4),
    )
    payload = json.loads(first.exact_body)

    assert first.request.call_index == 2
    assert first.request.call_phase == "AFTER_TOOL"
    assert first.request.model_call_id == stable_model_call_id(EXECUTION_ID, 2)
    assert first.request.request_hash == takeover.request.request_hash
    assert first.exact_body != takeover.exact_body
    assert "runtimeExternalPermitId" not in first.request.logical_payload()
    assert set(payload["dispatchArm"]) == {
        "tenantId",
        "runtimeExternalPermitId",
        "leaseOwner",
        "leaseEpoch",
        "admissionSnapshotHash",
        "armEventId",
    }
    assert GovernedAfterToolModelRequestReceipt.restore(
        EXECUTION_ID,
        first.exact_body,
        first.body_sha256,
    ) == first


def test_h12_persists_and_binds_only_the_exact_after_tool_receipt(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        intent = _intent()
        receipt = GovernedAfterToolModelRequestReceipt.create(
            EXECUTION_ID,
            intent,
            _permit(intent, lease_epoch=3),
        )
        database = tmp_path / "governed-after-tool.db"
        async with H12DurableSlots(database) as slots:
            await _prepare_after_tool_slot(slots, intent)
            assert (
                await slots.persist_governed_after_tool_model_receipt(receipt)
                == receipt
            )
            await slots.begin_governed_after_tool_model_dispatch(
                receipt,
                _fence(receipt),
            )
            await slots.require_governed_after_tool_model_dispatch_binding(
                receipt
            )
            with pytest.raises(
                H12CausalFenceRejected,
                match="exact dispatch receipt",
            ):
                await slots.mark_model_dispatching(EXECUTION_ID, 2)
            response = GovernedInitialModelCallResponse.model_validate_json(
                json.dumps(_applied_response(receipt)),
                strict=True,
            )
            await slots.complete_governed_after_tool_model(
                EXECUTION_ID,
                _fence(receipt),
                response,
            )
            await slots.complete_governed_after_tool_model(
                EXECUTION_ID,
                _fence(receipt),
                response,
            )
            terminal = await slots.load_governed_after_tool_terminal_evidence(
                EXECUTION_ID
            )
            assert terminal is not None
            assert terminal.outcome_status == "SUCCEEDED"
            assert terminal.response_payload["assistantText"] == "final answer"

        async with H12DurableSlots(database) as recovered:
            assert (
                await recovered.load_governed_after_tool_model_receipt(
                    receipt.runtime_external_permit_id
                )
                == receipt
            )
            assert await recovered.load_governed_after_tool_model_receipt_history(
                EXECUTION_ID
            ) == (receipt,)
            await recovered.require_governed_after_tool_model_dispatch_binding(
                receipt
            )
            terminal = await recovered.load_governed_after_tool_terminal_evidence(
                EXECUTION_ID
            )
            assert terminal is not None
            assert terminal.java_status == "RESPONSE_RECEIVED"

    asyncio.run(verify())


def test_gateway_posts_the_exact_after_tool_receipt_to_the_dedicated_path() -> None:
    async def verify() -> None:
        intent = _intent()
        receipt = GovernedAfterToolModelRequestReceipt.create(
            EXECUTION_ID,
            intent,
            _permit(intent, lease_epoch=3),
        )
        requests: list[httpx.Request] = []
        issuer = _RecordingIssuer()

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json=_applied_response(receipt))

        client = GovernedInitialModelGatewayClient(
            base_url="https://java.internal",
            jwt_issuer=issuer,
            timeout_seconds=5,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        response = await client.invoke_after_tool(receipt)

        assert response.disposition == "CANONICAL_OUTCOME_APPLIED"
        assert response.terminal_result is not None
        assert response.terminal_result.assistant_text == "final answer"
        assert issuer.scopes == ["model.invoke.governed"]
        assert len(requests) == 1
        assert requests[0].content == receipt.exact_body
        assert requests[0].url.path.endswith(
            f"/{EXECUTION_ID}/governed-model-calls/after-tool"
        )

    asyncio.run(verify())


def _intent() -> GovernedAfterToolModelIntent:
    return GovernedAfterToolModelIntent.model_validate(
        {
            "contractVersion": "1.2",
            "modelCallId": stable_model_call_id(EXECUTION_ID, 2),
            "callIndex": 2,
            "callPhase": "AFTER_TOOL",
            "executionGeneration": 3,
            "idempotencyKey": f"h12:{EXECUTION_ID}:model:2",
            "admissionSnapshotId": ADMISSION_ID,
            "promptSnapshotId": UUID("e1000000-0000-4000-8000-000000000003"),
            "contextSnapshotId": UUID("e1000000-0000-4000-8000-000000000004"),
            "toolPolicySnapshotId": UUID("e1000000-0000-4000-8000-000000000005"),
            "orchestrationPolicySnapshotId": UUID(
                "e1000000-0000-4000-8000-000000000006"
            ),
            "modelRouteBindingId": UUID("e1000000-0000-4000-8000-000000000007"),
            "modelRouteStateVersion": 5,
            "modelDefinitionId": UUID("e1000000-0000-4000-8000-000000000008"),
            "modelConfigurationVersion": 7,
        },
        strict=True,
    )


def _permit(
    intent: GovernedAfterToolModelIntent,
    *,
    lease_epoch: int,
) -> ModelPermitReceipt:
    issued_at = datetime(2026, 8, 14, tzinfo=UTC)
    _, request_hash = canonical_intent(intent.durable_payload())
    return ModelPermitReceipt(
        tenant_id=UUID("e1000000-0000-4000-8000-000000000009"),
        runtime_external_permit_id=UUID(
            f"e1000000-0000-4000-8000-{100 + lease_epoch:012d}"
        ),
        runtime_run_id=EXECUTION_ID,
        task_execution_generation=3,
        lease_owner=f"worker-{lease_epoch}",
        lease_epoch=lease_epoch,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash="a" * 64,
        operation_kind=ExternalOperation.MODEL_INVOKE,
        intent_id=intent.model_call_id,
        request_hash=request_hash,
        issue_event_id=UUID(
            f"e1000000-0000-4000-8000-{200 + lease_epoch:012d}"
        ),
        arm_event_id=UUID(
            f"e1000000-0000-4000-8000-{300 + lease_epoch:012d}"
        ),
        permit_attempt=lease_epoch,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=30),
    )


def _fence(receipt: GovernedAfterToolModelRequestReceipt) -> DriverFence:
    request = receipt.request
    arm = request.dispatch_arm
    return DriverFence(
        tenant_id=arm.tenant_id,
        runtime_run_id=receipt.execution_id,
        task_execution_generation=request.execution_generation,
        lease_owner=arm.lease_owner,
        lease_epoch=arm.lease_epoch,
        admission_contract_version="2.2",
        admission_snapshot_id=request.admission_snapshot_id,
        admission_snapshot_hash=arm.admission_snapshot_hash,
    )


async def _prepare_after_tool_slot(
    slots: H12DurableSlots,
    intent: GovernedAfterToolModelIntent,
) -> None:
    selection_id = UUID("e1000000-0000-4000-8000-000000000020")
    call_one = await slots.prepare_model(
        EXECUTION_ID,
        1,
        ModelPhase.TOOL_DECISION,
        {"kind": "tool-decision"},
    )
    await slots.mark_model_dispatching(EXECUTION_ID, 1)
    await slots.complete_model(
        EXECUTION_ID,
        1,
        java_status="RESPONSE_RECEIVED",
        outcome=ModelOutcome.TOOL_SELECTION,
        model_tool_selection_id=selection_id,
        response_payload={"outcome": {"type": "TOOL_SELECTION"}},
    )
    await slots.prepare_tool(
        EXECUTION_ID,
        source_model_call_id=call_one.intent_id,
        model_tool_selection_id=selection_id,
        request_without_hash={"kind": "tool-call"},
    )
    await slots.mark_tool_dispatching(EXECUTION_ID)
    await slots.complete_tool(
        EXECUTION_ID,
        java_status="SUCCEEDED",
        response_payload={"status": "SUCCEEDED"},
    )
    await slots.prepare_model(
        EXECUTION_ID,
        2,
        ModelPhase.FINAL_AFTER_TOOL,
        intent.durable_payload(),
    )


class _RecordingIssuer:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def issue(self, *, scope: str, now: datetime | None = None) -> IssuedRuntimeModelJwt:
        del now
        self.scopes.append(scope)
        issued_at = datetime(2026, 8, 14, tzinfo=UTC)
        return IssuedRuntimeModelJwt(
            "governed-model-token",
            issued_at,
            issued_at + timedelta(seconds=30),
        )


def _applied_response(
    receipt: GovernedAfterToolModelRequestReceipt,
) -> dict[str, object]:
    arm = receipt.request.dispatch_arm
    dispatch = {
        "runtimeExternalPermitId": str(arm.runtime_external_permit_id),
        "leaseOwner": arm.lease_owner,
        "leaseEpoch": arm.lease_epoch,
        "armEventId": str(arm.arm_event_id),
    }
    return {
        "contractVersion": "1.2",
        "modelCallId": str(receipt.request.model_call_id),
        "requestHash": receipt.request.request_hash,
        "disposition": "CANONICAL_OUTCOME_APPLIED",
        "modelCallStatus": "RESPONSE_RECEIVED",
        "failureCode": None,
        "action": "NONE",
        "providerRetryAllowed": False,
        "persistedDispatch": dispatch,
        "attemptedDispatch": dispatch,
        "canonicalFact": {
            "outcomeEventId": "e1000000-0000-4000-8000-000000000030",
            "outcomeStatus": "SUCCEEDED",
            "sourceFactId": "e1000000-0000-4000-8000-000000000031",
            "sourceFactVersion": 1,
            "sourceFactHash": "b" * 64,
            "outcomeCode": "MODEL_RESPONSE_RECEIVED",
            "resultHash": "c" * 64,
        },
        "terminalResult": {
            "status": "RESPONSE_RECEIVED",
            "responseKind": "FINAL_TEXT",
            "assistantText": "final answer",
            "providerRequestId": "provider-request-2",
            "providerModelName": "model-a",
            "finishReason": "stop",
            "inputTokens": 2,
            "outputTokens": 3,
            "usageConfirmed": True,
            "capturedAmount": 0,
            "failureCode": None,
        },
    }

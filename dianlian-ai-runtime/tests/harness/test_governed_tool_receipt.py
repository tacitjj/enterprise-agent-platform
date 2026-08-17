from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
from uuid import UUID

import pytest

from dianlian_runtime.harness.governed_tool_gateway import (
    GovernedToolCallResponse,
)
from dianlian_runtime.harness.governed_tool_receipt import (
    GovernedToolIntent,
    GovernedToolRequestReceipt,
)
from dianlian_runtime.harness.h12_durable import (
    H12CausalFenceRejected,
    H12DurableSlots,
    H12IntentConflict,
    ModelOutcome,
    ModelPhase,
    canonical_intent,
    stable_model_call_id,
    stable_tool_call_id,
)
from dianlian_runtime.supervisor.contracts import ExternalOperation
from dianlian_runtime.supervisor.driver import DriverFence
from dianlian_runtime.supervisor.tool_permit_issuer import ToolPermitReceipt


EXECUTION_ID = UUID("c1000000-0000-4000-8000-000000000001")
TENANT_ID = UUID("c1000000-0000-4000-8000-000000000002")
ADMISSION_ID = UUID("c1000000-0000-4000-8000-000000000003")
TOOL_POLICY_ID = UUID("c1000000-0000-4000-8000-000000000004")
SELECTION_ID = UUID("c1000000-0000-4000-8000-000000000005")


def _intent() -> GovernedToolIntent:
    return GovernedToolIntent.model_validate(
        {
            "contractVersion": "1.2",
            "selectionMode": "MODEL_SELECTED",
            "toolInvocationId": stable_tool_call_id(EXECUTION_ID),
            "sourceModelCallId": stable_model_call_id(EXECUTION_ID, 1),
            "executionGeneration": 3,
            "admissionSnapshotId": ADMISSION_ID,
            "toolPolicySnapshotId": TOOL_POLICY_ID,
            "modelToolSelectionId": SELECTION_ID,
            "toolCallSlot": 1,
            "idempotencyKey": f"h12:{EXECUTION_ID}:tool:1",
        },
        strict=True,
    )


def _permit(*, lease_epoch: int) -> ToolPermitReceipt:
    issued_at = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
    _, request_hash = canonical_intent(_intent().durable_payload())
    return ToolPermitReceipt(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=UUID(
            f"c1000000-0000-4000-8000-{100 + lease_epoch:012d}"
        ),
        runtime_run_id=EXECUTION_ID,
        task_execution_generation=3,
        lease_owner=f"worker-{lease_epoch}",
        lease_epoch=lease_epoch,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash="a" * 64,
        operation_kind=ExternalOperation.TOOL_INVOKE,
        intent_id=stable_tool_call_id(EXECUTION_ID),
        request_hash=request_hash,
        issue_event_id=UUID(
            f"c1000000-0000-4000-8000-{200 + lease_epoch:012d}"
        ),
        arm_event_id=UUID(
            f"c1000000-0000-4000-8000-{300 + lease_epoch:012d}"
        ),
        permit_attempt=lease_epoch,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=30),
    )


def _receipt(lease_epoch: int) -> GovernedToolRequestReceipt:
    return GovernedToolRequestReceipt.create(
        EXECUTION_ID,
        _intent(),
        _permit(lease_epoch=lease_epoch),
    )


def _fence(receipt: GovernedToolRequestReceipt) -> DriverFence:
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


async def _prepare_tool_slot(slots: H12DurableSlots) -> None:
    model = await slots.prepare_model(
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
        model_tool_selection_id=SELECTION_ID,
        response_payload={"outcome": {"type": "TOOL_SELECTION"}},
    )
    await slots.prepare_tool(
        EXECUTION_ID,
        source_model_call_id=model.intent_id,
        model_tool_selection_id=SELECTION_ID,
        request_without_hash=_intent().durable_payload(),
    )


def test_exact_tool_receipt_separates_logical_hash_from_dispatch_envelope() -> None:
    first = GovernedToolRequestReceipt.create(EXECUTION_ID, _intent(), _permit(lease_epoch=3))
    takeover = GovernedToolRequestReceipt.create(
        EXECUTION_ID,
        _intent(),
        _permit(lease_epoch=4),
    )

    assert first.request.request_hash == takeover.request.request_hash
    assert first.exact_body != takeover.exact_body
    assert first.runtime_external_permit_id != takeover.runtime_external_permit_id
    assert first.request.logical_payload() == _intent().durable_payload()


def test_tool_receipt_restores_the_exact_canonical_body() -> None:
    receipt = GovernedToolRequestReceipt.create(
        EXECUTION_ID,
        _intent(),
        _permit(lease_epoch=3),
    )

    assert GovernedToolRequestReceipt.restore(
        EXECUTION_ID,
        receipt.exact_body,
        receipt.body_sha256,
    ) == receipt
    assert receipt.body_sha256 == hashlib.sha256(receipt.exact_body).hexdigest()


def test_tool_receipt_rejects_a_mismatched_permit() -> None:
    mismatched = _permit(lease_epoch=3)
    mismatched = replace(
        mismatched,
        intent_id=UUID("c1000000-0000-4000-8000-000000000099"),
    )

    with pytest.raises(ValueError, match="do not match"):
        GovernedToolRequestReceipt.create(EXECUTION_ID, _intent(), mismatched)


def test_tool_receipt_restore_rejects_duplicate_json_keys() -> None:
    receipt = GovernedToolRequestReceipt.create(
        EXECUTION_ID,
        _intent(),
        _permit(lease_epoch=3),
    )
    duplicate = receipt.exact_body[:-1] + b',"requestHash":"' + b"a" * 64 + b'"}'

    with pytest.raises(ValueError, match="duplicate key"):
        GovernedToolRequestReceipt.restore(
            EXECUTION_ID,
            duplicate,
            hashlib.sha256(duplicate).hexdigest(),
        )


def test_h12_persists_and_binds_only_the_exact_governed_tool_receipt(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        database = tmp_path / "governed-tool.db"
        receipt = _receipt(3)
        async with H12DurableSlots(database) as slots:
            await _prepare_tool_slot(slots)
            assert await slots.persist_governed_tool_receipt(receipt) == receipt
            assert (
                await slots.load_governed_tool_receipt(
                    receipt.runtime_external_permit_id
                )
                == receipt
            )
            assert await slots.load_governed_tool_receipt_history(
                EXECUTION_ID
            ) == (receipt,)

            with pytest.raises(H12CausalFenceRejected, match="governed runtime Driver"):
                await slots.next_action(EXECUTION_ID)
            with pytest.raises(H12CausalFenceRejected, match="exact dispatch receipt"):
                await slots.mark_tool_dispatching(EXECUTION_ID)

            await slots.begin_governed_tool_dispatch(receipt, _fence(receipt))
            await slots.require_governed_tool_dispatch_binding(receipt)
            with pytest.raises(H12CausalFenceRejected, match="governed runtime Driver"):
                await slots.next_action(EXECUTION_ID)
            with pytest.raises(
                H12CausalFenceRejected,
                match="canonical terminal evidence",
            ):
                await slots.complete_tool(
                    EXECUTION_ID,
                    java_status="SUCCEEDED",
                    response_payload={"status": "SUCCEEDED"},
                )

        async with H12DurableSlots(database) as recovered:
            assert (
                await recovered.load_governed_tool_receipt(
                    receipt.runtime_external_permit_id
                )
                == receipt
            )
            assert await recovered.load_governed_tool_receipt_history(
                EXECUTION_ID
            ) == (receipt,)
            await recovered.require_governed_tool_dispatch_binding(receipt)

    asyncio.run(verify())


def test_h12_keeps_explicit_governed_tool_receipt_history_across_takeover(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        first = _receipt(3)
        takeover = _receipt(4)
        async with H12DurableSlots(tmp_path / "governed-tool-history.db") as slots:
            await _prepare_tool_slot(slots)
            await slots.persist_governed_tool_receipt(first)
            await slots.begin_governed_tool_dispatch(first, _fence(first))
            await slots.persist_governed_tool_receipt(takeover)

            assert await slots.load_governed_tool_receipt_history(
                EXECUTION_ID
            ) == (first, takeover)
            await slots.begin_governed_tool_dispatch(takeover, _fence(takeover))
            await slots.require_governed_tool_dispatch_binding(first)
            await slots.require_governed_tool_dispatch_binding(takeover)

            collision_permit = replace(
                _permit(lease_epoch=4),
                runtime_external_permit_id=UUID(
                    "c1000000-0000-4000-8000-000000000998"
                ),
                arm_event_id=UUID(
                    "c1000000-0000-4000-8000-000000000999"
                ),
            )
            collision = GovernedToolRequestReceipt.create(
                EXECUTION_ID,
                _intent(),
                collision_permit,
            )
            with pytest.raises(H12IntentConflict, match="advance the lease epoch"):
                await slots.persist_governed_tool_receipt(collision)

    asyncio.run(verify())


def test_h12_releases_after_tool_only_from_applied_governed_tool_evidence(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        receipt = _receipt(3)
        async with H12DurableSlots(tmp_path / "governed-tool-terminal.db") as slots:
            await _prepare_tool_slot(slots)
            await slots.persist_governed_tool_receipt(receipt)
            await slots.begin_governed_tool_dispatch(receipt, _fence(receipt))
            response = _tool_response(receipt, pending=False)

            await slots.complete_governed_tool(
                EXECUTION_ID,
                _fence(receipt),
                response,
            )
            await slots.complete_governed_tool(
                EXECUTION_ID,
                _fence(receipt),
                response,
            )

            evidence = await slots.load_governed_tool_terminal_evidence(
                EXECUTION_ID
            )
            assert evidence is not None
            assert evidence.outcome_status == "SUCCEEDED"
            assert evidence.tool_invocation_id == receipt.request.tool_invocation_id
            assert evidence.response_payload == {
                "contractVersion": "1.2",
                "disposition": "CANONICAL_OUTCOME_APPLIED",
                "outcomeCode": "TOOL_SUCCEEDED",
                "outcomeStatus": "SUCCEEDED",
            }
            call_two = await slots.prepare_model(
                EXECUTION_ID,
                2,
                ModelPhase.FINAL_AFTER_TOOL,
                {"kind": "final-after-tool"},
            )
            assert call_two.intent_id == stable_model_call_id(EXECUTION_ID, 2)

    asyncio.run(verify())


def test_h12_keeps_pending_governed_tool_outcome_non_terminal(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        receipt = _receipt(3)
        async with H12DurableSlots(tmp_path / "governed-tool-pending.db") as slots:
            await _prepare_tool_slot(slots)
            await slots.persist_governed_tool_receipt(receipt)
            await slots.begin_governed_tool_dispatch(receipt, _fence(receipt))

            with pytest.raises(H12CausalFenceRejected, match="not a releasable"):
                await slots.complete_governed_tool(
                    EXECUTION_ID,
                    _fence(receipt),
                    _tool_response(receipt, pending=True),
                )
            assert await slots.load_governed_tool_terminal_evidence(
                EXECUTION_ID
            ) is None
            with pytest.raises(H12CausalFenceRejected, match="terminal successful"):
                await slots.prepare_model(
                    EXECUTION_ID,
                    2,
                    ModelPhase.FINAL_AFTER_TOOL,
                    {"kind": "final-after-tool"},
                )

    asyncio.run(verify())


def _tool_response(
    receipt: GovernedToolRequestReceipt,
    *,
    pending: bool,
) -> GovernedToolCallResponse:
    arm = receipt.request.dispatch_arm
    dispatch = {
        "runtimeExternalPermitId": arm.runtime_external_permit_id,
        "leaseOwner": arm.lease_owner,
        "leaseEpoch": arm.lease_epoch,
        "armEventId": arm.arm_event_id,
    }
    return GovernedToolCallResponse.model_validate(
        {
            "contractVersion": "1.2",
            "toolInvocationId": receipt.request.tool_invocation_id,
            "requestHash": receipt.request.request_hash,
            "disposition": (
                "CANONICAL_OUTCOME_PENDING"
                if pending
                else "CANONICAL_OUTCOME_APPLIED"
            ),
            "action": "REDELIVER_SAME_CANONICAL_FACT" if pending else "NONE",
            "providerRetryAllowed": False,
            "persistedDispatch": dispatch,
            "attemptedDispatch": dispatch,
            "canonicalFact": {
                "outcomeEventId": UUID(
                    "c1000000-0000-4000-8000-000000000040"
                ),
                "outcomeStatus": "SUCCEEDED",
                "sourceFactId": UUID(
                    "c1000000-0000-4000-8000-000000000041"
                ),
                "sourceFactVersion": 1,
                "sourceFactHash": "b" * 64,
                "outcomeCode": "TOOL_SUCCEEDED",
                "resultHash": "c" * 64,
            },
        },
        strict=True,
    )

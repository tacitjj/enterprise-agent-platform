from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from dianlian_runtime.harness.governed_model_gateway import (
    GovernedInitialModelCallResponse,
)
from dianlian_runtime.harness.governed_model_intent import (
    GovernedInitialModelIntent,
)
from dianlian_runtime.harness.governed_model_receipt import (
    GovernedInitialModelRequestReceipt,
)
from dianlian_runtime.harness.h12_durable import (
    H12CausalFenceRejected,
    H12DurableSlots,
    H12IntentConflict,
    LocalIntentState,
    ModelOutcome,
    ModelPhase,
    canonical_intent,
    stable_model_call_id,
    stable_model_tool_selection_id,
)
from dianlian_runtime.supervisor.contracts import ExternalOperation
from dianlian_runtime.supervisor.driver import DriverFence
from dianlian_runtime.supervisor.model_permit_issuer import ModelPermitReceipt


EXECUTION_ID = UUID("52000000-0000-4000-8000-000000000001")
TENANT_ID = UUID("52000000-0000-4000-8000-000000000002")
ADMISSION_ID = UUID("52000000-0000-4000-8000-000000000003")
HASH = "a" * 64


def _intent() -> GovernedInitialModelIntent:
    return GovernedInitialModelIntent.model_validate(
        {
            "contractVersion": "1.2",
            "modelCallId": stable_model_call_id(EXECUTION_ID, 1),
            "callIndex": 1,
            "callPhase": "INITIAL",
            "executionGeneration": 3,
            "idempotencyKey": f"h12:{EXECUTION_ID}:model:1",
            "admissionSnapshotId": ADMISSION_ID,
            "promptSnapshotId": UUID(
                "52000000-0000-4000-8000-000000000004"
            ),
            "contextSnapshotId": UUID(
                "52000000-0000-4000-8000-000000000005"
            ),
            "toolPolicySnapshotId": UUID(
                "52000000-0000-4000-8000-000000000006"
            ),
            "orchestrationPolicySnapshotId": UUID(
                "52000000-0000-4000-8000-000000000007"
            ),
            "modelRouteBindingId": UUID(
                "52000000-0000-4000-8000-000000000008"
            ),
            "modelRouteStateVersion": 5,
            "modelDefinitionId": UUID(
                "52000000-0000-4000-8000-000000000009"
            ),
            "modelConfigurationVersion": 7,
        },
        strict=True,
    )


def _permit(
    *,
    lease_epoch: int,
    permit_id: UUID,
    arm_event_id: UUID,
    request_hash: str | None = None,
) -> ModelPermitReceipt:
    issued_at = datetime(2026, 8, 13, 8, 0, tzinfo=UTC)
    _, logical_hash = canonical_intent(_intent().durable_payload())
    return ModelPermitReceipt(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=permit_id,
        runtime_run_id=EXECUTION_ID,
        task_execution_generation=3,
        lease_owner=f"worker-{lease_epoch}",
        lease_epoch=lease_epoch,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=HASH,
        operation_kind=ExternalOperation.MODEL_INVOKE,
        intent_id=stable_model_call_id(EXECUTION_ID, 1),
        request_hash=request_hash or logical_hash,
        issue_event_id=UUID(
            f"52000000-0000-4000-8000-{100 + lease_epoch:012d}"
        ),
        arm_event_id=arm_event_id,
        permit_attempt=lease_epoch,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=30),
    )


def _receipt(
    lease_epoch: int,
    *,
    permit_id: UUID | None = None,
    arm_event_id: UUID | None = None,
) -> GovernedInitialModelRequestReceipt:
    return GovernedInitialModelRequestReceipt.create(
        EXECUTION_ID,
        _intent(),
        _permit(
            lease_epoch=lease_epoch,
            permit_id=permit_id
            or UUID(f"52000000-0000-4000-8000-{200 + lease_epoch:012d}"),
            arm_event_id=arm_event_id
            or UUID(f"52000000-0000-4000-8000-{300 + lease_epoch:012d}"),
        ),
    )


def _fence(receipt: GovernedInitialModelRequestReceipt) -> DriverFence:
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


def _dispatch(receipt: GovernedInitialModelRequestReceipt) -> dict[str, object]:
    arm = receipt.request.dispatch_arm
    return {
        "runtimeExternalPermitId": arm.runtime_external_permit_id,
        "leaseOwner": arm.lease_owner,
        "leaseEpoch": arm.lease_epoch,
        "armEventId": arm.arm_event_id,
    }


def _applied_final_response(
    attempted: GovernedInitialModelRequestReceipt,
    *,
    persisted: GovernedInitialModelRequestReceipt | None = None,
) -> GovernedInitialModelCallResponse:
    winner = persisted or attempted
    return GovernedInitialModelCallResponse.model_validate(
        {
            "contractVersion": "1.2",
            "modelCallId": attempted.request.model_call_id,
            "requestHash": attempted.request.request_hash,
            "disposition": "CANONICAL_OUTCOME_APPLIED",
            "modelCallStatus": "RESPONSE_RECEIVED",
            "failureCode": None,
            "action": "NONE",
            "providerRetryAllowed": False,
            "persistedDispatch": _dispatch(winner),
            "attemptedDispatch": _dispatch(attempted),
            "canonicalFact": {
                "outcomeEventId": UUID(
                    "52000000-0000-4000-8000-000000000401"
                ),
                "outcomeStatus": "SUCCEEDED",
                "sourceFactId": UUID(
                    "52000000-0000-4000-8000-000000000402"
                ),
                "sourceFactVersion": 1,
                "sourceFactHash": "b" * 64,
                "outcomeCode": "MODEL_RESPONSE_RECEIVED",
                "resultHash": "c" * 64,
            },
            "terminalResult": {
                "status": "RESPONSE_RECEIVED",
                "responseKind": "FINAL_TEXT",
                "assistantText": "answer",
                "providerRequestId": "provider-request-1",
                "providerModelName": "model-a",
                "finishReason": "stop",
                "inputTokens": 2,
                "outputTokens": 3,
                "usageConfirmed": True,
                "capturedAmount": 0,
                "failureCode": None,
            },
        },
        strict=True,
    )


def _pending_response(
    receipt: GovernedInitialModelRequestReceipt,
) -> GovernedInitialModelCallResponse:
    return GovernedInitialModelCallResponse.model_validate(
        {
            "contractVersion": "1.2",
            "modelCallId": receipt.request.model_call_id,
            "requestHash": receipt.request.request_hash,
            "disposition": "CANONICAL_OUTCOME_PENDING",
            "modelCallStatus": "RESPONSE_RECEIVED",
            "failureCode": None,
            "action": "REDELIVER_SAME_CANONICAL_FACT",
            "providerRetryAllowed": False,
            "persistedDispatch": _dispatch(receipt),
            "attemptedDispatch": _dispatch(receipt),
            "canonicalFact": {
                "outcomeEventId": UUID(
                    "52000000-0000-4000-8000-000000000411"
                ),
                "outcomeStatus": "SUCCEEDED",
                "sourceFactId": UUID(
                    "52000000-0000-4000-8000-000000000412"
                ),
                "sourceFactVersion": 1,
                "sourceFactHash": "d" * 64,
                "outcomeCode": "MODEL_RESPONSE_RECEIVED",
                "resultHash": "e" * 64,
            },
            "terminalResult": None,
        },
        strict=True,
    )


def _unknown_applied_response(
    receipt: GovernedInitialModelRequestReceipt,
) -> GovernedInitialModelCallResponse:
    payload = _pending_response(receipt).model_dump(mode="python", by_alias=True)
    payload["disposition"] = "CANONICAL_OUTCOME_APPLIED"
    payload["modelCallStatus"] = "OUTCOME_UNKNOWN"
    payload["action"] = "MANUAL_RECONCILIATION_REQUIRED"
    canonical = payload["canonicalFact"]
    assert isinstance(canonical, dict)
    canonical["outcomeStatus"] = "OUTCOME_UNKNOWN"
    canonical["outcomeCode"] = "MODEL_PROVIDER_OUTCOME_UNKNOWN"
    canonical["resultHash"] = None
    return GovernedInitialModelCallResponse.model_validate(payload, strict=True)


async def _prepare_logical_slot(slots: H12DurableSlots) -> None:
    await slots.prepare_model(
        EXECUTION_ID,
        1,
        ModelPhase.TOOL_DECISION,
        _intent().durable_payload(),
    )


def test_applied_governed_tool_selection_releases_only_a_stable_reference(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        receipt = _receipt(1)
        async with H12DurableSlots(tmp_path / "governed-selection.db") as slots:
            await _prepare_logical_slot(slots)
            await slots.persist_governed_initial_model_receipt(receipt)
            await slots.begin_governed_initial_model_dispatch(receipt, _fence(receipt))
            await slots.complete_governed_initial_model(
                EXECUTION_ID,
                _fence(receipt),
                _tool_required_response(receipt),
            )

            evidence = await slots.load_governed_initial_terminal_evidence(
                EXECUTION_ID
            )
            selection_id = stable_model_tool_selection_id(
                receipt.request.model_call_id
            )
            assert evidence is not None
            assert evidence.outcome_kind == ModelOutcome.TOOL_SELECTION
            assert evidence.model_tool_selection_id == selection_id
            assert set(evidence.response_payload) == {
                "contractVersion",
                "disposition",
                "modelToolSelectionId",
                "outcomeStatus",
            }
            tool = await slots.prepare_tool(
                EXECUTION_ID,
                source_model_call_id=receipt.request.model_call_id,
                model_tool_selection_id=selection_id,
                request_without_hash={"kind": "governed-tool"},
            )
            assert tool.intent_id is not None

    asyncio.run(verify())


def _tool_required_response(
    receipt: GovernedInitialModelRequestReceipt,
) -> GovernedInitialModelCallResponse:
    dispatch = _dispatch(receipt)
    return GovernedInitialModelCallResponse.model_validate(
        {
            "contractVersion": "1.2",
            "modelCallId": receipt.request.model_call_id,
            "requestHash": receipt.request.request_hash,
            "disposition": "GOVERNED_TOOL_REQUIRED",
            "modelCallStatus": "RESPONSE_RECEIVED",
            "failureCode": None,
            "action": "WAIT_FOR_GOVERNED_TOOL_CHAIN",
            "providerRetryAllowed": False,
            "persistedDispatch": dispatch,
            "attemptedDispatch": dispatch,
            "canonicalFact": {
                "outcomeEventId": UUID(
                    "52000000-0000-4000-8000-000000000421"
                ),
                "outcomeStatus": "SUCCEEDED",
                "sourceFactId": UUID(
                    "52000000-0000-4000-8000-000000000422"
                ),
                "sourceFactVersion": 1,
                "sourceFactHash": "f" * 64,
                "outcomeCode": "MODEL_TOOL_SELECTION_RECORDED",
                "resultHash": "1" * 64,
            },
            "terminalResult": None,
        },
        strict=True,
    )


def test_exact_receipt_shape_keeps_permit_out_of_logical_hash() -> None:
    first = _receipt(1)
    takeover = _receipt(2)
    first_payload = json.loads(first.exact_body)
    takeover_payload = json.loads(takeover.exact_body)
    _, expected_hash = canonical_intent(_intent().durable_payload())

    assert set(first_payload) == {
        *set(_intent().durable_payload()),
        "requestHash",
        "dispatchArm",
    }
    assert len(_intent().durable_payload()) == 15
    assert first.execution_id == EXECUTION_ID
    assert "executionId" not in first_payload
    assert "runtimeRunId" not in first_payload
    assert set(first_payload["dispatchArm"]) == {
        "tenantId",
        "runtimeExternalPermitId",
        "leaseOwner",
        "leaseEpoch",
        "admissionSnapshotHash",
        "armEventId",
    }
    assert first_payload["requestHash"] == expected_hash
    assert takeover_payload["requestHash"] == expected_hash
    assert first.exact_body != takeover.exact_body
    assert first.body_sha256 == hashlib.sha256(first.exact_body).hexdigest()
    assert all(
        forbidden not in first.exact_body.decode("utf-8").lower()
        for forbidden in (
            "authorization",
            "jwt",
            "issueeventid",
            "permitattempt",
            "issuedat",
            "expiresat",
            "secret",
            "token",
        )
    )


def test_receipt_requires_exact_path_intent_and_permit_binding() -> None:
    wrong_hash = _permit(
        lease_epoch=1,
        permit_id=UUID("52000000-0000-4000-8000-000000000201"),
        arm_event_id=UUID("52000000-0000-4000-8000-000000000301"),
        request_hash="b" * 64,
    )
    with pytest.raises(ValueError, match="do not match"):
        GovernedInitialModelRequestReceipt.create(
            EXECUTION_ID,
            _intent(),
            wrong_hash,
        )

    with pytest.raises(ValueError, match="path execution id"):
        GovernedInitialModelRequestReceipt.create(
            UUID("52000000-0000-4000-8000-000000000099"),
            _intent(),
            _permit(
                lease_epoch=1,
                permit_id=UUID("52000000-0000-4000-8000-000000000201"),
                arm_event_id=UUID(
                    "52000000-0000-4000-8000-000000000301"
                ),
            ),
        )


def test_exact_receipt_survives_restart_and_is_idempotent(tmp_path: Path) -> None:
    async def verify() -> None:
        database = tmp_path / "governed-receipt.db"
        receipt = _receipt(1)
        async with H12DurableSlots(database) as slots:
            await _prepare_logical_slot(slots)
            assert (
                await slots.persist_governed_initial_model_receipt(receipt)
            ) == receipt

        async with H12DurableSlots(database) as recovered:
            exact = await recovered.load_governed_initial_model_receipt(
                receipt.runtime_external_permit_id
            )
            assert exact == receipt
            assert exact is not None
            assert exact.exact_body == receipt.exact_body
            assert (
                await recovered.persist_governed_initial_model_receipt(receipt)
            ) == receipt
            assert await recovered.load_governed_initial_model_receipt_history(
                EXECUTION_ID
            ) == (receipt,)

    asyncio.run(verify())


def test_takeover_appends_history_but_never_selects_latest(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        first = _receipt(1)
        takeover = _receipt(2)
        third = _receipt(3)
        async with H12DurableSlots(tmp_path / "takeover.db") as slots:
            await _prepare_logical_slot(slots)
            await slots.persist_governed_initial_model_receipt(first)
            assert await slots.load_governed_initial_model_receipt(
                first.runtime_external_permit_id
            ) == first

            await slots.begin_governed_initial_model_dispatch(first, _fence(first))
            await slots.begin_governed_initial_model_dispatch(first, _fence(first))
            with pytest.raises(H12CausalFenceRejected, match="exact dispatch"):
                await slots.mark_model_dispatching(EXECUTION_ID, 1)
            assert await slots.load_governed_initial_model_receipt(
                first.runtime_external_permit_id
            ) == first
            await slots.persist_governed_initial_model_receipt(takeover)
            await slots.begin_governed_initial_model_dispatch(
                takeover,
                _fence(takeover),
            )
            assert await slots.load_governed_initial_model_receipt_history(
                EXECUTION_ID
            ) == (first, takeover)

            with pytest.raises(H12CausalFenceRejected, match="canonical terminal"):
                await slots.complete_model(
                    EXECUTION_ID,
                    1,
                    java_status="FAILED_SAFE",
                    outcome=None,
                    response_payload={"failureCode": "UNTRUSTED_LEGACY_PATH"},
                )
            # The current worker may settle an older Java canonical winner; the
            # historical receipt proves result identity while the new fence proves
            # authority to mutate the local slot.
            response = _applied_final_response(first, persisted=first)
            await slots.complete_governed_initial_model(
                EXECUTION_ID,
                _fence(takeover),
                response,
            )
            await slots.complete_governed_initial_model(
                EXECUTION_ID,
                _fence(takeover),
                response,
            )
            terminal = await slots.require_model_intent(EXECUTION_ID, 1)
            assert terminal.local_state == LocalIntentState.TERMINAL
            assert terminal.java_status == "RESPONSE_RECEIVED"
            assert terminal.response_payload is not None
            assert terminal.response_payload["assistantText"] == "answer"
            assert await slots.load_governed_initial_model_receipt(
                first.runtime_external_permit_id
            ) == first
            assert await slots.load_governed_initial_model_receipt(
                takeover.runtime_external_permit_id
            ) == takeover
            with pytest.raises(H12CausalFenceRejected, match="terminal"):
                await slots.persist_governed_initial_model_receipt(third)

    asyncio.run(verify())


def test_pending_response_never_releases_the_governed_slot(tmp_path: Path) -> None:
    async def verify() -> None:
        receipt = _receipt(1)
        async with H12DurableSlots(tmp_path / "pending.db") as slots:
            await _prepare_logical_slot(slots)
            await slots.persist_governed_initial_model_receipt(receipt)
            await slots.begin_governed_initial_model_dispatch(receipt, _fence(receipt))

            for response in (
                _pending_response(receipt),
                _unknown_applied_response(receipt),
            ):
                with pytest.raises(H12CausalFenceRejected):
                    await slots.complete_governed_initial_model(
                        EXECUTION_ID,
                        _fence(receipt),
                        response,
                    )
            intent = await slots.require_model_intent(EXECUTION_ID, 1)
            assert intent.local_state == LocalIntentState.DISPATCHING
            assert intent.java_status is None

    asyncio.run(verify())


def test_store_rejects_first_dispatching_receipt_and_identity_collisions(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        first = _receipt(1)
        async with H12DurableSlots(tmp_path / "first-dispatching.db") as slots:
            await _prepare_logical_slot(slots)
            await slots.mark_model_dispatching(EXECUTION_ID, 1)
            with pytest.raises(H12CausalFenceRejected, match="first governed"):
                await slots.persist_governed_initial_model_receipt(first)

        async with H12DurableSlots(tmp_path / "collisions.db") as slots:
            await _prepare_logical_slot(slots)
            await slots.persist_governed_initial_model_receipt(first)
            same_permit_changed_arm = _receipt(
                2,
                permit_id=first.runtime_external_permit_id,
            )
            with pytest.raises(H12IntentConflict, match="another exact"):
                await slots.persist_governed_initial_model_receipt(
                    same_permit_changed_arm
                )
            same_epoch_new_permit = _receipt(
                1,
                permit_id=UUID(
                    "52000000-0000-4000-8000-000000000299"
                ),
                arm_event_id=UUID(
                    "52000000-0000-4000-8000-000000000399"
                ),
            )
            with pytest.raises(H12IntentConflict, match="lease epoch"):
                await slots.persist_governed_initial_model_receipt(
                    same_epoch_new_permit
                )

    asyncio.run(verify())

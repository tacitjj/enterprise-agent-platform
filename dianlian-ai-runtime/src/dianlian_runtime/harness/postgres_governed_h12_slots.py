from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from typing import Any, Literal
from uuid import UUID

from dianlian_runtime.harness.governed_model_gateway import (
    GovernedInitialModelCallResponse,
)
from dianlian_runtime.harness.governed_model_intent import GovernedInitialModelIntent
from dianlian_runtime.harness.governed_model_receipt import (
    GovernedAfterToolModelRequestReceipt,
    GovernedInitialModelRequestReceipt,
)
from dianlian_runtime.harness.governed_tool_gateway import GovernedToolCallResponse
from dianlian_runtime.harness.governed_tool_receipt import GovernedToolRequestReceipt
from dianlian_runtime.harness.h12_durable import (
    DurableIntent,
    GovernedAfterToolTerminalEvidence,
    GovernedInitialTerminalEvidence,
    GovernedToolTerminalEvidence,
    H12CausalFenceRejected,
    H12IntentConflict,
    LocalIntentState,
    ModelOutcome,
    ModelPhase,
    _after_tool_fence_matches_receipt,
    _after_tool_response_identity_matches_receipt,
    _current_fence_can_settle_after_tool_receipt,
    _current_fence_can_settle_receipt,
    _current_fence_can_settle_tool_receipt,
    _fence_matches_receipt,
    _governed_terminal_completion,
    _governed_tool_terminal_completion,
    _response_identity_matches_receipt,
    _tool_fence_matches_receipt,
    _tool_response_identity_matches_receipt,
    _validate_governed_terminal_evidence,
    _validate_governed_tool_terminal_evidence,
    canonical_intent,
    stable_model_call_id,
    stable_tool_call_id,
)
from dianlian_runtime.supervisor.contracts import FrozenJsonObject
from dianlian_runtime.supervisor.driver import DriverFence
from dianlian_runtime.supervisor.h12_checkpoint_store import (
    PostgresH12CheckpointStore,
    RuntimeH12CheckpointFact,
    RuntimeH12SlotsState,
)


_MODEL_SLOT_KEYS = {
    "schemaVersion",
    "callIndex",
    "intent",
    "receipts",
    "dispatchBindings",
    "terminalResponse",
}
_TOOL_SLOT_KEYS = {
    "schemaVersion",
    "intent",
    "receipts",
    "dispatchBindings",
    "terminalResponse",
}
_MODEL_INTENT_KEYS = {
    "executionId",
    "intentId",
    "requestHash",
    "canonicalRequest",
    "localState",
    "javaStatus",
    "outcomeKind",
    "modelToolSelectionId",
    "responsePayload",
}
_TOOL_INTENT_KEYS = {
    "executionId",
    "intentId",
    "sourceModelCallId",
    "modelToolSelectionId",
    "requestHash",
    "canonicalRequest",
    "localState",
    "javaStatus",
    "responsePayload",
}
_RECEIPT_KEYS = {
    "executionId",
    "runtimeExternalPermitId",
    "armEventId",
    "leaseEpoch",
    "bodySha256",
    "exactBody",
}

SlotName = Literal["initial_model", "tool", "after_tool_model"]
ReceiptKind = Literal["initial", "tool", "after_tool"]


class PostgresGovernedH12SlotsFactory:
    """Create one current-fenced PostgreSQL H12 slot session per Driver call."""

    def __init__(self, store: PostgresH12CheckpointStore) -> None:
        if not isinstance(store, PostgresH12CheckpointStore):
            raise TypeError("store must be a PostgresH12CheckpointStore")
        self._store = store
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    async def start(self) -> None:
        if self._ready:
            raise RuntimeError("PostgreSQL governed H12 slots are already started")
        await self._store.verify_capability()
        self._ready = True

    async def close(self) -> None:
        self._ready = False

    def __call__(self, fence: DriverFence) -> "PostgresGovernedH12Slots":
        if not self._ready:
            raise RuntimeError("PostgreSQL governed H12 slots are not ready")
        return PostgresGovernedH12Slots(self._store, fence)


class PostgresGovernedH12Slots:
    """Governed H12 journal persisted as immutable whole-document CAS checkpoints."""

    def __init__(self, store: PostgresH12CheckpointStore, fence: DriverFence) -> None:
        if not isinstance(store, PostgresH12CheckpointStore):
            raise TypeError("store must be a PostgresH12CheckpointStore")
        if not isinstance(fence, DriverFence):
            raise TypeError("fence must be a DriverFence")
        self._store = store
        self._fence = fence
        self._fact: RuntimeH12CheckpointFact | None = None
        self._state = RuntimeH12SlotsState()
        self._entered = False
        self._write_lock = asyncio.Lock()

    async def __aenter__(self) -> "PostgresGovernedH12Slots":
        if self._entered:
            raise RuntimeError("PostgreSQL governed H12 slots cannot be re-entered")
        self._fact = await self._store.load(self._fence)
        if self._fact is not None:
            self._state = RuntimeH12SlotsState.from_fact(self._fact)
            _validate_state(self._state)
        self._entered = True
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self._entered = False

    async def load_governed_initial_model_intent(
        self,
        execution_id: UUID,
    ) -> GovernedInitialModelIntent | None:
        self._require_execution(execution_id)
        document = self._slot_document("initial_model")
        if document is None:
            return None
        durable = _model_intent(document, expected_call_index=1)
        try:
            intent = GovernedInitialModelIntent.model_validate_json(
                durable.canonical_request,
                strict=True,
            )
        except (TypeError, ValueError) as exception:
            raise H12IntentConflict(
                "initial model checkpoint does not contain a governed logical intent"
            ) from exception
        _, expected_hash = canonical_intent(intent.durable_payload())
        if (
            intent.model_call_id != durable.intent_id
            or expected_hash != durable.request_hash
        ):
            raise H12IntentConflict(
                "governed logical intent differs from checkpoint identity"
            )
        return intent

    async def prepare_model(
        self,
        execution_id: UUID,
        call_index: int,
        phase: ModelPhase,
        request_without_hash: dict[str, Any],
    ) -> DurableIntent:
        self._require_execution(execution_id)
        expected_phase = (
            ModelPhase.TOOL_DECISION
            if call_index == 1
            else ModelPhase.FINAL_AFTER_TOOL
        )
        if call_index not in {1, 2} or phase != expected_phase:
            raise ValueError("H1 2.2 model phase does not match call index")
        canonical, request_hash = canonical_intent(request_without_hash)
        intent_id = stable_model_call_id(execution_id, call_index)
        slot_name: SlotName = "initial_model" if call_index == 1 else "after_tool_model"
        async with self._write_lock:
            existing = self._slot_document(slot_name)
            if existing is not None:
                durable = _model_intent(existing, expected_call_index=call_index)
                if (
                    durable.intent_id != intent_id
                    or durable.request_hash != request_hash
                    or durable.canonical_request != canonical
                ):
                    raise H12IntentConflict("model checkpoint is bound to another intent")
                return durable
            if call_index == 2:
                tool_evidence = _tool_evidence(self._slot_document("tool"))
                if tool_evidence is None or tool_evidence.outcome_status != "SUCCEEDED":
                    raise H12CausalFenceRejected(
                        "AFTER_TOOL model requires exact successful Tool evidence"
                    )
            document = _new_model_slot(
                execution_id,
                call_index,
                intent_id,
                request_hash,
                canonical,
            )
            await self._save_slot(
                slot_name,
                document,
                f"MODEL_{call_index}_PREPARED",
            )
            return _model_intent(document, expected_call_index=call_index)

    async def load_governed_initial_terminal_evidence(
        self,
        execution_id: UUID,
    ) -> GovernedInitialTerminalEvidence | None:
        self._require_execution(execution_id)
        return _model_evidence(
            self._slot_document("initial_model"),
            expected_call_index=1,
        )

    async def persist_governed_initial_model_receipt(
        self,
        receipt: GovernedInitialModelRequestReceipt,
    ) -> GovernedInitialModelRequestReceipt:
        if not isinstance(receipt, GovernedInitialModelRequestReceipt):
            raise TypeError("receipt must be a GovernedInitialModelRequestReceipt")
        return await self._persist_model_receipt("initial_model", "initial", receipt, 1)

    async def begin_governed_initial_model_dispatch(
        self,
        receipt: GovernedInitialModelRequestReceipt,
        fence: DriverFence,
    ) -> None:
        if not isinstance(receipt, GovernedInitialModelRequestReceipt):
            raise TypeError("receipt must be a GovernedInitialModelRequestReceipt")
        if not _fence_matches_receipt(fence, receipt):
            raise H12CausalFenceRejected(
                "current Driver fence does not match the governed request receipt"
            )
        await self._begin_dispatch("initial_model", "initial", receipt, 1)

    async def require_governed_initial_model_dispatch_binding(
        self,
        receipt: GovernedInitialModelRequestReceipt,
    ) -> None:
        self._require_binding("initial_model", "initial", receipt)

    async def complete_governed_initial_model(
        self,
        execution_id: UUID,
        fence: DriverFence,
        response: GovernedInitialModelCallResponse,
    ) -> None:
        self._require_execution(execution_id)
        if not isinstance(response, GovernedInitialModelCallResponse):
            raise TypeError("response must be a GovernedInitialModelCallResponse")
        if response.model_call_id != stable_model_call_id(execution_id, 1):
            raise H12IntentConflict("governed response modelCallId differs from the slot")
        await self._complete_model("initial_model", "initial", response, fence, 1)

    async def prepare_tool(
        self,
        execution_id: UUID,
        *,
        source_model_call_id: UUID,
        model_tool_selection_id: UUID,
        request_without_hash: dict[str, Any],
    ) -> DurableIntent:
        self._require_execution(execution_id)
        canonical, request_hash = canonical_intent(request_without_hash)
        intent_id = stable_tool_call_id(execution_id)
        initial = _model_evidence(
            self._slot_document("initial_model"),
            expected_call_index=1,
        )
        if (
            initial is None
            or initial.java_status != "RESPONSE_RECEIVED"
            or initial.outcome_kind != ModelOutcome.TOOL_SELECTION
            or initial.model_call_id != source_model_call_id
            or initial.model_tool_selection_id != model_tool_selection_id
        ):
            raise H12CausalFenceRejected(
                "Tool checkpoint requires exact terminal model selection evidence"
            )
        async with self._write_lock:
            existing = self._slot_document("tool")
            if existing is not None:
                durable = _tool_intent(existing)
                intent = _required_object(existing["intent"], "Tool intent")
                if (
                    durable.intent_id != intent_id
                    or durable.request_hash != request_hash
                    or durable.canonical_request != canonical
                    or UUID(str(intent["sourceModelCallId"])) != source_model_call_id
                    or UUID(str(intent["modelToolSelectionId"]))
                    != model_tool_selection_id
                ):
                    raise H12IntentConflict("Tool checkpoint is bound to another intent")
                return durable
            document = _new_tool_slot(
                execution_id,
                intent_id,
                source_model_call_id,
                model_tool_selection_id,
                request_hash,
                canonical,
            )
            await self._save_slot("tool", document, "TOOL_1_PREPARED")
            return _tool_intent(document)

    async def load_governed_tool_terminal_evidence(
        self,
        execution_id: UUID,
    ) -> GovernedToolTerminalEvidence | None:
        self._require_execution(execution_id)
        return _tool_evidence(self._slot_document("tool"))

    async def persist_governed_tool_receipt(
        self,
        receipt: GovernedToolRequestReceipt,
    ) -> GovernedToolRequestReceipt:
        if not isinstance(receipt, GovernedToolRequestReceipt):
            raise TypeError("receipt must be a GovernedToolRequestReceipt")
        async with self._write_lock:
            document = self._required_slot("tool")
            durable = _tool_intent(document)
            request = receipt.request
            canonical, request_hash = canonical_intent(request.logical_payload())
            intent = _required_object(document["intent"], "Tool intent")
            if (
                durable.intent_id != request.tool_invocation_id
                or durable.request_hash != request.request_hash
                or durable.request_hash != request_hash
                or durable.canonical_request != canonical
                or UUID(str(intent["sourceModelCallId"]))
                != request.source_model_call_id
                or UUID(str(intent["modelToolSelectionId"]))
                != request.model_tool_selection_id
            ):
                raise H12IntentConflict(
                    "governed Tool receipt differs from the durable logical intent"
                )
            stored = self._append_receipt(document, "tool", receipt)
            if stored is not None:
                return stored
            await self._save_slot("tool", document, "TOOL_1_RECEIPT_APPENDED")
            return receipt

    async def begin_governed_tool_dispatch(
        self,
        receipt: GovernedToolRequestReceipt,
        fence: DriverFence,
    ) -> None:
        if not isinstance(receipt, GovernedToolRequestReceipt):
            raise TypeError("receipt must be a GovernedToolRequestReceipt")
        if not _tool_fence_matches_receipt(fence, receipt):
            raise H12CausalFenceRejected(
                "current Driver fence does not match the governed Tool receipt"
            )
        await self._begin_dispatch("tool", "tool", receipt, 1)

    async def require_governed_tool_dispatch_binding(
        self,
        receipt: GovernedToolRequestReceipt,
    ) -> None:
        self._require_binding("tool", "tool", receipt)

    async def complete_governed_tool(
        self,
        execution_id: UUID,
        fence: DriverFence,
        response: GovernedToolCallResponse,
    ) -> None:
        self._require_execution(execution_id)
        if not isinstance(response, GovernedToolCallResponse):
            raise TypeError("response must be a GovernedToolCallResponse")
        if response.tool_invocation_id != stable_tool_call_id(execution_id):
            raise H12IntentConflict("governed Tool response differs from the slot")
        completion = _governed_tool_terminal_completion(response)
        async with self._write_lock:
            document = self._required_slot("tool")
            attempted, persisted = self._terminal_receipts(
                document,
                "tool",
                response.attempted_dispatch.runtime_external_permit_id,
                response.persisted_dispatch.runtime_external_permit_id,
            )
            if (
                not _tool_response_identity_matches_receipt(
                    response.attempted_dispatch,
                    attempted,
                )
                or not _tool_response_identity_matches_receipt(
                    response.persisted_dispatch,
                    persisted,
                )
                or response.request_hash != attempted.request.request_hash
                or response.request_hash != persisted.request.request_hash
                or response.tool_invocation_id
                != attempted.request.tool_invocation_id
                or response.tool_invocation_id
                != persisted.request.tool_invocation_id
            ):
                raise H12IntentConflict(
                    "governed Tool terminal response is not bound to receipt history"
                )
            if not _current_fence_can_settle_tool_receipt(fence, attempted):
                raise H12CausalFenceRejected(
                    "current Driver fence cannot settle the attempted Tool receipt"
                )
            self._require_two_bindings(document, attempted, persisted)
            existing = document["terminalResponse"]
            response_data = response.model_dump(mode="json", by_alias=True)
            durable = _tool_intent(document)
            if existing is not None:
                if existing != response_data or durable.local_state != LocalIntentState.TERMINAL:
                    raise H12IntentConflict(
                        "governed Tool terminal response conflicts with checkpoint evidence"
                    )
                return
            if durable.local_state != LocalIntentState.DISPATCHING:
                raise H12CausalFenceRejected(
                    "governed Tool slot is not eligible for terminal convergence"
                )
            intent = _required_object(document["intent"], "Tool intent")
            intent["localState"] = LocalIntentState.TERMINAL.value
            intent["javaStatus"] = completion["java_status"]
            intent["responsePayload"] = completion["response_payload"]
            document["terminalResponse"] = response_data
            await self._save_slot("tool", document, "TOOL_1_TERMINAL")

    async def load_governed_after_tool_terminal_evidence(
        self,
        execution_id: UUID,
    ) -> GovernedAfterToolTerminalEvidence | None:
        self._require_execution(execution_id)
        evidence = _model_evidence(
            self._slot_document("after_tool_model"),
            expected_call_index=2,
        )
        if evidence is None:
            return None
        if evidence.outcome_kind == ModelOutcome.TOOL_SELECTION:
            raise H12IntentConflict("AFTER_TOOL terminal selected another Tool")
        result = GovernedAfterToolTerminalEvidence(
            execution_id=evidence.execution_id,
            model_call_id=evidence.model_call_id,
            request_hash=evidence.request_hash,
            completion_kind=evidence.completion_kind,
            persisted_permit_id=evidence.persisted_permit_id,
            attempted_permit_id=evidence.attempted_permit_id,
            outcome_status=evidence.outcome_status,
            source_fact_id=evidence.source_fact_id,
            source_fact_version=evidence.source_fact_version,
            source_fact_hash=evidence.source_fact_hash,
            outcome_code=evidence.outcome_code,
            java_status=evidence.java_status,
            response_payload=evidence.response_payload,
        )
        _validate_governed_terminal_evidence(result)
        return result

    async def persist_governed_after_tool_model_receipt(
        self,
        receipt: GovernedAfterToolModelRequestReceipt,
    ) -> GovernedAfterToolModelRequestReceipt:
        if not isinstance(receipt, GovernedAfterToolModelRequestReceipt):
            raise TypeError(
                "receipt must be a GovernedAfterToolModelRequestReceipt"
            )
        return await self._persist_model_receipt(
            "after_tool_model",
            "after_tool",
            receipt,
            2,
        )

    async def begin_governed_after_tool_model_dispatch(
        self,
        receipt: GovernedAfterToolModelRequestReceipt,
        fence: DriverFence,
    ) -> None:
        if not isinstance(receipt, GovernedAfterToolModelRequestReceipt):
            raise TypeError(
                "receipt must be a GovernedAfterToolModelRequestReceipt"
            )
        if not _after_tool_fence_matches_receipt(fence, receipt):
            raise H12CausalFenceRejected(
                "current Driver fence does not match the AFTER_TOOL receipt"
            )
        await self._begin_dispatch(
            "after_tool_model",
            "after_tool",
            receipt,
            2,
        )

    async def require_governed_after_tool_model_dispatch_binding(
        self,
        receipt: GovernedAfterToolModelRequestReceipt,
    ) -> None:
        self._require_binding("after_tool_model", "after_tool", receipt)

    async def complete_governed_after_tool_model(
        self,
        execution_id: UUID,
        fence: DriverFence,
        response: GovernedInitialModelCallResponse,
    ) -> None:
        self._require_execution(execution_id)
        if not isinstance(response, GovernedInitialModelCallResponse):
            raise TypeError("response must be a GovernedInitialModelCallResponse")
        if response.model_call_id != stable_model_call_id(execution_id, 2):
            raise H12IntentConflict("AFTER_TOOL response differs from call two")
        completion = _governed_terminal_completion(response)
        if completion["outcome_kind"] == ModelOutcome.TOOL_SELECTION.value:
            raise H12CausalFenceRejected(
                "AFTER_TOOL model call cannot select another Tool"
            )
        await self._complete_model(
            "after_tool_model",
            "after_tool",
            response,
            fence,
            2,
        )

    async def _persist_model_receipt(
        self,
        slot_name: SlotName,
        kind: ReceiptKind,
        receipt: (
            GovernedInitialModelRequestReceipt
            | GovernedAfterToolModelRequestReceipt
        ),
        call_index: int,
    ) -> Any:
        async with self._write_lock:
            document = self._required_slot(slot_name)
            durable = _model_intent(document, expected_call_index=call_index)
            request = receipt.request
            canonical, request_hash = canonical_intent(request.logical_payload())
            if (
                durable.intent_id != request.model_call_id
                or durable.request_hash != request.request_hash
                or durable.request_hash != request_hash
                or durable.canonical_request != canonical
            ):
                raise H12IntentConflict(
                    "governed model receipt differs from the durable logical intent"
                )
            stored = self._append_receipt(document, kind, receipt)
            if stored is not None:
                return stored
            await self._save_slot(
                slot_name,
                document,
                f"MODEL_{call_index}_RECEIPT_APPENDED",
            )
            return receipt

    def _append_receipt(
        self,
        document: dict[str, object],
        kind: ReceiptKind,
        receipt: Any,
    ) -> Any | None:
        durable = (
            _tool_intent(document)
            if kind == "tool"
            else _model_intent(
                document,
                expected_call_index=1 if kind == "initial" else 2,
            )
        )
        receipts = _required_list(document["receipts"], "receipts")
        existing = _find_receipt(receipts, kind, receipt.runtime_external_permit_id)
        if existing is not None:
            if existing != receipt:
                raise H12IntentConflict(
                    "runtime Permit id is bound to another exact request receipt"
                )
            return existing
        self._reject_cross_slot_receipt_collision(receipt)
        if durable.local_state == LocalIntentState.TERMINAL:
            raise H12CausalFenceRejected(
                "terminal governed slot cannot accept another request receipt"
            )
        if not receipts and durable.local_state != LocalIntentState.PREPARED:
            raise H12CausalFenceRejected(
                "first governed receipt must be persisted from PREPARED"
            )
        latest_epoch = max(
            (int(_required_object(item, "receipt")["leaseEpoch"]) for item in receipts),
            default=None,
        )
        if latest_epoch is not None and receipt.lease_epoch <= latest_epoch:
            raise H12IntentConflict(
                "a new governed receipt must advance the lease epoch"
            )
        receipts.append(_receipt_record(receipt))
        return None

    async def _begin_dispatch(
        self,
        slot_name: SlotName,
        kind: ReceiptKind,
        receipt: Any,
        call_index: int,
    ) -> None:
        async with self._write_lock:
            document = self._required_slot(slot_name)
            durable = (
                _tool_intent(document)
                if kind == "tool"
                else _model_intent(document, expected_call_index=call_index)
            )
            receipts = _required_list(document["receipts"], "receipts")
            stored = _find_receipt(
                receipts,
                kind,
                receipt.runtime_external_permit_id,
            )
            if stored != receipt:
                raise H12CausalFenceRejected(
                    "governed dispatch requires the exact persisted receipt"
                )
            request_id = (
                receipt.request.tool_invocation_id
                if kind == "tool"
                else receipt.request.model_call_id
            )
            if durable.intent_id != request_id or durable.request_hash != receipt.request.request_hash:
                raise H12IntentConflict(
                    "governed dispatch differs from the durable logical intent"
                )
            if durable.local_state == LocalIntentState.TERMINAL:
                raise H12CausalFenceRejected(
                    "terminal governed slot cannot bind another dispatch"
                )
            bindings = _required_list(document["dispatchBindings"], "dispatch bindings")
            permit = str(receipt.runtime_external_permit_id)
            if permit in bindings:
                if durable.local_state != LocalIntentState.DISPATCHING:
                    raise H12IntentConflict(
                        "governed dispatch binding and local state differ"
                    )
                return
            bindings.append(permit)
            intent = _required_object(document["intent"], "intent")
            if durable.local_state == LocalIntentState.PREPARED:
                intent["localState"] = LocalIntentState.DISPATCHING.value
            elif durable.local_state != LocalIntentState.DISPATCHING:
                raise H12CausalFenceRejected(
                    "governed slot cannot bind a dispatch"
                )
            transition = "TOOL_1_DISPATCH_BOUND" if kind == "tool" else f"MODEL_{call_index}_DISPATCH_BOUND"
            await self._save_slot(slot_name, document, transition)

    def _require_binding(
        self,
        slot_name: SlotName,
        kind: ReceiptKind,
        receipt: Any,
    ) -> None:
        document = self._required_slot(slot_name)
        stored = _find_receipt(
            _required_list(document["receipts"], "receipts"),
            kind,
            receipt.runtime_external_permit_id,
        )
        bindings = _required_list(document["dispatchBindings"], "dispatch bindings")
        if stored != receipt or str(receipt.runtime_external_permit_id) not in bindings:
            raise H12CausalFenceRejected(
                "governed receipt has no exact historical dispatch binding"
            )

    async def _complete_model(
        self,
        slot_name: SlotName,
        kind: ReceiptKind,
        response: GovernedInitialModelCallResponse,
        fence: DriverFence,
        call_index: int,
    ) -> None:
        completion = _governed_terminal_completion(response)
        async with self._write_lock:
            document = self._required_slot(slot_name)
            attempted, persisted = self._terminal_receipts(
                document,
                kind,
                response.attempted_dispatch.runtime_external_permit_id,
                response.persisted_dispatch.runtime_external_permit_id,
            )
            identity_matcher = (
                _response_identity_matches_receipt
                if kind == "initial"
                else _after_tool_response_identity_matches_receipt
            )
            if (
                not identity_matcher(response.attempted_dispatch, attempted)
                or not identity_matcher(response.persisted_dispatch, persisted)
                or response.request_hash != attempted.request.request_hash
                or response.request_hash != persisted.request.request_hash
                or response.model_call_id != attempted.request.model_call_id
                or response.model_call_id != persisted.request.model_call_id
            ):
                raise H12IntentConflict(
                    "governed terminal response is not bound to receipt history"
                )
            can_settle = (
                _current_fence_can_settle_receipt
                if kind == "initial"
                else _current_fence_can_settle_after_tool_receipt
            )
            if not can_settle(fence, attempted):
                raise H12CausalFenceRejected(
                    "current Driver fence cannot settle the attempted receipt"
                )
            self._require_two_bindings(document, attempted, persisted)
            response_data = response.model_dump(mode="json", by_alias=True)
            existing = document["terminalResponse"]
            durable = _model_intent(document, expected_call_index=call_index)
            if existing is not None:
                if existing != response_data or durable.local_state != LocalIntentState.TERMINAL:
                    raise H12IntentConflict(
                        "governed terminal response conflicts with checkpoint evidence"
                    )
                return
            if durable.local_state != LocalIntentState.DISPATCHING:
                raise H12CausalFenceRejected(
                    "governed model slot is not eligible for terminal convergence"
                )
            intent = _required_object(document["intent"], "model intent")
            intent["localState"] = LocalIntentState.TERMINAL.value
            intent["javaStatus"] = completion["java_status"]
            intent["outcomeKind"] = completion["outcome_kind"]
            intent["modelToolSelectionId"] = completion["model_tool_selection_id"]
            intent["responsePayload"] = completion["response_payload"]
            document["terminalResponse"] = response_data
            await self._save_slot(
                slot_name,
                document,
                f"MODEL_{call_index}_TERMINAL",
            )

    def _terminal_receipts(
        self,
        document: dict[str, object],
        kind: ReceiptKind,
        attempted_permit: UUID,
        persisted_permit: UUID,
    ) -> tuple[Any, Any]:
        receipts = _required_list(document["receipts"], "receipts")
        attempted = _find_receipt(receipts, kind, attempted_permit)
        persisted = _find_receipt(receipts, kind, persisted_permit)
        if attempted is None or persisted is None:
            raise H12IntentConflict(
                "governed terminal response is not bound to receipt history"
            )
        return attempted, persisted

    @staticmethod
    def _require_two_bindings(
        document: dict[str, object],
        attempted: Any,
        persisted: Any,
    ) -> None:
        bindings = _required_list(document["dispatchBindings"], "dispatch bindings")
        if (
            str(attempted.runtime_external_permit_id) not in bindings
            or str(persisted.runtime_external_permit_id) not in bindings
        ):
            raise H12CausalFenceRejected(
                "governed terminal response lacks exact dispatch history"
            )

    def _reject_cross_slot_receipt_collision(self, receipt: Any) -> None:
        for slot_name, kind in (
            ("initial_model", "initial"),
            ("tool", "tool"),
            ("after_tool_model", "after_tool"),
        ):
            document = self._slot_document(slot_name)
            if document is None:
                continue
            for record in _required_list(document["receipts"], "receipts"):
                stored = _restore_receipt(kind, record)
                if (
                    stored.runtime_external_permit_id
                    == receipt.runtime_external_permit_id
                    or stored.arm_event_id == receipt.arm_event_id
                ):
                    raise H12IntentConflict(
                        "governed receipt collides with Permit or Arm history"
                    )

    def _slot_document(self, slot_name: SlotName) -> dict[str, object] | None:
        self._require_entered()
        value = getattr(self._state, slot_name)
        return value.to_builtin() if value is not None else None

    def _required_slot(self, slot_name: SlotName) -> dict[str, object]:
        document = self._slot_document(slot_name)
        if document is None:
            raise H12CausalFenceRejected("governed checkpoint slot is missing")
        return document

    async def _save_slot(
        self,
        slot_name: SlotName,
        document: dict[str, object],
        transition_code: str,
    ) -> None:
        _validate_slot(slot_name, document)
        state = replace(self._state, **{slot_name: FrozenJsonObject(document)})
        fact = await self._store.save(
            self._fence,
            expected=self._fact,
            transition_code=transition_code,
            state=state,
        )
        self._state = state
        self._fact = fact

    def _require_execution(self, execution_id: UUID) -> None:
        self._require_entered()
        if not isinstance(execution_id, UUID) or execution_id.int == 0:
            raise ValueError("execution_id must be a non-nil UUID")
        if execution_id != self._fence.runtime_run_id:
            raise H12CausalFenceRejected(
                "execution id differs from the current Run fence"
            )

    def _require_entered(self) -> None:
        if not self._entered:
            raise RuntimeError("PostgreSQL governed H12 slots are not open")


def _new_model_slot(
    execution_id: UUID,
    call_index: int,
    intent_id: UUID,
    request_hash: str,
    canonical: str,
) -> dict[str, object]:
    return {
        "schemaVersion": "governed-h12-model-slot-v1",
        "callIndex": call_index,
        "intent": {
            "executionId": str(execution_id),
            "intentId": str(intent_id),
            "requestHash": request_hash,
            "canonicalRequest": canonical,
            "localState": LocalIntentState.PREPARED.value,
            "javaStatus": None,
            "outcomeKind": None,
            "modelToolSelectionId": None,
            "responsePayload": None,
        },
        "receipts": [],
        "dispatchBindings": [],
        "terminalResponse": None,
    }


def _new_tool_slot(
    execution_id: UUID,
    intent_id: UUID,
    source_model_call_id: UUID,
    model_tool_selection_id: UUID,
    request_hash: str,
    canonical: str,
) -> dict[str, object]:
    return {
        "schemaVersion": "governed-h12-tool-slot-v1",
        "intent": {
            "executionId": str(execution_id),
            "intentId": str(intent_id),
            "sourceModelCallId": str(source_model_call_id),
            "modelToolSelectionId": str(model_tool_selection_id),
            "requestHash": request_hash,
            "canonicalRequest": canonical,
            "localState": LocalIntentState.PREPARED.value,
            "javaStatus": None,
            "responsePayload": None,
        },
        "receipts": [],
        "dispatchBindings": [],
        "terminalResponse": None,
    }


def _model_intent(
    document: dict[str, object],
    *,
    expected_call_index: int,
) -> DurableIntent:
    _validate_slot(
        "initial_model" if expected_call_index == 1 else "after_tool_model",
        document,
    )
    if document["callIndex"] != expected_call_index:
        raise H12IntentConflict("model checkpoint call index is inconsistent")
    value = _required_object(document["intent"], "model intent")
    return DurableIntent(
        execution_id=UUID(str(value["executionId"])),
        call_index=expected_call_index,
        intent_id=UUID(str(value["intentId"])),
        request_hash=str(value["requestHash"]),
        canonical_request=str(value["canonicalRequest"]),
        local_state=LocalIntentState(str(value["localState"])),
        java_status=str(value["javaStatus"]) if value["javaStatus"] is not None else None,
        outcome_kind=(
            ModelOutcome(str(value["outcomeKind"]))
            if value["outcomeKind"] is not None
            else None
        ),
        model_tool_selection_id=(
            UUID(str(value["modelToolSelectionId"]))
            if value["modelToolSelectionId"] is not None
            else None
        ),
        response_payload=(
            _required_object(value["responsePayload"], "model response payload")
            if value["responsePayload"] is not None
            else None
        ),
    )


def _tool_intent(document: dict[str, object]) -> DurableIntent:
    _validate_slot("tool", document)
    value = _required_object(document["intent"], "Tool intent")
    return DurableIntent(
        execution_id=UUID(str(value["executionId"])),
        call_index=1,
        intent_id=UUID(str(value["intentId"])),
        request_hash=str(value["requestHash"]),
        canonical_request=str(value["canonicalRequest"]),
        local_state=LocalIntentState(str(value["localState"])),
        java_status=str(value["javaStatus"]) if value["javaStatus"] is not None else None,
        outcome_kind=None,
        model_tool_selection_id=UUID(str(value["modelToolSelectionId"])),
        response_payload=(
            _required_object(value["responsePayload"], "Tool response payload")
            if value["responsePayload"] is not None
            else None
        ),
    )


def _model_evidence(
    document: dict[str, object] | None,
    *,
    expected_call_index: int,
) -> GovernedInitialTerminalEvidence | None:
    if document is None:
        return None
    durable = _model_intent(document, expected_call_index=expected_call_index)
    if document["terminalResponse"] is None:
        if durable.local_state == LocalIntentState.TERMINAL:
            raise H12IntentConflict("terminal model checkpoint lacks response evidence")
        return None
    response = _model_response(document["terminalResponse"])
    completion = _governed_terminal_completion(response)
    fact = response.canonical_fact
    evidence = GovernedInitialTerminalEvidence(
        execution_id=durable.execution_id,
        model_call_id=response.model_call_id,
        request_hash=response.request_hash,
        completion_kind=str(completion["completion_kind"]),
        persisted_permit_id=response.persisted_dispatch.runtime_external_permit_id,
        attempted_permit_id=response.attempted_dispatch.runtime_external_permit_id,
        outcome_status=fact.outcome_status if fact is not None else None,
        source_fact_id=fact.source_fact_id if fact is not None else None,
        source_fact_version=fact.source_fact_version if fact is not None else None,
        source_fact_hash=fact.source_fact_hash if fact is not None else None,
        outcome_code=fact.outcome_code if fact is not None else None,
        java_status=str(completion["java_status"]),
        outcome_kind=(
            ModelOutcome(str(completion["outcome_kind"]))
            if completion["outcome_kind"] is not None
            else None
        ),
        model_tool_selection_id=(
            UUID(str(completion["model_tool_selection_id"]))
            if completion["model_tool_selection_id"] is not None
            else None
        ),
        response_payload=_required_object(
            completion["response_payload"],
            "model response payload",
        ),
    )
    if durable.local_state != LocalIntentState.TERMINAL:
        raise H12IntentConflict("model terminal response and state differ")
    _validate_governed_terminal_evidence(evidence)
    return evidence


def _tool_evidence(
    document: dict[str, object] | None,
) -> GovernedToolTerminalEvidence | None:
    if document is None:
        return None
    durable = _tool_intent(document)
    if document["terminalResponse"] is None:
        if durable.local_state == LocalIntentState.TERMINAL:
            raise H12IntentConflict("terminal Tool checkpoint lacks response evidence")
        return None
    response = _tool_response(document["terminalResponse"])
    completion = _governed_tool_terminal_completion(response)
    fact = response.canonical_fact
    assert fact is not None
    evidence = GovernedToolTerminalEvidence(
        execution_id=durable.execution_id,
        tool_invocation_id=response.tool_invocation_id,
        request_hash=response.request_hash,
        persisted_permit_id=response.persisted_dispatch.runtime_external_permit_id,
        attempted_permit_id=response.attempted_dispatch.runtime_external_permit_id,
        outcome_status=fact.outcome_status,
        source_fact_id=fact.source_fact_id,
        source_fact_version=fact.source_fact_version,
        source_fact_hash=fact.source_fact_hash,
        outcome_code=fact.outcome_code,
        java_status=str(completion["java_status"]),
        response_payload=_required_object(
            completion["response_payload"],
            "Tool response payload",
        ),
    )
    if durable.local_state != LocalIntentState.TERMINAL:
        raise H12IntentConflict("Tool terminal response and state differ")
    _validate_governed_tool_terminal_evidence(evidence)
    return evidence


def _receipt_record(receipt: Any) -> dict[str, object]:
    return {
        "executionId": str(receipt.execution_id),
        "runtimeExternalPermitId": str(receipt.runtime_external_permit_id),
        "armEventId": str(receipt.arm_event_id),
        "leaseEpoch": receipt.lease_epoch,
        "bodySha256": receipt.body_sha256,
        "exactBody": receipt.exact_body.decode("utf-8"),
    }


def _find_receipt(
    records: list[object],
    kind: ReceiptKind,
    permit_id: UUID,
) -> Any | None:
    for record in records:
        value = _required_object(record, "receipt")
        if UUID(str(value["runtimeExternalPermitId"])) == permit_id:
            return _restore_receipt(kind, value)
    return None


def _restore_receipt(kind: ReceiptKind, record: object) -> Any:
    value = _required_object(record, "receipt")
    _require_exact_keys(value, _RECEIPT_KEYS, "receipt")
    exact_body = str(value["exactBody"]).encode("utf-8")
    execution_id = UUID(str(value["executionId"]))
    receipt_type = {
        "initial": GovernedInitialModelRequestReceipt,
        "tool": GovernedToolRequestReceipt,
        "after_tool": GovernedAfterToolModelRequestReceipt,
    }[kind]
    receipt = receipt_type.restore(
        execution_id,
        exact_body,
        str(value["bodySha256"]),
    )
    if (
        receipt.runtime_external_permit_id
        != UUID(str(value["runtimeExternalPermitId"]))
        or receipt.arm_event_id != UUID(str(value["armEventId"]))
        or receipt.lease_epoch != int(value["leaseEpoch"])
    ):
        raise H12IntentConflict("governed receipt metadata differs from exact body")
    return receipt


def _model_response(value: object) -> GovernedInitialModelCallResponse:
    return GovernedInitialModelCallResponse.model_validate_json(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        strict=True,
    )


def _tool_response(value: object) -> GovernedToolCallResponse:
    return GovernedToolCallResponse.model_validate_json(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
        strict=True,
    )


def _validate_state(state: RuntimeH12SlotsState) -> None:
    for name in ("initial_model", "tool", "after_tool_model"):
        value = getattr(state, name)
        if value is not None:
            _validate_slot(name, value.to_builtin())


def _validate_slot(slot_name: SlotName, document: dict[str, object]) -> None:
    if slot_name == "tool":
        _require_exact_keys(document, _TOOL_SLOT_KEYS, "Tool slot")
        if document["schemaVersion"] != "governed-h12-tool-slot-v1":
            raise H12IntentConflict("Tool checkpoint schema is unsupported")
        intent = _required_object(document["intent"], "Tool intent")
        _require_exact_keys(intent, _TOOL_INTENT_KEYS, "Tool intent")
    else:
        _require_exact_keys(document, _MODEL_SLOT_KEYS, "model slot")
        if document["schemaVersion"] != "governed-h12-model-slot-v1":
            raise H12IntentConflict("model checkpoint schema is unsupported")
        expected = 1 if slot_name == "initial_model" else 2
        if document["callIndex"] != expected:
            raise H12IntentConflict("model checkpoint call index is inconsistent")
        intent = _required_object(document["intent"], "model intent")
        _require_exact_keys(intent, _MODEL_INTENT_KEYS, "model intent")
    receipts = _required_list(document["receipts"], "receipts")
    for receipt in receipts:
        _require_exact_keys(_required_object(receipt, "receipt"), _RECEIPT_KEYS, "receipt")
    bindings = _required_list(document["dispatchBindings"], "dispatch bindings")
    if any(not isinstance(value, str) for value in bindings):
        raise H12IntentConflict("dispatch binding must be a Permit id string")
    LocalIntentState(str(intent["localState"]))
    if intent["executionId"] is None or UUID(str(intent["executionId"])).int == 0:
        raise H12IntentConflict("checkpoint execution id is invalid")
    if UUID(str(intent["intentId"])).int == 0:
        raise H12IntentConflict("checkpoint intent id is invalid")
    request_hash = str(intent["requestHash"])
    if len(request_hash) != 64 or any(ch not in "0123456789abcdef" for ch in request_hash):
        raise H12IntentConflict("checkpoint request hash is invalid")
    canonical = str(intent["canonicalRequest"])
    if canonical_intent(_required_object(json.loads(canonical), "canonical intent"))[0] != canonical:
        raise H12IntentConflict("checkpoint canonical intent is not canonical JSON")


def _required_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise H12IntentConflict(f"{label} must be a JSON object")
    return value


def _required_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise H12IntentConflict(f"{label} must be a JSON array")
    return value


def _require_exact_keys(
    value: dict[str, object],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise H12IntentConflict(f"{label} fields differ from the frozen contract")

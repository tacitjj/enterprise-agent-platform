from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

from dianlian_runtime.harness.admission_manifest import (
    AdmissionManifestFailedSafe,
    AdmissionManifestOutcomeUnknown,
    JavaAdmissionManifestClient,
)
from dianlian_runtime.harness.governed_model_gateway import (
    GovernedInitialModelCallResponse,
    GovernedInitialModelGatewayClient,
    GovernedModelGatewayFailure,
    GovernedModelGatewayOutcomeUnknown,
    GovernedModelGatewayRejected,
)
from dianlian_runtime.harness.governed_model_intent import (
    GovernedAfterToolModelIntent,
    GovernedInitialModelIntent,
    build_governed_initial_model_intent,
)
from dianlian_runtime.harness.governed_model_receipt import (
    GovernedAfterToolModelRequestReceipt,
    GovernedInitialModelRequestReceipt,
)
from dianlian_runtime.harness.governed_h12_slots import (
    GovernedH12Slots,
    GovernedH12SlotsFactory,
)
from dianlian_runtime.harness.governed_tool_gateway import (
    GovernedToolCallResponse,
    GovernedToolGatewayClient,
    GovernedToolGatewayFailure,
    GovernedToolGatewayOutcomeUnknown,
    GovernedToolGatewayRejected,
)
from dianlian_runtime.harness.governed_tool_receipt import (
    GovernedToolIntent,
    GovernedToolRequestReceipt,
)
from dianlian_runtime.harness.h12_durable import (
    GovernedAfterToolTerminalEvidence,
    GovernedInitialTerminalEvidence,
    GovernedToolTerminalEvidence,
    H12DurableSlots,
    H12IntentConflict,
    ModelOutcome,
    ModelPhase,
    canonical_intent,
    stable_model_call_id,
    stable_tool_call_id,
)
from dianlian_runtime.supervisor.admission_permit_issuer import (
    AdmissionPermitDisposition,
    AdmissionPermitFenceRequired,
    AdmissionPermitIssueResult,
    AdmissionPermitOutcomeUnknown,
    DormantAdmissionPermitIssuer,
    IssueAdmissionPermitRequest,
)
from dianlian_runtime.supervisor.contracts import FrozenJsonObject
from dianlian_runtime.supervisor.driver import (
    DriverCheckpointSink,
    DriverExecutionDisposition,
    DriverExecutionRequest,
    DriverExecutionResult,
    DriverFence,
    DriverFenceGate,
    DriverFenceRevoked,
    LocalQuiesceDisposition,
    LocalQuiesceResult,
)
from dianlian_runtime.supervisor.model_permit_issuer import (
    DormantModelPermitIssuer,
    IssueModelPermitRequest,
    ModelPermitDisposition,
    ModelPermitFenceRequired,
    ModelPermitIssueResult,
    ModelPermitOutcomeUnknown,
)
from dianlian_runtime.supervisor.tool_permit_issuer import (
    DormantToolPermitIssuer,
    IssueToolPermitRequest,
    ToolPermitDisposition,
    ToolPermitFenceRequired,
    ToolPermitIssueResult,
    ToolPermitOutcomeUnknown,
)


Offload = Callable[[Callable[[], object]], Awaitable[object]]


class GovernedInitialRunExecutionDriver:
    """Opt-in governed H12 Driver; it never falls back to the legacy path."""

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        slots_factory: GovernedH12SlotsFactory | None = None,
        admission_permit_issuer: DormantAdmissionPermitIssuer,
        admission_manifest_client: JavaAdmissionManifestClient,
        model_permit_issuer: DormantModelPermitIssuer,
        model_gateway: GovernedInitialModelGatewayClient,
        tool_permit_issuer: DormantToolPermitIssuer | None = None,
        tool_gateway: GovernedToolGatewayClient | None = None,
        permit_ttl_seconds: int = 30,
        offload: Offload | None = None,
    ) -> None:
        if slots_factory is None and not isinstance(data_dir, Path):
            raise TypeError("data_dir must be a Path when slots_factory is absent")
        if slots_factory is not None and not callable(slots_factory):
            raise TypeError("slots_factory must be callable")
        if slots_factory is not None and data_dir is not None:
            raise ValueError("data_dir and slots_factory are mutually exclusive")
        if not callable(getattr(admission_permit_issuer, "issue", None)):
            raise TypeError("admission_permit_issuer must provide issue")
        if not callable(getattr(admission_manifest_client, "resolve", None)):
            raise TypeError("admission_manifest_client must provide resolve")
        if not callable(getattr(model_permit_issuer, "issue", None)):
            raise TypeError("model_permit_issuer must provide issue")
        if not callable(getattr(model_gateway, "invoke_initial", None)):
            raise TypeError("model_gateway must provide invoke_initial")
        if (tool_permit_issuer is None) != (tool_gateway is None):
            raise ValueError("governed Tool issuer and gateway must be configured together")
        if tool_permit_issuer is not None:
            if not callable(getattr(tool_permit_issuer, "issue", None)):
                raise TypeError("tool_permit_issuer must provide issue")
            if not callable(getattr(tool_gateway, "invoke", None)):
                raise TypeError("tool_gateway must provide invoke")
            if not callable(getattr(model_gateway, "invoke_after_tool", None)):
                raise TypeError("model_gateway must provide invoke_after_tool")
        if isinstance(permit_ttl_seconds, bool) or not 1 <= permit_ttl_seconds <= 60:
            raise ValueError("permit_ttl_seconds is outside its allowed range")
        if offload is not None and not callable(offload):
            raise TypeError("offload must be callable")
        self._data_dir = data_dir.resolve() if data_dir is not None else None
        self._slots_factory = slots_factory or self._local_slots
        self._admission_permit_issuer = admission_permit_issuer
        self._admission_manifest_client = admission_manifest_client
        self._model_permit_issuer = model_permit_issuer
        self._model_gateway = model_gateway
        self._tool_permit_issuer = tool_permit_issuer
        self._tool_gateway = tool_gateway
        self._permit_ttl_seconds = permit_ttl_seconds
        self._offload_impl = offload or asyncio.to_thread
        self._offloads: set[asyncio.Task[object]] = set()
        self._execution_lock = asyncio.Lock()
        self._started = False
        self._closed = False

    @property
    def ready(self) -> bool:
        return self._started and not self._closed

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("governed initial Driver cannot be started twice")
        if self._closed:
            raise RuntimeError("closed governed initial Driver cannot be started")
        if self._data_dir is not None:
            self._data_dir.mkdir(parents=True, exist_ok=True)
        start_slots = getattr(self._slots_factory, "start", None)
        if callable(start_slots):
            try:
                await start_slots()
                if getattr(self._slots_factory, "ready", True) is not True:
                    raise RuntimeError("governed H12 slots did not become ready")
            except BaseException:
                close_slots = getattr(self._slots_factory, "close", None)
                if callable(close_slots):
                    await close_slots()
                raise
        self._started = True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        while self._offloads:
            await asyncio.gather(*tuple(self._offloads), return_exceptions=True)
        close_slots = getattr(self._slots_factory, "close", None)
        if callable(close_slots):
            await close_slots()
        await self._admission_manifest_client.aclose()
        await self._model_gateway.aclose()
        if self._tool_gateway is not None:
            await self._tool_gateway.aclose()

    async def execute(
        self,
        request: DriverExecutionRequest,
        *,
        gate: DriverFenceGate,
        checkpoints: DriverCheckpointSink,
    ) -> DriverExecutionResult:
        del checkpoints
        if not self.ready:
            raise RuntimeError("governed initial Driver is not ready")
        if not isinstance(request, DriverExecutionRequest):
            raise TypeError("request must be a DriverExecutionRequest")
        if gate.revoked:
            raise DriverFenceRevoked("runtime execution fence is revoked")
        async with self._execution_lock:
            async with self._slots_factory(request.fence) as slots:
                intent = await slots.load_governed_initial_model_intent(
                    request.fence.runtime_run_id
                )
                if intent is None:
                    resolved = await self._resolve_initial_intent(request, gate)
                    if isinstance(resolved, DriverExecutionResult):
                        return resolved
                    intent = resolved
                    durable = await slots.prepare_model(
                        request.fence.runtime_run_id,
                        1,
                        ModelPhase.TOOL_DECISION,
                        intent.durable_payload(),
                    )
                    _, request_hash = canonical_intent(intent.durable_payload())
                    if (
                        durable.intent_id != intent.model_call_id
                        or durable.request_hash != request_hash
                    ):
                        raise DriverFenceRevoked(
                            "governed logical intent persistence mismatched"
                        )
                _require_intent_matches_execution(intent, request)
                terminal = await slots.load_governed_initial_terminal_evidence(
                    request.fence.runtime_run_id
                )
                if terminal is not None:
                    await gate.authorize_execution()
                    if terminal.outcome_kind == ModelOutcome.TOOL_SELECTION:
                        return await self._continue_after_initial_selection(
                            slots,
                            request,
                            intent,
                            terminal,
                            gate,
                        )
                    return _local_model_terminal_result(terminal)
                return await self._invoke_initial(
                    slots,
                    request,
                    intent,
                    gate,
                )

    async def quiesce_locally(self, fence: DriverFence) -> LocalQuiesceResult:
        if not isinstance(fence, DriverFence):
            raise TypeError("fence must be a DriverFence")
        return LocalQuiesceResult(LocalQuiesceDisposition.QUIESCED)

    async def _resolve_initial_intent(
        self,
        request: DriverExecutionRequest,
        gate: DriverFenceGate,
    ) -> GovernedInitialModelIntent | DriverExecutionResult:
        await gate.authorize_execution()
        try:
            issued = await self._offload(
                lambda: self._admission_permit_issuer.issue(
                    IssueAdmissionPermitRequest(
                        request.authority,
                        request.fence,
                        self._permit_ttl_seconds,
                    )
                )
            )
        except AdmissionPermitOutcomeUnknown as exception:
            return _permit_issue_outcome_unknown_result(
                "ADMISSION_RESOLVE",
                exception.code,
                request.authority.admission_snapshot_id,
            )
        except AdmissionPermitFenceRequired as exception:
            raise DriverFenceRevoked("admission permit outcome is unknown") from exception
        if not isinstance(issued, AdmissionPermitIssueResult):
            raise DriverFenceRevoked("admission permit result is invalid")
        if not issued.manifest_resolve_allowed:
            if issued.disposition != AdmissionPermitDisposition.HISTORICAL_CONSUMED:
                raise DriverFenceRevoked("admission permit disposition is unsupported")
            return DriverExecutionResult(
                DriverExecutionDisposition.FAILED_CONFIRMED,
                "ADMISSION_MANIFEST_UNRECOVERABLE",
                "ADMISSION_PERMIT_HISTORICAL_CONSUMED",
                FrozenJsonObject(
                    {
                        "schemaVersion": "admission-manifest-convergence-v1",
                        "operation": "ADMISSION_RESOLVE",
                        "code": "ADMISSION_PERMIT_HISTORICAL_CONSUMED",
                        "persistedPermitId": str(
                            issued.permit.runtime_external_permit_id
                        ),
                    }
                ),
            )
        try:
            manifest = await self._admission_manifest_client.resolve(
                request,
                issued.permit,
                gate=gate,
            )
        except AdmissionManifestFailedSafe:
            return _failed_result(
                "ADMISSION_MANIFEST_REJECTED",
                "ADMISSION_MANIFEST_REJECTED",
                None,
            )
        except AdmissionManifestOutcomeUnknown as exception:
            return DriverExecutionResult(
                DriverExecutionDisposition.CONVERGENCE_PENDING,
                None,
                None,
                FrozenJsonObject(
                    {
                        "schemaVersion": "admission-manifest-convergence-v1",
                        "code": exception.code,
                        "action": "QUERY_EXACT_ADMISSION_MANIFEST",
                        "persistedPermitId": str(
                            issued.permit.runtime_external_permit_id
                        ),
                    }
                ),
            )
        try:
            return build_governed_initial_model_intent(manifest)
        except (TypeError, ValueError) as exception:
            raise DriverFenceRevoked("admission manifest intent is invalid") from exception

    async def _invoke_initial(
        self,
        slots: GovernedH12Slots,
        request: DriverExecutionRequest,
        intent: GovernedInitialModelIntent,
        gate: DriverFenceGate,
    ) -> DriverExecutionResult:
        _, request_hash = canonical_intent(intent.durable_payload())
        await gate.authorize_execution()
        try:
            issued = await self._offload(
                lambda: self._model_permit_issuer.issue(
                    IssueModelPermitRequest(
                        request.authority,
                        request.fence,
                        intent.model_call_id,
                        request_hash,
                        self._permit_ttl_seconds,
                    )
                )
            )
        except ModelPermitOutcomeUnknown as exception:
            return _permit_issue_outcome_unknown_result(
                "MODEL_INVOKE",
                exception.code,
                intent.model_call_id,
            )
        except ModelPermitFenceRequired as exception:
            raise DriverFenceRevoked("model permit outcome is unknown") from exception
        if not isinstance(issued, ModelPermitIssueResult):
            raise DriverFenceRevoked("model permit result is invalid")
        receipt = GovernedInitialModelRequestReceipt.create(
            request.fence.runtime_run_id,
            intent,
            issued.receipt,
        )
        await slots.persist_governed_initial_model_receipt(receipt)
        if issued.disposition == ModelPermitDisposition.CURRENT_ISSUED:
            await gate.authorize_execution()
            await slots.begin_governed_initial_model_dispatch(receipt, request.fence)
        elif issued.disposition == ModelPermitDisposition.HISTORICAL_CONSUMED:
            await slots.require_governed_initial_model_dispatch_binding(receipt)
        else:
            raise DriverFenceRevoked("model permit disposition is unsupported")

        await gate.authorize_execution()
        try:
            response = await self._model_gateway.invoke_initial(receipt)
        except GovernedModelGatewayOutcomeUnknown as exception:
            return _gateway_outcome_unknown_result(
                "MODEL",
                exception.code,
                exception.action,
                receipt.runtime_external_permit_id,
            )
        except GovernedModelGatewayRejected as exception:
            return _gateway_rejected_result(
                "MODEL",
                exception.code,
                exception.action,
                receipt.runtime_external_permit_id,
            )
        except GovernedModelGatewayFailure as exception:
            raise DriverFenceRevoked("governed Java model outcome is unknown") from exception
        if response.disposition == "GOVERNED_TOOL_REQUIRED":
            await gate.authorize_execution()
            try:
                await slots.complete_governed_initial_model(
                    request.fence.runtime_run_id,
                    request.fence,
                    response,
                )
                terminal = await slots.load_governed_initial_terminal_evidence(
                    request.fence.runtime_run_id
                )
            except (H12IntentConflict, RuntimeError, ValueError) as exception:
                raise DriverFenceRevoked(
                    "governed Tool selection convergence was fenced"
                ) from exception
            if terminal is None or terminal.outcome_kind != ModelOutcome.TOOL_SELECTION:
                raise DriverFenceRevoked(
                    "governed Tool selection evidence is missing"
                )
            return await self._continue_after_initial_selection(
                slots,
                request,
                intent,
                terminal,
                gate,
            )
        if not _model_response_is_releasable(response):
            return _model_nonterminal_result(response)
        await gate.authorize_execution()
        try:
            await slots.complete_governed_initial_model(
                request.fence.runtime_run_id,
                request.fence,
                response,
            )
        except (H12IntentConflict, RuntimeError, ValueError) as exception:
            raise DriverFenceRevoked(
                "governed local terminal convergence was fenced"
            ) from exception
        return _terminal_result(response)

    async def _continue_after_initial_selection(
        self,
        slots: GovernedH12Slots,
        request: DriverExecutionRequest,
        initial_intent: GovernedInitialModelIntent,
        initial_evidence: GovernedInitialTerminalEvidence,
        gate: DriverFenceGate,
    ) -> DriverExecutionResult:
        if self._tool_permit_issuer is None or self._tool_gateway is None:
            return _evidence_fenced_result(
                "GOVERNED_TOOL_RUNTIME_NOT_CONFIGURED",
                initial_evidence.persisted_permit_id,
            )
        selection_id = initial_evidence.model_tool_selection_id
        if selection_id is None:
            raise DriverFenceRevoked("governed Tool selection id is missing")
        tool_intent = _tool_intent(
            initial_intent,
            selection_id,
            request.fence.runtime_run_id,
        )
        durable = await slots.prepare_tool(
            request.fence.runtime_run_id,
            source_model_call_id=initial_intent.model_call_id,
            model_tool_selection_id=selection_id,
            request_without_hash=tool_intent.durable_payload(),
        )
        _, request_hash = canonical_intent(tool_intent.durable_payload())
        if (
            durable.intent_id != tool_intent.tool_invocation_id
            or durable.request_hash != request_hash
        ):
            raise DriverFenceRevoked("governed Tool intent persistence mismatched")

        tool_evidence = await slots.load_governed_tool_terminal_evidence(
            request.fence.runtime_run_id
        )
        if tool_evidence is None:
            tool_result = await self._invoke_tool(
                slots,
                request,
                tool_intent,
                gate,
            )
            if tool_result is not None:
                return tool_result
            tool_evidence = await slots.load_governed_tool_terminal_evidence(
                request.fence.runtime_run_id
            )
        if tool_evidence is None:
            raise DriverFenceRevoked("governed Tool terminal evidence is missing")
        if tool_evidence.outcome_status != "SUCCEEDED":
            await gate.authorize_execution()
            return _local_tool_failure_result(tool_evidence)
        return await self._continue_after_tool(
            slots,
            request,
            initial_intent,
            gate,
        )

    async def _invoke_tool(
        self,
        slots: GovernedH12Slots,
        request: DriverExecutionRequest,
        intent: GovernedToolIntent,
        gate: DriverFenceGate,
    ) -> DriverExecutionResult | None:
        assert self._tool_permit_issuer is not None
        assert self._tool_gateway is not None
        _, request_hash = canonical_intent(intent.durable_payload())
        await gate.authorize_execution()
        try:
            issued = await self._offload(
                lambda: self._tool_permit_issuer.issue(
                    IssueToolPermitRequest(
                        request.authority,
                        request.fence,
                        intent.tool_invocation_id,
                        request_hash,
                        self._permit_ttl_seconds,
                    )
                )
            )
        except ToolPermitOutcomeUnknown as exception:
            return _permit_issue_outcome_unknown_result(
                "TOOL_INVOKE",
                exception.code,
                intent.tool_invocation_id,
            )
        except ToolPermitFenceRequired as exception:
            raise DriverFenceRevoked("Tool permit outcome is unknown") from exception
        if not isinstance(issued, ToolPermitIssueResult):
            raise DriverFenceRevoked("Tool permit result is invalid")
        receipt = GovernedToolRequestReceipt.create(
            request.fence.runtime_run_id,
            intent,
            issued.receipt,
        )
        await slots.persist_governed_tool_receipt(receipt)
        if issued.disposition == ToolPermitDisposition.CURRENT_ISSUED:
            await gate.authorize_execution()
            await slots.begin_governed_tool_dispatch(receipt, request.fence)
        elif issued.disposition == ToolPermitDisposition.HISTORICAL_CONSUMED:
            await slots.require_governed_tool_dispatch_binding(receipt)
        else:
            raise DriverFenceRevoked("Tool permit disposition is unsupported")

        await gate.authorize_execution()
        try:
            response = await self._tool_gateway.invoke(receipt)
        except GovernedToolGatewayOutcomeUnknown as exception:
            return _gateway_outcome_unknown_result(
                "TOOL",
                exception.code,
                exception.action,
                receipt.runtime_external_permit_id,
            )
        except GovernedToolGatewayRejected as exception:
            return _gateway_rejected_result(
                "TOOL",
                exception.code,
                exception.action,
                receipt.runtime_external_permit_id,
            )
        except GovernedToolGatewayFailure as exception:
            raise DriverFenceRevoked("governed Java Tool outcome is unknown") from exception
        if not _tool_response_is_releasable(response):
            return _tool_nonterminal_result(response)
        await gate.authorize_execution()
        try:
            await slots.complete_governed_tool(
                request.fence.runtime_run_id,
                request.fence,
                response,
            )
        except (H12IntentConflict, RuntimeError, ValueError) as exception:
            raise DriverFenceRevoked(
                "governed Tool terminal convergence was fenced"
            ) from exception
        return None

    async def _continue_after_tool(
        self,
        slots: GovernedH12Slots,
        request: DriverExecutionRequest,
        initial_intent: GovernedInitialModelIntent,
        gate: DriverFenceGate,
    ) -> DriverExecutionResult:
        intent = _after_tool_intent(
            initial_intent,
            request.fence.runtime_run_id,
        )
        durable = await slots.prepare_model(
            request.fence.runtime_run_id,
            2,
            ModelPhase.FINAL_AFTER_TOOL,
            intent.durable_payload(),
        )
        _, request_hash = canonical_intent(intent.durable_payload())
        if durable.intent_id != intent.model_call_id or durable.request_hash != request_hash:
            raise DriverFenceRevoked("AFTER_TOOL model intent persistence mismatched")
        terminal = await slots.load_governed_after_tool_terminal_evidence(
            request.fence.runtime_run_id
        )
        if terminal is not None:
            await gate.authorize_execution()
            return _local_model_terminal_result(terminal)
        return await self._invoke_after_tool(slots, request, intent, gate)

    async def _invoke_after_tool(
        self,
        slots: GovernedH12Slots,
        request: DriverExecutionRequest,
        intent: GovernedAfterToolModelIntent,
        gate: DriverFenceGate,
    ) -> DriverExecutionResult:
        _, request_hash = canonical_intent(intent.durable_payload())
        await gate.authorize_execution()
        try:
            issued = await self._offload(
                lambda: self._model_permit_issuer.issue(
                    IssueModelPermitRequest(
                        request.authority,
                        request.fence,
                        intent.model_call_id,
                        request_hash,
                        self._permit_ttl_seconds,
                    )
                )
            )
        except ModelPermitOutcomeUnknown as exception:
            return _permit_issue_outcome_unknown_result(
                "MODEL_INVOKE",
                exception.code,
                intent.model_call_id,
            )
        except ModelPermitFenceRequired as exception:
            raise DriverFenceRevoked("AFTER_TOOL model permit outcome is unknown") from exception
        if not isinstance(issued, ModelPermitIssueResult):
            raise DriverFenceRevoked("AFTER_TOOL model permit result is invalid")
        receipt = GovernedAfterToolModelRequestReceipt.create(
            request.fence.runtime_run_id,
            intent,
            issued.receipt,
        )
        await slots.persist_governed_after_tool_model_receipt(receipt)
        if issued.disposition == ModelPermitDisposition.CURRENT_ISSUED:
            await gate.authorize_execution()
            await slots.begin_governed_after_tool_model_dispatch(
                receipt,
                request.fence,
            )
        elif issued.disposition == ModelPermitDisposition.HISTORICAL_CONSUMED:
            await slots.require_governed_after_tool_model_dispatch_binding(receipt)
        else:
            raise DriverFenceRevoked("AFTER_TOOL model permit disposition is unsupported")

        await gate.authorize_execution()
        try:
            response = await self._model_gateway.invoke_after_tool(receipt)
        except GovernedModelGatewayOutcomeUnknown as exception:
            return _gateway_outcome_unknown_result(
                "MODEL",
                exception.code,
                exception.action,
                receipt.runtime_external_permit_id,
            )
        except GovernedModelGatewayRejected as exception:
            return _gateway_rejected_result(
                "MODEL",
                exception.code,
                exception.action,
                receipt.runtime_external_permit_id,
            )
        except GovernedModelGatewayFailure as exception:
            raise DriverFenceRevoked(
                "governed Java AFTER_TOOL outcome is unknown"
            ) from exception
        if not _model_response_is_releasable(response):
            return _model_nonterminal_result(response)
        await gate.authorize_execution()
        try:
            await slots.complete_governed_after_tool_model(
                request.fence.runtime_run_id,
                request.fence,
                response,
            )
        except (H12IntentConflict, RuntimeError, ValueError) as exception:
            raise DriverFenceRevoked(
                "governed AFTER_TOOL terminal convergence was fenced"
            ) from exception
        return _terminal_result(response)

    async def _offload(self, operation: Callable[[], object]) -> object:
        task = asyncio.create_task(self._offload_impl(operation))
        self._offloads.add(task)
        task.add_done_callback(self._offloads.discard)
        return await asyncio.shield(task)

    def _slot_path(self, fence: DriverFence) -> Path:
        if self._data_dir is None:
            raise RuntimeError("local governed H12 data directory is not configured")
        return self._data_dir / f"{fence.runtime_run_id}.db"

    def _local_slots(self, fence: DriverFence) -> H12DurableSlots:
        return H12DurableSlots(self._slot_path(fence))


def _require_intent_matches_execution(
    intent: GovernedInitialModelIntent,
    request: DriverExecutionRequest,
) -> None:
    authority = request.authority
    if (
        intent.model_call_id != stable_model_call_id(authority.runtime_run_id, 1)
        or intent.execution_generation != authority.task_execution_generation
        or intent.admission_snapshot_id != authority.admission_snapshot_id
    ):
        raise DriverFenceRevoked("governed logical intent differs from execution authority")


def _model_response_is_releasable(
    response: GovernedInitialModelCallResponse,
) -> bool:
    if response.disposition == "FAILED_SAFE_BEFORE_ARM":
        return True
    if response.disposition != "CANONICAL_OUTCOME_APPLIED":
        return False
    fact = response.canonical_fact
    return fact is not None and fact.outcome_status != "OUTCOME_UNKNOWN"


def _tool_response_is_releasable(response: GovernedToolCallResponse) -> bool:
    fact = response.canonical_fact
    return (
        response.disposition == "CANONICAL_OUTCOME_APPLIED"
        and response.action == "NONE"
        and fact is not None
        and fact.outcome_status != "OUTCOME_UNKNOWN"
    )


def _terminal_result(
    response: GovernedInitialModelCallResponse,
) -> DriverExecutionResult:
    fact = response.canonical_fact
    event = _event_payload(response)
    if fact is not None and fact.outcome_status == "SUCCEEDED":
        return DriverExecutionResult(
            DriverExecutionDisposition.COMPLETED,
            "GOVERNED_MODEL_FINAL_TEXT",
            None,
            event,
        )
    failure_code = response.failure_code
    if failure_code is None and response.terminal_result is not None:
        failure_code = response.terminal_result.failure_code
    if failure_code is None and fact is not None:
        failure_code = fact.outcome_code
    return DriverExecutionResult(
        DriverExecutionDisposition.FAILED_CONFIRMED,
        "GOVERNED_MODEL_FAILED_CONFIRMED",
        _driver_code(failure_code, "GOVERNED_MODEL_FAILED_SAFE"),
        event,
    )


def _failed_result(
    terminal_reason: str,
    failure_code: str,
    response: GovernedInitialModelCallResponse | None,
) -> DriverExecutionResult:
    payload = (
        _event_payload(response)
        if response is not None
        else FrozenJsonObject({"schemaVersion": "governed-initial-driver-event-v1"})
    )
    return DriverExecutionResult(
        DriverExecutionDisposition.FAILED_CONFIRMED,
        terminal_reason,
        failure_code,
        payload,
    )


def _model_nonterminal_result(
    response: GovernedInitialModelCallResponse,
) -> DriverExecutionResult:
    fact = response.canonical_fact
    if (
        response.disposition == "CANONICAL_OUTCOME_APPLIED"
        and fact is not None
        and fact.outcome_status == "OUTCOME_UNKNOWN"
    ):
        return DriverExecutionResult(
            DriverExecutionDisposition.FAILED_CONFIRMED,
            "MODEL_OUTCOME_UNKNOWN",
            "EXTERNAL_OUTCOME_UNKNOWN",
            _event_payload(response),
        )
    return DriverExecutionResult(
        _nonterminal_disposition(response.action),
        None,
        None,
        _event_payload(response),
    )


def _local_model_terminal_result(
    evidence: GovernedInitialTerminalEvidence | GovernedAfterToolTerminalEvidence,
) -> DriverExecutionResult:
    event = FrozenJsonObject(
        {
            "schemaVersion": "governed-initial-driver-event-v1",
            "modelCallId": str(evidence.model_call_id),
            "requestHash": evidence.request_hash,
            "persistedPermitId": str(evidence.persisted_permit_id),
            **(
                {
                    "outcomeStatus": evidence.outcome_status,
                    "sourceFactId": str(evidence.source_fact_id),
                    "sourceFactVersion": evidence.source_fact_version,
                    "sourceFactHash": evidence.source_fact_hash,
                }
                if evidence.outcome_status is not None
                else {}
            ),
        }
    )
    if evidence.outcome_status == "SUCCEEDED":
        return DriverExecutionResult(
            DriverExecutionDisposition.COMPLETED,
            "GOVERNED_MODEL_FINAL_TEXT",
            None,
            event,
        )
    payload_code = evidence.response_payload.get("failureCode")
    failure_code = payload_code if isinstance(payload_code, str) else None
    return DriverExecutionResult(
        DriverExecutionDisposition.FAILED_CONFIRMED,
        "GOVERNED_MODEL_FAILED_CONFIRMED",
        _driver_code(
            failure_code or evidence.outcome_code,
            "GOVERNED_MODEL_FAILED_SAFE",
        ),
        event,
    )


def _local_tool_failure_result(
    evidence: GovernedToolTerminalEvidence,
) -> DriverExecutionResult:
    return DriverExecutionResult(
        DriverExecutionDisposition.FAILED_CONFIRMED,
        "GOVERNED_TOOL_FAILED_CONFIRMED",
        _driver_code(evidence.outcome_code, "GOVERNED_TOOL_FAILED_SAFE"),
        FrozenJsonObject(
            {
                "schemaVersion": "governed-tool-driver-event-v1",
                "toolInvocationId": str(evidence.tool_invocation_id),
                "requestHash": evidence.request_hash,
                "persistedPermitId": str(evidence.persisted_permit_id),
                "outcomeStatus": evidence.outcome_status,
                "sourceFactId": str(evidence.source_fact_id),
                "sourceFactVersion": evidence.source_fact_version,
                "sourceFactHash": evidence.source_fact_hash,
            }
        ),
    )


def _tool_nonterminal_result(response: GovernedToolCallResponse) -> DriverExecutionResult:
    fact = response.canonical_fact
    payload: dict[str, object] = {
        "schemaVersion": "governed-tool-driver-event-v1",
        "toolInvocationId": str(response.tool_invocation_id),
        "requestHash": response.request_hash,
        "disposition": response.disposition,
        "persistedPermitId": str(
            response.persisted_dispatch.runtime_external_permit_id
        ),
    }
    if fact is not None:
        payload.update(
            {
                "outcomeStatus": fact.outcome_status,
                "sourceFactId": str(fact.source_fact_id),
                "sourceFactVersion": fact.source_fact_version,
                "sourceFactHash": fact.source_fact_hash,
            }
        )
    if (
        response.disposition == "CANONICAL_OUTCOME_APPLIED"
        and fact is not None
        and fact.outcome_status == "OUTCOME_UNKNOWN"
    ):
        return DriverExecutionResult(
            DriverExecutionDisposition.FAILED_CONFIRMED,
            "TOOL_OUTCOME_UNKNOWN",
            "EXTERNAL_OUTCOME_UNKNOWN",
            FrozenJsonObject(payload),
        )
    return DriverExecutionResult(
        _nonterminal_disposition(response.action),
        None,
        None,
        FrozenJsonObject(payload),
    )


def _nonterminal_disposition(action: str) -> DriverExecutionDisposition:
    if action in {
        "QUERY_EXACT_JAVA",
        "QUERY_EXACT_ARM_AND_JAVA",
        "QUERY_RECEIPT_HISTORY",
        "REDELIVER_SAME_CANONICAL_FACT",
        "WAIT_FOR_GOVERNED_TOOL_CHAIN",
    }:
        return DriverExecutionDisposition.CONVERGENCE_PENDING
    return DriverExecutionDisposition.FENCED


def _gateway_outcome_unknown_result(
    operation: str,
    code: str,
    action: str,
    permit_id: object,
) -> DriverExecutionResult:
    return DriverExecutionResult(
        _nonterminal_disposition(action),
        None,
        None,
        FrozenJsonObject(
            {
                "schemaVersion": "governed-gateway-outcome-unknown-v1",
                "operation": operation,
                "code": code,
                "action": action,
                "persistedPermitId": str(permit_id),
            }
        ),
    )


def _gateway_rejected_result(
    operation: str,
    code: str,
    action: str,
    permit_id: object,
) -> DriverExecutionResult:
    return DriverExecutionResult(
        _nonterminal_disposition(action),
        None,
        None,
        FrozenJsonObject(
            {
                "schemaVersion": "governed-gateway-rejected-v1",
                "operation": operation,
                "code": code,
                "action": action,
                "persistedPermitId": str(permit_id),
            }
        ),
    )


def _permit_issue_outcome_unknown_result(
    operation: str,
    code: str,
    intent_id: UUID,
) -> DriverExecutionResult:
    return DriverExecutionResult(
        DriverExecutionDisposition.CONVERGENCE_PENDING,
        None,
        None,
        FrozenJsonObject(
            {
                "schemaVersion": "governed-permit-issue-convergence-v1",
                "operation": operation,
                "code": code,
                "action": f"REISSUE_EXACT_{operation}_PERMIT",
                "intentId": str(intent_id),
            }
        ),
    )


def _evidence_fenced_result(code: str, permit_id: object) -> DriverExecutionResult:
    return DriverExecutionResult(
        DriverExecutionDisposition.FENCED,
        None,
        None,
        FrozenJsonObject(
            {
                "schemaVersion": "governed-driver-fence-v1",
                "code": code,
                "persistedPermitId": str(permit_id),
            }
        ),
    )


def _tool_intent(
    initial: GovernedInitialModelIntent,
    selection_id: UUID,
    execution_id: UUID,
) -> GovernedToolIntent:
    return GovernedToolIntent.model_validate(
        {
            "contractVersion": "1.2",
            "selectionMode": "MODEL_SELECTED",
            "toolInvocationId": stable_tool_call_id(execution_id),
            "sourceModelCallId": initial.model_call_id,
            "executionGeneration": initial.execution_generation,
            "admissionSnapshotId": initial.admission_snapshot_id,
            "toolPolicySnapshotId": initial.tool_policy_snapshot_id,
            "modelToolSelectionId": selection_id,
            "toolCallSlot": 1,
            "idempotencyKey": f"h12:{execution_id}:tool:1",
        },
        strict=True,
    )


def _after_tool_intent(
    initial: GovernedInitialModelIntent,
    execution_id: UUID,
) -> GovernedAfterToolModelIntent:
    return GovernedAfterToolModelIntent.model_validate(
        {
            **initial.model_dump(mode="python", by_alias=True),
            "modelCallId": stable_model_call_id(execution_id, 2),
            "callIndex": 2,
            "callPhase": "AFTER_TOOL",
            "idempotencyKey": f"h12:{execution_id}:model:2",
        },
        strict=True,
    )


def _event_payload(
    response: GovernedInitialModelCallResponse,
) -> FrozenJsonObject:
    fact = response.canonical_fact
    payload: dict[str, object] = {
        "schemaVersion": "governed-initial-driver-event-v1",
        "modelCallId": str(response.model_call_id),
        "requestHash": response.request_hash,
        "disposition": response.disposition,
        "persistedPermitId": str(
            response.persisted_dispatch.runtime_external_permit_id
        ),
    }
    if fact is not None:
        payload.update(
            {
                "outcomeStatus": fact.outcome_status,
                "sourceFactId": str(fact.source_fact_id),
                "sourceFactVersion": fact.source_fact_version,
                "sourceFactHash": fact.source_fact_hash,
            }
        )
    return FrozenJsonObject(payload)


def _driver_code(value: str | None, fallback: str) -> str:
    if value is None or len(value) > 64:
        return fallback
    return value

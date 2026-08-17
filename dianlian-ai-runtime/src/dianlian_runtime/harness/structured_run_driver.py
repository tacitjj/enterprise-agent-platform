from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from dianlian_runtime.harness.admission_manifest import (
    AdmissionManifestFailedSafe,
    AdmissionManifestOutcomeUnknown,
    JavaAdmissionManifestClient,
)
from dianlian_runtime.harness.structured_admission_manifest import (
    JavaCapabilityStructuredAdmissionManifest,
)
from dianlian_runtime.harness.structured_model_gateway import (
    StructuredModelCallResponse,
    StructuredModelGatewayClient,
    StructuredModelGatewayFailure,
)
from dianlian_runtime.harness.structured_model_receipt import (
    StructuredModelRequestReceipt,
    stable_structured_model_call_id,
    structured_model_request_hash,
)
from dianlian_runtime.supervisor.admission_permit_issuer import (
    AdmissionPermitDisposition,
    AdmissionPermitFenceRequired,
    AdmissionPermitOutcomeUnknown,
    DormantAdmissionPermitIssuer,
    IssueAdmissionPermitRequest,
)
from dianlian_runtime.supervisor.contracts import FrozenJsonObject, RuntimeSourceKind
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
    ModelPermitFenceRequired,
    ModelPermitOutcomeUnknown,
)
from dianlian_runtime.supervisor.structured_checkpoint_store import (
    PostgresStructuredCheckpointStore,
    RuntimeStructuredCheckpointFact,
    RuntimeStructuredCheckpointRejected,
    RuntimeStructuredState,
)


Offload = Callable[[Callable[[], object]], Awaitable[object]]


class StructuredRunExecutionDriver:
    """默认休眠的 3.0 OneCall Driver；不包含任何具体角色业务流程。"""

    def __init__(
        self,
        *,
        checkpoint_store: PostgresStructuredCheckpointStore,
        admission_permit_issuer: DormantAdmissionPermitIssuer,
        admission_manifest_client: JavaAdmissionManifestClient,
        model_permit_issuer: DormantModelPermitIssuer,
        model_gateway: StructuredModelGatewayClient,
        permit_ttl_seconds: int = 30,
        offload: Offload | None = None,
    ) -> None:
        for value, method in (
            (checkpoint_store, "load"),
            (admission_permit_issuer, "issue"),
            (admission_manifest_client, "resolve"),
            (model_permit_issuer, "issue"),
            (model_gateway, "invoke"),
        ):
            if not callable(getattr(value, method, None)):
                raise TypeError("structured Driver dependency is invalid")
        if isinstance(permit_ttl_seconds, bool) or not 1 <= permit_ttl_seconds <= 60:
            raise ValueError("permit_ttl_seconds is outside its allowed range")
        if offload is not None and not callable(offload):
            raise TypeError("offload must be callable")
        self._checkpoint_store = checkpoint_store
        self._admission_permit_issuer = admission_permit_issuer
        self._admission_manifest_client = admission_manifest_client
        self._model_permit_issuer = model_permit_issuer
        self._model_gateway = model_gateway
        self._permit_ttl_seconds = permit_ttl_seconds
        self._offload = offload or asyncio.to_thread
        self._execution_lock = asyncio.Lock()
        self._started = False
        self._closed = False

    @property
    def ready(self) -> bool:
        return self._started and not self._closed

    async def start(self) -> None:
        if self._started or self._closed:
            raise RuntimeError("structured Driver cannot be started in this state")
        await self._checkpoint_store.verify_capability()
        self._started = True

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._admission_manifest_client.aclose()
        await self._model_gateway.aclose()

    async def execute(
        self,
        request: DriverExecutionRequest,
        *,
        gate: DriverFenceGate,
        checkpoints: DriverCheckpointSink,
    ) -> DriverExecutionResult:
        del checkpoints
        if not self.ready:
            raise RuntimeError("structured Driver is not ready")
        _require_structured_execution(request)
        if gate.revoked:
            raise DriverFenceRevoked("runtime execution fence is revoked")
        async with self._execution_lock:
            fact = await self._checkpoint_store.load(request.fence)
            if fact is None:
                resolved = await self._resolve_manifest(request, gate)
                if isinstance(resolved, DriverExecutionResult):
                    return resolved
                state = RuntimeStructuredState(resolved)
                try:
                    fact = await self._checkpoint_store.save(
                        request.fence,
                        expected=None,
                        transition_code="MANIFEST_RESOLVED",
                        state=state,
                    )
                except RuntimeStructuredCheckpointRejected as exception:
                    raise DriverFenceRevoked(
                        "structured Manifest checkpoint was not applied"
                    ) from exception
            state = RuntimeStructuredState.from_fact(fact)
            _require_manifest_matches_execution(state.admission_manifest, request)
            return await self._invoke_model(request, gate, fact, state)

    async def quiesce_locally(self, fence: DriverFence) -> LocalQuiesceResult:
        if not isinstance(fence, DriverFence):
            raise TypeError("fence must be a DriverFence")
        return LocalQuiesceResult(LocalQuiesceDisposition.QUIESCED)

    async def _resolve_manifest(
        self,
        request: DriverExecutionRequest,
        gate: DriverFenceGate,
    ) -> JavaCapabilityStructuredAdmissionManifest | DriverExecutionResult:
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
            return _pending("ADMISSION_PERMIT_OUTCOME_UNKNOWN", exception.code)
        except AdmissionPermitFenceRequired as exception:
            raise DriverFenceRevoked("admission permit fence is uncertain") from exception
        if issued.disposition == AdmissionPermitDisposition.HISTORICAL_CONSUMED:
            return _pending(
                "ADMISSION_MANIFEST_RECOVERY_REQUIRED",
                "ADMISSION_PERMIT_HISTORICAL_CONSUMED",
            )
        try:
            manifest = await self._admission_manifest_client.resolve(
                request,
                issued.permit,
                gate=gate,
            )
        except AdmissionManifestFailedSafe as exception:
            return _failed("ADMISSION_MANIFEST_REJECTED", exception.code)
        except AdmissionManifestOutcomeUnknown as exception:
            return _pending("ADMISSION_MANIFEST_OUTCOME_UNKNOWN", exception.code)
        if not isinstance(manifest, JavaCapabilityStructuredAdmissionManifest):
            raise DriverFenceRevoked("structured Admission response type drifted")
        return manifest

    async def _invoke_model(
        self,
        request: DriverExecutionRequest,
        gate: DriverFenceGate,
        fact: RuntimeStructuredCheckpointFact,
        state: RuntimeStructuredState,
    ) -> DriverExecutionResult:
        manifest = state.admission_manifest
        model_call_id = stable_structured_model_call_id(manifest.runtime_run_id)
        request_hash = structured_model_request_hash(
            manifest.runtime_run_id,
            manifest.admission_snapshot_id,
            manifest.admission_snapshot_hash,
        )
        receipt = state.find_current_receipt(
            request.fence,
            model_call_id=model_call_id,
            model_request_hash=request_hash,
        )
        if receipt is None:
            await gate.authorize_execution()
            try:
                issued = await self._offload(
                    lambda: self._model_permit_issuer.issue(
                        IssueModelPermitRequest(
                            request.authority,
                            request.fence,
                            model_call_id,
                            request_hash,
                            self._permit_ttl_seconds,
                        )
                    )
                )
            except ModelPermitOutcomeUnknown as exception:
                return _pending("MODEL_PERMIT_OUTCOME_UNKNOWN", exception.code)
            except ModelPermitFenceRequired as exception:
                raise DriverFenceRevoked(
                    "model permit fence is uncertain"
                ) from exception
            if not issued.provider_dispatch_allowed:
                return _pending(
                    "MODEL_RECEIPT_HISTORY_REQUIRED",
                    "MODEL_PERMIT_HISTORICAL_CONSUMED",
                )
            receipt = StructuredModelRequestReceipt.create(
                manifest.runtime_run_id,
                manifest,
                issued.receipt,
            )
            advanced = state.append_receipt(receipt)
            try:
                fact = await self._checkpoint_store.save(
                    request.fence,
                    expected=fact,
                    transition_code="MODEL_RECEIPT_APPENDED",
                    state=advanced,
                )
            except RuntimeStructuredCheckpointRejected as exception:
                raise DriverFenceRevoked(
                    "structured receipt checkpoint was not applied"
                ) from exception
            state = RuntimeStructuredState.from_fact(fact)
            receipt = state.find_receipt(issued.receipt.runtime_external_permit_id)
            if receipt is None:
                raise DriverFenceRevoked("structured receipt checkpoint drifted")

        # checkpoint 已提交后才允许执行 Java POST；当前 fence 仍需逐次实时回验。
        await gate.authorize_execution()
        try:
            response = await self._model_gateway.invoke(receipt)
        except StructuredModelGatewayFailure as exception:
            return _pending("STRUCTURED_MODEL_CONVERGENCE_REQUIRED", exception.code)
        return await _map_response(response, gate)


async def _map_response(
    response: StructuredModelCallResponse,
    gate: DriverFenceGate,
) -> DriverExecutionResult:
    payload = {
        "schemaVersion": "structured-model-driver-result-v1",
        "modelCallId": str(response.model_call_id),
        "modelRequestHash": response.model_request_hash,
        "persistedPermitId": str(
            response.persisted_dispatch.runtime_external_permit_id
        ),
        "attemptedPermitId": str(
            response.attempted_dispatch.runtime_external_permit_id
        ),
        "disposition": response.disposition,
        "action": response.action,
    }
    if response.canonical_fact is not None:
        payload["canonicalFact"] = response.canonical_fact.model_dump(
            mode="json",
            by_alias=True,
        )
    if response.candidate_receipt is not None:
        payload["candidateReceipt"] = response.candidate_receipt.model_dump(
            mode="json",
            by_alias=True,
        )

    if response.disposition == "CANDIDATE_PROJECTED":
        await gate.authorize_execution()
        return DriverExecutionResult(
            DriverExecutionDisposition.COMPLETED,
            "STRUCTURED_CANDIDATE_PROJECTED",
            None,
            FrozenJsonObject(payload),
        )
    if response.disposition == "CANONICAL_OUTCOME_APPLIED":
        canonical = response.canonical_fact
        assert canonical is not None
        if canonical.outcome_status in {"FAILED_CONFIRMED", "NOT_DISPATCHED"}:
            await gate.authorize_execution()
            return DriverExecutionResult(
                DriverExecutionDisposition.FAILED_CONFIRMED,
                "STRUCTURED_MODEL_FAILED_CONFIRMED",
                canonical.outcome_code,
                FrozenJsonObject(payload),
            )
    return DriverExecutionResult(
        DriverExecutionDisposition.CONVERGENCE_PENDING,
        None,
        None,
        FrozenJsonObject(payload),
    )


def _require_structured_execution(request: DriverExecutionRequest) -> None:
    if not isinstance(request, DriverExecutionRequest):
        raise TypeError("request must be a DriverExecutionRequest")
    authority = request.authority
    if (
        authority.admission_contract_version != "3.0"
        or authority.runtime_type != "JAVA_CAPABILITY_STRUCTURED"
        or authority.source_kind != RuntimeSourceKind.TASK_STEP
    ):
        raise ValueError("structured Driver requires exact TASK_STEP / 3.0 authority")


def _require_manifest_matches_execution(
    manifest: JavaCapabilityStructuredAdmissionManifest,
    request: DriverExecutionRequest,
) -> None:
    authority = request.authority
    if (
        manifest.tenant_id != authority.tenant_id
        or manifest.runtime_run_id != authority.runtime_run_id
        or manifest.task_id != authority.task_run_id
        or manifest.task_step_id != authority.task_step_id
        or manifest.execution_generation != authority.task_execution_generation
        or manifest.actor_user_id != authority.user_id
        or manifest.admission_snapshot_id != authority.admission_snapshot_id
        or manifest.admission_snapshot_hash != authority.admission_snapshot_hash
        or manifest.request_hash != authority.request_hash
        or manifest.idempotency_key != authority.idempotency_key
        or manifest.enterprise_agent_id != authority.agent_instance_id
        or manifest.point_reservation_id != authority.budget_reservation_id
    ):
        raise DriverFenceRevoked("structured Admission does not match Run authority")


def _pending(reason: str, code: str) -> DriverExecutionResult:
    return DriverExecutionResult(
        DriverExecutionDisposition.CONVERGENCE_PENDING,
        None,
        None,
        FrozenJsonObject(
            {
                "schemaVersion": "structured-model-driver-pending-v1",
                "reason": reason,
                "code": code,
                "providerRetryAllowed": False,
            }
        ),
    )


def _failed(reason: str, code: str) -> DriverExecutionResult:
    return DriverExecutionResult(
        DriverExecutionDisposition.FAILED_CONFIRMED,
        reason,
        code,
        FrozenJsonObject(
            {
                "schemaVersion": "structured-model-driver-failed-v1",
                "reason": reason,
                "code": code,
            }
        ),
    )

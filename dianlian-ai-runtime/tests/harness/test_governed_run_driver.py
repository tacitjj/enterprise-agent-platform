from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from uuid import UUID

from dianlian_runtime.harness.admission_manifest import (
    AdmissionManifestOutcomeUnknown,
    JavaAdmissionManifest,
)
from dianlian_runtime.harness.governed_model_gateway import (
    GovernedInitialModelCallResponse,
    GovernedModelGatewayOutcomeUnknown,
    GovernedModelGatewayRejected,
)
from dianlian_runtime.harness.governed_model_intent import (
    build_governed_initial_model_intent,
)
from dianlian_runtime.harness.governed_model_receipt import (
    GovernedAfterToolModelRequestReceipt,
    GovernedInitialModelRequestReceipt,
)
from dianlian_runtime.harness.governed_tool_gateway import (
    GovernedToolCallResponse,
    GovernedToolGatewayRejected,
)
from dianlian_runtime.harness.governed_tool_receipt import (
    GovernedToolRequestReceipt,
)
from dianlian_runtime.harness.governed_run_driver import (
    GovernedInitialRunExecutionDriver,
)
from dianlian_runtime.harness.postgres_governed_h12_slots import (
    PostgresGovernedH12SlotsFactory,
)
from dianlian_runtime.harness.h12_durable import (
    H12DurableSlots,
    LocalIntentState,
    ModelOutcome,
    ModelPhase,
    canonical_intent,
    stable_model_call_id,
    stable_model_tool_selection_id,
)
from dianlian_runtime.supervisor.admission_permit_issuer import (
    AdmissionPermitDisposition,
    AdmissionPermitIssueResult,
)
from dianlian_runtime.supervisor.contracts import (
    ExternalOperation,
    ExternalPermitStatus,
    MultitaskStrategy,
    OperationKind,
    RuntimeExecutionAuthorityFact,
    RuntimeExternalPermitFact,
    PrimitiveOutcome,
    PrimitiveResult,
    RuntimeH12CheckpointFact,
)
from dianlian_runtime.supervisor.driver import (
    DriverExecutionDisposition,
    DriverExecutionRequest,
    DriverFence,
)
from dianlian_runtime.supervisor.model_permit_issuer import (
    ModelPermitDisposition,
    ModelPermitIssueResult,
    ModelPermitOutcomeUnknown,
    ModelPermitReceipt,
)
from dianlian_runtime.supervisor.h12_checkpoint_store import (
    PostgresH12CheckpointStore,
)
from dianlian_runtime.supervisor.tool_permit_issuer import (
    ToolPermitDisposition,
    ToolPermitIssueResult,
    ToolPermitReceipt,
)


RUN_ID = UUID("72000000-0000-4000-8000-000000000001")
TENANT_ID = UUID("72000000-0000-4000-8000-000000000002")
THREAD_ID = UUID("72000000-0000-4000-8000-000000000003")
TASK_ID = UUID("72000000-0000-4000-8000-000000000004")
STEP_ID = UUID("72000000-0000-4000-8000-000000000005")
ADMISSION_ID = UUID("72000000-0000-4000-8000-000000000006")
ADMISSION_HASH = "a" * 64
NOW = datetime(2026, 8, 14, tzinfo=UTC)
POLICY_HASH = "6cf57e7fa121d4edaeb1c379df87fb5ae08e693d40c1639d3fad8ae964c9b66c"


class RecordingGate:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    @property
    def revoked(self) -> bool:
        return False

    async def authorize_execution(self) -> None:
        self.events.append("gate")


class UnusedCheckpoints:
    async def register(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("INITIAL-only Driver must not register a checkpoint")


class AdmissionIssuer:
    def __init__(
        self,
        events: list[str],
        permit: RuntimeExternalPermitFact,
        *,
        disposition: AdmissionPermitDisposition = (
            AdmissionPermitDisposition.CURRENT_ISSUED
        ),
    ) -> None:
        self.events = events
        self.permit = permit
        self.disposition = disposition

    def issue(self, request: object) -> AdmissionPermitIssueResult:
        del request
        self.events.append("admission-issue")
        return AdmissionPermitIssueResult(
            self.disposition,
            self.permit,
            self.disposition != AdmissionPermitDisposition.HISTORICAL_CONSUMED,
        )


class AdmissionClient:
    def __init__(
        self,
        events: list[str],
        manifest: JavaAdmissionManifest,
        *,
        outcome_unknown: bool = False,
    ) -> None:
        self.events = events
        self.manifest = manifest
        self.outcome_unknown = outcome_unknown

    async def resolve(
        self,
        execution: object,
        permit: object,
        *,
        gate: RecordingGate,
    ) -> JavaAdmissionManifest:
        del execution, permit
        self.events.append("manifest")
        await gate.authorize_execution()
        await gate.authorize_execution()
        if self.outcome_unknown:
            raise AdmissionManifestOutcomeUnknown(
                "ADMISSION_MANIFEST_OUTCOME_UNKNOWN"
            )
        return self.manifest

    async def aclose(self) -> None:
        return None


class ModelIssuer:
    def __init__(
        self,
        events: list[str],
        *,
        historical: ModelPermitReceipt | None = None,
        outcome_unknown: bool = False,
    ) -> None:
        self.events = events
        self.historical = historical
        self.outcome_unknown = outcome_unknown
        self.calls = 0

    def issue(self, request: object) -> ModelPermitIssueResult:
        self.events.append("model-issue")
        if self.outcome_unknown:
            raise ModelPermitOutcomeUnknown()
        if self.historical is not None:
            return ModelPermitIssueResult(
                ModelPermitDisposition.HISTORICAL_CONSUMED,
                self.historical,
                False,
            )
        self.calls += 1
        suffix = self.calls * 10
        receipt = ModelPermitReceipt(
            tenant_id=request.authority.tenant_id,
            runtime_external_permit_id=UUID(
                f"72000000-0000-4000-8000-{101 + suffix:012d}"
            ),
            runtime_run_id=request.authority.runtime_run_id,
            task_execution_generation=request.authority.task_execution_generation,
            lease_owner=request.authority.lease_owner,
            lease_epoch=request.authority.lease_epoch,
            admission_snapshot_id=request.authority.admission_snapshot_id,
            admission_snapshot_hash=request.authority.admission_snapshot_hash,
            operation_kind=ExternalOperation.MODEL_INVOKE,
            intent_id=request.intent_id,
            request_hash=request.request_hash,
            issue_event_id=UUID(
                f"72000000-0000-4000-8000-{102 + suffix:012d}"
            ),
            arm_event_id=UUID(
                f"72000000-0000-4000-8000-{103 + suffix:012d}"
            ),
            permit_attempt=self.calls,
            issued_at=NOW,
            expires_at=NOW + timedelta(seconds=30),
        )
        return ModelPermitIssueResult(
            ModelPermitDisposition.CURRENT_ISSUED,
            receipt,
            True,
        )


class ModelGateway:
    def __init__(
        self,
        events: list[str],
        *,
        pending: bool = False,
        tool_chain: bool = False,
        outcome_unknown: bool = False,
        rejected_action: str | None = None,
        canonical_outcome_unknown: bool = False,
    ) -> None:
        self.events = events
        self.pending = pending
        self.tool_chain = tool_chain
        self.outcome_unknown = outcome_unknown
        self.rejected_action = rejected_action
        self.canonical_outcome_unknown = canonical_outcome_unknown

    async def invoke_initial(
        self,
        receipt: GovernedInitialModelRequestReceipt,
    ) -> GovernedInitialModelCallResponse:
        self.events.append("gateway")
        if self.outcome_unknown:
            raise GovernedModelGatewayOutcomeUnknown(
                "GOVERNED_MODEL_GATEWAY_OUTCOME_UNKNOWN",
                "QUERY_EXACT_ARM_AND_JAVA",
            )
        if self.rejected_action is not None:
            raise GovernedModelGatewayRejected(
                "RUNTIME_GOVERNED_MODEL_CALL_CONFLICT",
                self.rejected_action,
            )
        if self.canonical_outcome_unknown:
            return _response(
                receipt,
                pending=False,
                canonical_outcome_unknown=True,
            )
        if self.tool_chain:
            return _tool_required_response(receipt)
        return _response(receipt, pending=self.pending)

    async def invoke_after_tool(
        self,
        receipt: GovernedAfterToolModelRequestReceipt,
    ) -> GovernedInitialModelCallResponse:
        self.events.append("gateway-after-tool")
        return _response(receipt, pending=False)

    async def aclose(self) -> None:
        return None


class ToolIssuer:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def issue(self, request: object) -> ToolPermitIssueResult:
        self.events.append("tool-issue")
        return ToolPermitIssueResult(
            ToolPermitDisposition.CURRENT_ISSUED,
            ToolPermitReceipt(
                tenant_id=request.authority.tenant_id,
                runtime_external_permit_id=UUID(
                    "72000000-0000-4000-8000-000000000201"
                ),
                runtime_run_id=request.authority.runtime_run_id,
                task_execution_generation=request.authority.task_execution_generation,
                lease_owner=request.authority.lease_owner,
                lease_epoch=request.authority.lease_epoch,
                admission_snapshot_id=request.authority.admission_snapshot_id,
                admission_snapshot_hash=request.authority.admission_snapshot_hash,
                operation_kind=ExternalOperation.TOOL_INVOKE,
                intent_id=request.intent_id,
                request_hash=request.request_hash,
                issue_event_id=UUID(
                    "72000000-0000-4000-8000-000000000202"
                ),
                arm_event_id=UUID(
                    "72000000-0000-4000-8000-000000000203"
                ),
                permit_attempt=1,
                issued_at=NOW,
                expires_at=NOW + timedelta(seconds=30),
            ),
            True,
        )


class ToolGateway:
    def __init__(
        self,
        events: list[str],
        *,
        pending: bool = False,
        rejected_action: str | None = None,
        canonical_outcome_unknown: bool = False,
    ) -> None:
        self.events = events
        self.pending = pending
        self.rejected_action = rejected_action
        self.canonical_outcome_unknown = canonical_outcome_unknown

    async def invoke(
        self,
        receipt: GovernedToolRequestReceipt,
    ) -> GovernedToolCallResponse:
        self.events.append("tool-gateway")
        if self.rejected_action is not None:
            raise GovernedToolGatewayRejected(
                "RUNTIME_GOVERNED_TOOL_CALL_CONFLICT",
                self.rejected_action,
            )
        return _tool_response(
            receipt,
            pending=self.pending,
            canonical_outcome_unknown=self.canonical_outcome_unknown,
        )

    async def aclose(self) -> None:
        return None


class CheckpointRepository:
    def __init__(self) -> None:
        self.current: RuntimeH12CheckpointFact | None = None

    def check_h12_checkpoint_capability(self) -> PrimitiveResult:
        return PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, True)

    def load_h12_checkpoint(self, request: object) -> PrimitiveResult:
        del request
        if self.current is None:
            return PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None)
        return PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, self.current)

    def save_h12_checkpoint(self, request: object) -> PrimitiveResult:
        expected_id = self.current.checkpoint_id if self.current is not None else None
        expected_version = self.current.state_version if self.current is not None else 0
        assert request.expected_checkpoint_id == expected_id
        assert request.expected_state_version == expected_version
        self.current = RuntimeH12CheckpointFact(
            tenant_id=request.tenant_id,
            runtime_run_id=request.runtime_run_id,
            task_execution_generation=request.task_execution_generation,
            checkpoint_id=request.checkpoint_id,
            previous_checkpoint_id=request.expected_checkpoint_id,
            state_version=request.expected_state_version + 1,
            state=request.state,
            state_hash="f" * 64,
            transition_code=request.transition_code,
            event_id=request.event_id,
            created_by=request.lease_owner,
            lease_epoch=request.lease_epoch,
            created_at=NOW,
        )
        return PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, self.current)


async def direct_offload(operation: Callable[[], object]) -> object:
    return operation()


def test_current_receipt_runs_in_gate_order_and_releases_only_applied_result(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        events: list[str] = []
        request = _execution_request(lease_epoch=1)
        driver = _driver(tmp_path, request, events)
        await driver.start()
        try:
            result = await driver.execute(
                request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await driver.close()

        assert result.disposition == DriverExecutionDisposition.COMPLETED
        assert result.event_payload.to_builtin()["outcomeStatus"] == "SUCCEEDED"
        assert events == [
            "gate",
            "admission-issue",
            "manifest",
            "gate",
            "gate",
            "gate",
            "model-issue",
            "gate",
            "gate",
            "gateway",
            "gate",
        ]
        async with H12DurableSlots(tmp_path / f"{RUN_ID}.db") as slots:
            intent = await slots.require_model_intent(RUN_ID, 1)
            assert intent.local_state == LocalIntentState.TERMINAL
            assert intent.response_payload is not None
            assert intent.response_payload["assistantText"] == "answer"

        recovery_events: list[str] = []
        recovered = _driver(tmp_path, request, recovery_events)
        await recovered.start()
        try:
            replay = await recovered.execute(
                request,
                gate=RecordingGate(recovery_events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await recovered.close()
        assert replay.disposition == DriverExecutionDisposition.COMPLETED
        assert recovery_events == ["gate"]

    asyncio.run(verify())


def test_driver_uses_an_injected_governed_slots_factory(tmp_path: Path) -> None:
    async def verify() -> None:
        events: list[str] = []
        opened_for: list[DriverFence] = []
        request = _execution_request(lease_epoch=1)

        def slots_factory(fence: DriverFence) -> H12DurableSlots:
            opened_for.append(fence)
            return H12DurableSlots(tmp_path / "injected-governed.db")

        driver = GovernedInitialRunExecutionDriver(
            slots_factory=slots_factory,
            admission_permit_issuer=AdmissionIssuer(
                events,
                _admission_permit(request),
            ),
            admission_manifest_client=AdmissionClient(events, _manifest()),
            model_permit_issuer=ModelIssuer(events),
            model_gateway=ModelGateway(events),
            offload=direct_offload,
        )
        await driver.start()
        try:
            result = await driver.execute(
                request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await driver.close()

        assert result.disposition == DriverExecutionDisposition.COMPLETED
        assert opened_for == [request.fence]
        assert (tmp_path / "injected-governed.db").is_file()

    asyncio.run(verify())


def test_postgres_checkpoint_slots_cover_the_complete_governed_h12_chain() -> None:
    async def verify() -> None:
        events: list[str] = []
        request = _execution_request(lease_epoch=1)
        repository = CheckpointRepository()
        slots_factory = PostgresGovernedH12SlotsFactory(
            PostgresH12CheckpointStore(repository)
        )
        driver = GovernedInitialRunExecutionDriver(
            slots_factory=slots_factory,
            admission_permit_issuer=AdmissionIssuer(
                events,
                _admission_permit(request),
            ),
            admission_manifest_client=AdmissionClient(events, _manifest()),
            model_permit_issuer=ModelIssuer(events),
            model_gateway=ModelGateway(events, tool_chain=True),
            tool_permit_issuer=ToolIssuer(events),
            tool_gateway=ToolGateway(events),
            offload=direct_offload,
        )
        await driver.start()
        try:
            result = await driver.execute(
                request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
            assert result.disposition == DriverExecutionDisposition.COMPLETED
            assert repository.current is not None
            async with slots_factory(request.fence) as slots:
                initial = await slots.load_governed_initial_terminal_evidence(RUN_ID)
                tool = await slots.load_governed_tool_terminal_evidence(RUN_ID)
                after_tool = await slots.load_governed_after_tool_terminal_evidence(
                    RUN_ID
                )
        finally:
            await driver.close()

        assert initial is not None
        assert initial.outcome_kind == ModelOutcome.TOOL_SELECTION
        assert tool is not None and tool.outcome_status == "SUCCEEDED"
        assert after_tool is not None
        assert after_tool.response_payload["assistantText"] == "answer"

    asyncio.run(verify())


def test_historical_admission_without_intent_fails_without_external_dispatch(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        events: list[str] = []
        current_request = _execution_request(lease_epoch=2)
        old_request = _execution_request(lease_epoch=1)
        driver = GovernedInitialRunExecutionDriver(
            data_dir=tmp_path,
            admission_permit_issuer=AdmissionIssuer(
                events,
                _admission_permit(old_request),
                disposition=AdmissionPermitDisposition.HISTORICAL_CONSUMED,
            ),
            admission_manifest_client=AdmissionClient(events, _manifest()),
            model_permit_issuer=ModelIssuer(events),
            model_gateway=ModelGateway(events),
            offload=direct_offload,
        )
        await driver.start()
        try:
            result = await driver.execute(
                current_request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await driver.close()

        assert result.disposition == DriverExecutionDisposition.FAILED_CONFIRMED
        assert result.terminal_reason == "ADMISSION_MANIFEST_UNRECOVERABLE"
        assert result.failure_code == "ADMISSION_PERMIT_HISTORICAL_CONSUMED"
        assert result.event_payload.to_builtin()["operation"] == "ADMISSION_RESOLVE"
        assert events == ["gate", "admission-issue"]
        async with H12DurableSlots(tmp_path / f"{RUN_ID}.db") as slots:
            assert await slots.load_governed_initial_model_intent(RUN_ID) is None

    asyncio.run(verify())


def test_takeover_settles_an_old_bound_receipt_under_the_current_fence(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        old_request = _execution_request(lease_epoch=1)
        current_request = _execution_request(lease_epoch=2)
        manifest = _manifest()
        intent = build_governed_initial_model_intent(manifest)
        _, request_hash = canonical_intent(intent.durable_payload())
        old_permit = _model_receipt(old_request, intent.model_call_id, request_hash)
        old_receipt = GovernedInitialModelRequestReceipt.create(
            RUN_ID,
            intent,
            old_permit,
        )
        async with H12DurableSlots(tmp_path / f"{RUN_ID}.db") as slots:
            await slots.prepare_model(
                RUN_ID,
                1,
                ModelPhase.TOOL_DECISION,
                intent.durable_payload(),
            )
            await slots.persist_governed_initial_model_receipt(old_receipt)
            await slots.begin_governed_initial_model_dispatch(
                old_receipt,
                old_request.fence,
            )

        events: list[str] = []
        driver = GovernedInitialRunExecutionDriver(
            data_dir=tmp_path,
            admission_permit_issuer=AdmissionIssuer(
                events,
                _admission_permit(current_request),
            ),
            admission_manifest_client=AdmissionClient(events, manifest),
            model_permit_issuer=ModelIssuer(events, historical=old_permit),
            model_gateway=ModelGateway(events),
            offload=direct_offload,
        )
        await driver.start()
        try:
            result = await driver.execute(
                current_request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await driver.close()

        assert result.disposition == DriverExecutionDisposition.COMPLETED
        assert events == ["gate", "model-issue", "gate", "gateway", "gate"]
        async with H12DurableSlots(tmp_path / f"{RUN_ID}.db") as slots:
            terminal = await slots.require_model_intent(RUN_ID, 1)
            assert terminal.local_state == LocalIntentState.TERMINAL

    asyncio.run(verify())


def test_pending_java_state_keeps_the_local_slot_nonterminal(tmp_path: Path) -> None:
    async def verify() -> None:
        events: list[str] = []
        request = _execution_request(lease_epoch=1)
        driver = _driver(tmp_path, request, events, pending=True)
        await driver.start()
        try:
            result = await driver.execute(
                request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await driver.close()

        assert (
            result.disposition
            == DriverExecutionDisposition.CONVERGENCE_PENDING
        )
        async with H12DurableSlots(tmp_path / f"{RUN_ID}.db") as slots:
            intent = await slots.require_model_intent(RUN_ID, 1)
            assert intent.local_state == LocalIntentState.DISPATCHING
            assert intent.response_payload is None

    asyncio.run(verify())


def test_unknown_model_gateway_outcome_uses_exact_receipt_convergence(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        events: list[str] = []
        request = _execution_request(lease_epoch=1)
        driver = _driver(tmp_path, request, events, outcome_unknown=True)
        await driver.start()
        try:
            result = await driver.execute(
                request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await driver.close()

        assert (
            result.disposition
            == DriverExecutionDisposition.CONVERGENCE_PENDING
        )
        assert result.event_payload.to_builtin()["action"] == (
            "QUERY_EXACT_ARM_AND_JAVA"
        )
        async with H12DurableSlots(tmp_path / f"{RUN_ID}.db") as slots:
            intent = await slots.require_model_intent(RUN_ID, 1)
            assert intent.local_state == LocalIntentState.DISPATCHING
            assert intent.response_payload is None

    asyncio.run(verify())


def test_recoverable_model_rejection_keeps_the_exact_slot_nonterminal(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        events: list[str] = []
        request = _execution_request(lease_epoch=1)
        driver = _driver(
            tmp_path,
            request,
            events,
            model_rejected_action="QUERY_RECEIPT_HISTORY",
        )
        await driver.start()
        try:
            result = await driver.execute(
                request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await driver.close()

        assert result.disposition == DriverExecutionDisposition.CONVERGENCE_PENDING
        event = result.event_payload.to_builtin()
        assert event["code"] == "RUNTIME_GOVERNED_MODEL_CALL_CONFLICT"
        assert event["action"] == "QUERY_RECEIPT_HISTORY"
        async with H12DurableSlots(tmp_path / f"{RUN_ID}.db") as slots:
            intent = await slots.require_model_intent(RUN_ID, 1)
            assert intent.local_state == LocalIntentState.DISPATCHING
            assert intent.response_payload is None

    asyncio.run(verify())


def test_applied_model_outcome_unknown_terminates_run_without_releasing_slot(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        events: list[str] = []
        request = _execution_request(lease_epoch=1)
        driver = _driver(
            tmp_path,
            request,
            events,
            canonical_model_outcome_unknown=True,
        )
        await driver.start()
        try:
            result = await driver.execute(
                request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await driver.close()

        assert result.disposition == DriverExecutionDisposition.FAILED_CONFIRMED
        assert result.terminal_reason == "MODEL_OUTCOME_UNKNOWN"
        assert result.failure_code == "EXTERNAL_OUTCOME_UNKNOWN"
        assert result.event_payload.to_builtin()["outcomeStatus"] == (
            "OUTCOME_UNKNOWN"
        )
        async with H12DurableSlots(tmp_path / f"{RUN_ID}.db") as slots:
            intent = await slots.require_model_intent(RUN_ID, 1)
            assert intent.local_state == LocalIntentState.DISPATCHING
            assert intent.response_payload is None

    asyncio.run(verify())


def test_unknown_admission_manifest_outcome_keeps_the_same_run_recoverable(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        events: list[str] = []
        request = _execution_request(lease_epoch=1)
        driver = _driver(
            tmp_path,
            request,
            events,
            admission_outcome_unknown=True,
        )
        await driver.start()
        try:
            result = await driver.execute(
                request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await driver.close()

        assert (
            result.disposition
            == DriverExecutionDisposition.CONVERGENCE_PENDING
        )
        assert result.event_payload.to_builtin()["action"] == (
            "QUERY_EXACT_ADMISSION_MANIFEST"
        )
        async with H12DurableSlots(tmp_path / f"{RUN_ID}.db") as slots:
            assert await slots.load_governed_initial_model_intent(RUN_ID) is None

    asyncio.run(verify())


def test_unknown_model_permit_issue_retries_only_the_exact_stable_identity(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        events: list[str] = []
        request = _execution_request(lease_epoch=1)
        driver = _driver(
            tmp_path,
            request,
            events,
            model_permit_outcome_unknown=True,
        )
        await driver.start()
        try:
            result = await driver.execute(
                request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await driver.close()

        assert (
            result.disposition
            == DriverExecutionDisposition.CONVERGENCE_PENDING
        )
        event = result.event_payload.to_builtin()
        assert event["action"] == "REISSUE_EXACT_MODEL_INVOKE_PERMIT"
        assert event["intentId"] == str(stable_model_call_id(RUN_ID, 1))
        async with H12DurableSlots(tmp_path / f"{RUN_ID}.db") as slots:
            intent = await slots.require_model_intent(RUN_ID, 1)
            assert intent.local_state == LocalIntentState.PREPARED

    asyncio.run(verify())


def test_governed_tool_and_after_tool_chain_releases_only_the_final_fact(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        events: list[str] = []
        request = _execution_request(lease_epoch=1)
        driver = _driver(tmp_path, request, events, tool_chain=True)
        await driver.start()
        try:
            result = await driver.execute(
                request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await driver.close()

        assert result.disposition == DriverExecutionDisposition.COMPLETED
        assert events.index("gateway") < events.index("tool-issue")
        assert events.index("tool-issue") < events.index("tool-gateway")
        assert events.index("tool-gateway") < events.index("gateway-after-tool")
        async with H12DurableSlots(tmp_path / f"{RUN_ID}.db") as slots:
            initial = await slots.load_governed_initial_terminal_evidence(RUN_ID)
            assert initial is not None
            assert initial.outcome_kind == ModelOutcome.TOOL_SELECTION
            assert initial.model_tool_selection_id == stable_model_tool_selection_id(
                initial.model_call_id
            )
            tool = await slots.load_governed_tool_terminal_evidence(RUN_ID)
            assert tool is not None
            assert tool.outcome_status == "SUCCEEDED"
            after_tool = await slots.load_governed_after_tool_terminal_evidence(
                RUN_ID
            )
            assert after_tool is not None
            assert after_tool.outcome_status == "SUCCEEDED"
            call_two = await slots.require_model_intent(RUN_ID, 2)
            assert call_two.local_state == LocalIntentState.TERMINAL
            assert call_two.response_payload is not None
            assert call_two.response_payload["assistantText"] == "answer"

    asyncio.run(verify())


def test_recoverable_tool_rejection_keeps_the_tool_chain_nonterminal(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        events: list[str] = []
        request = _execution_request(lease_epoch=1)
        driver = _driver(
            tmp_path,
            request,
            events,
            tool_chain=True,
            tool_rejected_action="QUERY_EXACT_JAVA",
        )
        await driver.start()
        try:
            result = await driver.execute(
                request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await driver.close()

        assert result.disposition == DriverExecutionDisposition.CONVERGENCE_PENDING
        event = result.event_payload.to_builtin()
        assert event["code"] == "RUNTIME_GOVERNED_TOOL_CALL_CONFLICT"
        assert event["action"] == "QUERY_EXACT_JAVA"
        assert "gateway-after-tool" not in events
        async with H12DurableSlots(tmp_path / f"{RUN_ID}.db") as slots:
            assert await slots.load_governed_tool_terminal_evidence(RUN_ID) is None
            assert await slots.load_governed_after_tool_terminal_evidence(RUN_ID) is None

    asyncio.run(verify())


def test_applied_tool_outcome_unknown_terminates_run_without_after_tool(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        events: list[str] = []
        request = _execution_request(lease_epoch=1)
        driver = _driver(
            tmp_path,
            request,
            events,
            tool_chain=True,
            canonical_tool_outcome_unknown=True,
        )
        await driver.start()
        try:
            result = await driver.execute(
                request,
                gate=RecordingGate(events),
                checkpoints=UnusedCheckpoints(),
            )
        finally:
            await driver.close()

        assert result.disposition == DriverExecutionDisposition.FAILED_CONFIRMED
        assert result.terminal_reason == "TOOL_OUTCOME_UNKNOWN"
        assert result.failure_code == "EXTERNAL_OUTCOME_UNKNOWN"
        assert result.event_payload.to_builtin()["outcomeStatus"] == (
            "OUTCOME_UNKNOWN"
        )
        assert "gateway-after-tool" not in events
        async with H12DurableSlots(tmp_path / f"{RUN_ID}.db") as slots:
            assert await slots.load_governed_tool_terminal_evidence(RUN_ID) is None
            assert await slots.load_governed_after_tool_terminal_evidence(RUN_ID) is None

    asyncio.run(verify())


def _driver(
    data_dir: Path,
    request: DriverExecutionRequest,
    events: list[str],
    *,
    pending: bool = False,
    tool_chain: bool = False,
    outcome_unknown: bool = False,
    model_rejected_action: str | None = None,
    canonical_model_outcome_unknown: bool = False,
    canonical_tool_outcome_unknown: bool = False,
    tool_rejected_action: str | None = None,
    admission_outcome_unknown: bool = False,
    model_permit_outcome_unknown: bool = False,
) -> GovernedInitialRunExecutionDriver:
    return GovernedInitialRunExecutionDriver(
        data_dir=data_dir,
        admission_permit_issuer=AdmissionIssuer(
            events,
            _admission_permit(request),
        ),
        admission_manifest_client=AdmissionClient(
            events,
            _manifest(),
            outcome_unknown=admission_outcome_unknown,
        ),
        model_permit_issuer=ModelIssuer(
            events,
            outcome_unknown=model_permit_outcome_unknown,
        ),
        model_gateway=ModelGateway(
            events,
            pending=pending,
            tool_chain=tool_chain,
            outcome_unknown=outcome_unknown,
            rejected_action=model_rejected_action,
            canonical_outcome_unknown=canonical_model_outcome_unknown,
        ),
        tool_permit_issuer=ToolIssuer(events) if tool_chain else None,
        tool_gateway=(
            ToolGateway(
                events,
                rejected_action=tool_rejected_action,
                canonical_outcome_unknown=canonical_tool_outcome_unknown,
            )
            if tool_chain
            else None
        ),
        offload=direct_offload,
    )


def _execution_request(*, lease_epoch: int) -> DriverExecutionRequest:
    owner = f"worker-{lease_epoch}"
    authority = RuntimeExecutionAuthorityFact(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        runtime_thread_id=THREAD_ID,
        task_run_id=TASK_ID,
        task_step_id=STEP_ID,
        task_execution_generation=1,
        agent_instance_id=UUID("72000000-0000-4000-8000-000000000010"),
        user_id=UUID("72000000-0000-4000-8000-000000000011"),
        conversation_id=UUID("72000000-0000-4000-8000-000000000012"),
        source_message_id=None,
        runtime_thread_revision=1,
        runtime_type="DEERFLOW",
        runtime_agent_name="runtime-agent",
        capability_version_id=UUID("72000000-0000-4000-8000-000000000013"),
        prompt_version_id=UUID("72000000-0000-4000-8000-000000000014"),
        model_policy_id=UUID("72000000-0000-4000-8000-000000000015"),
        budget_reservation_id=UUID("72000000-0000-4000-8000-000000000016"),
        operation_kind=OperationKind.START,
        multitask_strategy=MultitaskStrategy.REJECT,
        request_hash="9" * 64,
        idempotency_key="governed-start",
        predecessor_runtime_run_id=None,
        expected_checkpoint_id=None,
        runtime_version="runtime-v1",
        agent_name="agent-v1",
        lease_owner=owner,
        lease_epoch=lease_epoch,
        admission_contract_version="2.2",
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=ADMISSION_HASH,
    )
    return DriverExecutionRequest(
        authority,
        DriverFence(
            tenant_id=TENANT_ID,
            runtime_run_id=RUN_ID,
            task_execution_generation=1,
            lease_owner=owner,
            lease_epoch=lease_epoch,
            admission_contract_version="2.2",
            admission_snapshot_id=ADMISSION_ID,
            admission_snapshot_hash=ADMISSION_HASH,
        ),
    )


def _admission_permit(request: DriverExecutionRequest) -> RuntimeExternalPermitFact:
    authority = request.authority
    return RuntimeExternalPermitFact(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=UUID(
            f"72000000-0000-4000-8000-{200 + authority.lease_epoch:012d}"
        ),
        runtime_run_id=RUN_ID,
        runtime_thread_id=THREAD_ID,
        task_step_id=STEP_ID,
        task_execution_generation=1,
        admission_contract_version="2.2",
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=ADMISSION_HASH,
        operation_kind=ExternalOperation.ADMISSION_RESOLVE,
        intent_id=ADMISSION_ID,
        request_hash=ADMISSION_HASH,
        lease_owner=authority.lease_owner,
        lease_epoch=authority.lease_epoch,
        permit_attempt=1,
        status=ExternalPermitStatus.ISSUED,
        requested_ttl_seconds=30,
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
        issue_event_id=UUID(
            f"72000000-0000-4000-8000-{300 + authority.lease_epoch:012d}"
        ),
        consume_event_id=None,
        consumed_by=None,
        consumed_at=None,
        updated_at=NOW,
    )


def _model_receipt(
    request: DriverExecutionRequest,
    intent_id: UUID,
    request_hash: str,
) -> ModelPermitReceipt:
    return ModelPermitReceipt(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=UUID("72000000-0000-4000-8000-000000000121"),
        runtime_run_id=RUN_ID,
        task_execution_generation=1,
        lease_owner=request.fence.lease_owner,
        lease_epoch=request.fence.lease_epoch,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=ADMISSION_HASH,
        operation_kind=ExternalOperation.MODEL_INVOKE,
        intent_id=intent_id,
        request_hash=request_hash,
        issue_event_id=UUID("72000000-0000-4000-8000-000000000122"),
        arm_event_id=UUID("72000000-0000-4000-8000-000000000123"),
        permit_attempt=1,
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )


def _manifest() -> JavaAdmissionManifest:
    payload = {
        "runtimeRunId": str(RUN_ID),
        "tenantId": str(TENANT_ID),
        "taskId": str(TASK_ID),
        "taskStepId": str(STEP_ID),
        "executionGeneration": 1,
        "admissionContractVersion": "2.2",
        "runtimeProfile": "DEERFLOW_H1_TEXT",
        "admissionSnapshotId": str(ADMISSION_ID),
        "admissionSnapshotHash": ADMISSION_HASH,
        "requestHash": "9" * 64,
        "idempotencyKey": "governed-start",
        "actorUserId": "72000000-0000-4000-8000-000000000011",
        "inputSnapshotId": "72000000-0000-4000-8000-000000000017",
        "enterpriseAgentId": "72000000-0000-4000-8000-000000000010",
        "agentVersionId": "72000000-0000-4000-8000-000000000019",
        "configurationVersionId": "72000000-0000-4000-8000-00000000001a",
        "pointReservationId": "72000000-0000-4000-8000-000000000016",
        "modelRoute": {
            "routeBindingId": "72000000-0000-4000-8000-00000000001c",
            "routeStateVersion": 1,
            "modelDefinitionId": "72000000-0000-4000-8000-00000000001d",
            "modelConfigurationVersion": 1,
            "reservationCeilingMicroCredit": 100000,
        },
        "prompt": {
            "promptSnapshotId": "72000000-0000-4000-8000-00000000001e",
            "hash": "2" * 64,
        },
        "context": {
            "contextSnapshotId": "72000000-0000-4000-8000-00000000001f",
            "hash": "3" * 64,
        },
        "toolPolicy": {
            "toolPolicySnapshotId": "72000000-0000-4000-8000-000000000021",
            "hash": "4" * 64,
        },
        "orchestrationPolicy": {
            "orchestrationPolicySnapshotId": "72000000-0000-4000-8000-000000000022",
            "maxModelCalls": 2,
            "maxToolCalls": 1,
            "modelCallReservationCeiling": 100000,
            "totalModelReservationCeiling": 200000,
            "hash": POLICY_HASH,
        },
    }
    return JavaAdmissionManifest.model_validate_json(
        json.dumps(payload, separators=(",", ":")),
        strict=True,
    )


def _response(
    receipt: (
        GovernedInitialModelRequestReceipt
        | GovernedAfterToolModelRequestReceipt
    ),
    *,
    pending: bool,
    canonical_outcome_unknown: bool = False,
) -> GovernedInitialModelCallResponse:
    arm = receipt.request.dispatch_arm
    dispatch = {
        "runtimeExternalPermitId": arm.runtime_external_permit_id,
        "leaseOwner": arm.lease_owner,
        "leaseEpoch": arm.lease_epoch,
        "armEventId": arm.arm_event_id,
    }
    payload = {
        "contractVersion": "1.2",
        "modelCallId": receipt.request.model_call_id,
        "requestHash": receipt.request.request_hash,
        "disposition": (
            "CANONICAL_OUTCOME_APPLIED"
            if canonical_outcome_unknown
            else (
                "CANONICAL_OUTCOME_PENDING"
                if pending
                else "CANONICAL_OUTCOME_APPLIED"
            )
        ),
        "modelCallStatus": (
            "OUTCOME_UNKNOWN" if canonical_outcome_unknown else "RESPONSE_RECEIVED"
        ),
        "failureCode": (
            "MODEL_PROVIDER_OUTCOME_UNKNOWN"
            if canonical_outcome_unknown
            else None
        ),
        "action": (
            "MANUAL_RECONCILIATION_REQUIRED"
            if canonical_outcome_unknown
            else ("REDELIVER_SAME_CANONICAL_FACT" if pending else "NONE")
        ),
        "providerRetryAllowed": False,
        "persistedDispatch": dispatch,
        "attemptedDispatch": dispatch,
        "canonicalFact": {
            "outcomeEventId": UUID("72000000-0000-4000-8000-000000000131"),
            "outcomeStatus": (
                "OUTCOME_UNKNOWN" if canonical_outcome_unknown else "SUCCEEDED"
            ),
            "sourceFactId": UUID("72000000-0000-4000-8000-000000000132"),
            "sourceFactVersion": 1,
            "sourceFactHash": "b" * 64,
            "outcomeCode": (
                "MODEL_OUTCOME_UNKNOWN"
                if canonical_outcome_unknown
                else "MODEL_RESPONSE_RECEIVED"
            ),
            "resultHash": None if canonical_outcome_unknown else "c" * 64,
        },
        "terminalResult": None,
    }
    if not pending and not canonical_outcome_unknown:
        payload["terminalResult"] = {
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
        }
    return GovernedInitialModelCallResponse.model_validate(payload, strict=True)


def _tool_required_response(
    receipt: GovernedInitialModelRequestReceipt,
) -> GovernedInitialModelCallResponse:
    arm = receipt.request.dispatch_arm
    dispatch = {
        "runtimeExternalPermitId": arm.runtime_external_permit_id,
        "leaseOwner": arm.lease_owner,
        "leaseEpoch": arm.lease_epoch,
        "armEventId": arm.arm_event_id,
    }
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
                    "72000000-0000-4000-8000-000000000141"
                ),
                "outcomeStatus": "SUCCEEDED",
                "sourceFactId": UUID(
                    "72000000-0000-4000-8000-000000000142"
                ),
                "sourceFactVersion": 1,
                "sourceFactHash": "d" * 64,
                "outcomeCode": "MODEL_TOOL_SELECTION_RECORDED",
                "resultHash": "e" * 64,
            },
            "terminalResult": None,
        },
        strict=True,
    )


def _tool_response(
    receipt: GovernedToolRequestReceipt,
    *,
    pending: bool,
    canonical_outcome_unknown: bool = False,
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
                "CANONICAL_OUTCOME_APPLIED"
                if canonical_outcome_unknown
                else (
                    "CANONICAL_OUTCOME_PENDING"
                    if pending
                    else "CANONICAL_OUTCOME_APPLIED"
                )
            ),
            "action": (
                "MANUAL_RECONCILIATION_REQUIRED"
                if canonical_outcome_unknown
                else ("REDELIVER_SAME_CANONICAL_FACT" if pending else "NONE")
            ),
            "providerRetryAllowed": False,
            "persistedDispatch": dispatch,
            "attemptedDispatch": dispatch,
            "canonicalFact": {
                "outcomeEventId": UUID(
                    "72000000-0000-4000-8000-000000000241"
                ),
                "outcomeStatus": (
                    "OUTCOME_UNKNOWN"
                    if canonical_outcome_unknown
                    else "SUCCEEDED"
                ),
                "sourceFactId": UUID(
                    "72000000-0000-4000-8000-000000000242"
                ),
                "sourceFactVersion": 1,
                "sourceFactHash": "7" * 64,
                "outcomeCode": (
                    "TOOL_OUTCOME_UNKNOWN"
                    if canonical_outcome_unknown
                    else "TOOL_SUCCEEDED"
                ),
                "resultHash": None if canonical_outcome_unknown else "8" * 64,
            },
        },
        strict=True,
    )

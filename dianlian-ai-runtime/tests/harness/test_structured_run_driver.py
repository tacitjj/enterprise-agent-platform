from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import httpx

from dianlian_runtime.harness.admission_manifest import JavaAdmissionManifestClient
from dianlian_runtime.harness.structured_admission_manifest import (
    JavaCapabilityStructuredAdmissionManifest,
    structured_one_call_policy_hash,
)
from dianlian_runtime.harness.structured_model_gateway import (
    StructuredModelCallResponse,
    StructuredModelGatewayOutcomeUnknown,
)
from dianlian_runtime.harness.structured_run_driver import StructuredRunExecutionDriver
from dianlian_runtime.supervisor.admission_permit_issuer import (
    AdmissionPermitDisposition,
    AdmissionPermitIssueResult,
)
from dianlian_runtime.supervisor.contracts import (
    ExternalOperation,
    ExternalPermitStatus,
    FrozenJsonObject,
    MultitaskStrategy,
    OperationKind,
    PrimitiveOutcome,
    PrimitiveResult,
    RuntimeExecutionAuthorityFact,
    RuntimeExternalPermitFact,
    RuntimeSourceKind,
    RuntimeStructuredCheckpointFact,
)
from dianlian_runtime.supervisor.driver import (
    DriverExecutionDisposition,
    DriverExecutionRequest,
    DriverFence,
)
from dianlian_runtime.supervisor.model_permit_issuer import (
    ModelPermitDisposition,
    ModelPermitIssueResult,
    ModelPermitReceipt,
)
from dianlian_runtime.supervisor.structured_checkpoint_store import (
    PostgresStructuredCheckpointStore,
    RuntimeStructuredState,
)


TENANT_ID = UUID("68000000-0000-4000-8000-000000000001")
RUN_ID = UUID("68000000-0000-4000-8000-000000000002")
TASK_ID = UUID("68000000-0000-4000-8000-000000000003")
STEP_ID = UUID("68000000-0000-4000-8000-000000000004")
THREAD_ID = UUID("68000000-0000-4000-8000-000000000005")
ADMISSION_ID = UUID("68000000-0000-4000-8000-000000000006")
ADMISSION_PERMIT_ID = UUID("68000000-0000-4000-8000-000000000007")
MODEL_PERMIT_ID = UUID("68000000-0000-4000-8000-000000000008")
ARM_EVENT_ID = UUID("68000000-0000-4000-8000-000000000009")
NOW = datetime(2026, 8, 16, tzinfo=UTC)
HASH = "a" * 64


class RecordingGate:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def revoked(self) -> bool:
        return False

    async def authorize_execution(self) -> None:
        self.calls += 1


class RecordingCheckpointRepository:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace
        self.current: RuntimeStructuredCheckpointFact | None = None

    def check_structured_checkpoint_capability(self):
        return PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, True)

    def load_structured_checkpoint(self, request):
        del request
        if self.current is None:
            return PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None)
        return PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, self.current)

    def save_structured_checkpoint(self, request):
        self.trace.append(f"save:{request.transition_code}")
        self.current = RuntimeStructuredCheckpointFact(
            tenant_id=request.tenant_id,
            runtime_run_id=request.runtime_run_id,
            task_execution_generation=request.task_execution_generation,
            checkpoint_id=request.checkpoint_id,
            previous_checkpoint_id=request.expected_checkpoint_id,
            state_version=request.expected_state_version + 1,
            state=request.state,
            state_hash=HASH,
            transition_code=request.transition_code,
            event_id=request.event_id,
            created_by=request.lease_owner,
            lease_epoch=request.lease_epoch,
            created_at=NOW,
        )
        return PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, self.current)


class AdmissionIssuer:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace

    def issue(self, request):
        self.trace.append("issue:admission")
        authority = request.authority
        fact = RuntimeExternalPermitFact(
            tenant_id=authority.tenant_id,
            runtime_external_permit_id=ADMISSION_PERMIT_ID,
            runtime_run_id=authority.runtime_run_id,
            runtime_thread_id=authority.runtime_thread_id,
            task_step_id=authority.task_step_id,
            task_execution_generation=authority.task_execution_generation,
            admission_contract_version="3.0",
            admission_snapshot_id=authority.admission_snapshot_id,
            admission_snapshot_hash=authority.admission_snapshot_hash,
            operation_kind=ExternalOperation.ADMISSION_RESOLVE,
            intent_id=authority.admission_snapshot_id,
            request_hash=authority.admission_snapshot_hash,
            lease_owner=authority.lease_owner,
            lease_epoch=authority.lease_epoch,
            permit_attempt=1,
            status=ExternalPermitStatus.ISSUED,
            requested_ttl_seconds=30,
            issued_at=NOW,
            expires_at=NOW + timedelta(seconds=30),
            issue_event_id=UUID("68000000-0000-4000-8000-00000000000a"),
            consume_event_id=None,
            consumed_by=None,
            consumed_at=None,
            updated_at=NOW,
        )
        return AdmissionPermitIssueResult(
            AdmissionPermitDisposition.CURRENT_ISSUED,
            fact,
            True,
        )


class AdmissionClient:
    def __init__(self, trace: list[str], manifest) -> None:
        self.trace = trace
        self.manifest = manifest

    async def resolve(self, request, permit, *, gate):
        del request, permit, gate
        self.trace.append("http:manifest")
        return self.manifest

    async def aclose(self) -> None:
        return None


class ModelIssuer:
    def __init__(self, trace: list[str], request_hash: str) -> None:
        self.trace = trace
        self.request_hash = request_hash

    def issue(self, request):
        self.trace.append("issue:model")
        authority = request.authority
        return ModelPermitIssueResult(
            ModelPermitDisposition.CURRENT_ISSUED,
            ModelPermitReceipt(
                tenant_id=authority.tenant_id,
                runtime_external_permit_id=MODEL_PERMIT_ID,
                runtime_run_id=authority.runtime_run_id,
                task_execution_generation=authority.task_execution_generation,
                lease_owner=authority.lease_owner,
                lease_epoch=authority.lease_epoch,
                admission_snapshot_id=authority.admission_snapshot_id,
                admission_snapshot_hash=authority.admission_snapshot_hash,
                operation_kind=ExternalOperation.MODEL_INVOKE,
                intent_id=request.intent_id,
                request_hash=self.request_hash,
                issue_event_id=UUID("68000000-0000-4000-8000-00000000000b"),
                arm_event_id=ARM_EVENT_ID,
                permit_attempt=1,
                issued_at=NOW,
                expires_at=NOW + timedelta(seconds=30),
            ),
            True,
        )


class Gateway:
    def __init__(self, trace: list[str], response, *, fail: bool = False) -> None:
        self.trace = trace
        self.response = response
        self.fail = fail

    async def invoke(self, receipt):
        self.trace.append("http:model")
        if self.fail:
            raise StructuredModelGatewayOutcomeUnknown(
                "STRUCTURED_MODEL_GATEWAY_OUTCOME_UNKNOWN",
                "QUERY_EXACT_JAVA",
            )
        return self.response(receipt)

    async def aclose(self) -> None:
        return None


def test_driver_persists_manifest_and_exact_receipt_before_java_post() -> None:
    async def verify() -> None:
        trace: list[str] = []
        manifest = _manifest()
        repository = RecordingCheckpointRepository(trace)
        gateway = Gateway(trace, _projected_response)
        driver = StructuredRunExecutionDriver(
            checkpoint_store=PostgresStructuredCheckpointStore(repository),
            admission_permit_issuer=AdmissionIssuer(trace),
            admission_manifest_client=AdmissionClient(trace, manifest),
            model_permit_issuer=ModelIssuer(trace, _model_request_hash()),
            model_gateway=gateway,
            offload=_direct_offload,
        )
        await driver.start()

        result = await driver.execute(
            _execution(),
            gate=RecordingGate(),
            checkpoints=SimpleNamespace(),
        )

        assert result.disposition == DriverExecutionDisposition.COMPLETED
        assert trace == [
            "issue:admission",
            "http:manifest",
            "save:MANIFEST_RESOLVED",
            "issue:model",
            "save:MODEL_RECEIPT_APPENDED",
            "http:model",
        ]
        assert repository.current is not None
        state = RuntimeStructuredState.from_fact(repository.current)
        assert len(state.receipts) == 1
        restored = state.find_receipt(MODEL_PERMIT_ID)
        assert restored is not None
        assert restored.exact_body.startswith(b'{"admission":')

    asyncio.run(verify())


def test_admission_client_selects_strict_30_manifest_contract() -> None:
    async def verify() -> None:
        execution = _execution()
        permit = AdmissionIssuer([]).issue(
            SimpleNamespace(authority=execution.authority)
        ).permit
        manifest = _manifest()
        client = JavaAdmissionManifestClient(
            base_url="https://java.internal",
            jwt_issuer=SimpleNamespace(
                issue=lambda **_kwargs: SimpleNamespace(value="admission-token")
            ),
            timeout_seconds=5,
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _request: httpx.Response(
                        200,
                        json=manifest.model_dump(mode="json", by_alias=True),
                    )
                )
            ),
        )
        resolved = await client.resolve(
            execution,
            permit,
            gate=RecordingGate(),
        )
        assert isinstance(resolved, JavaCapabilityStructuredAdmissionManifest)
        assert resolved.runtime_profile == "JAVA_CAPABILITY_STRUCTURED"

    asyncio.run(verify())


def test_gateway_unknown_keeps_run_pending_after_receipt_is_durable() -> None:
    async def verify() -> None:
        trace: list[str] = []
        repository = RecordingCheckpointRepository(trace)
        driver = StructuredRunExecutionDriver(
            checkpoint_store=PostgresStructuredCheckpointStore(repository),
            admission_permit_issuer=AdmissionIssuer(trace),
            admission_manifest_client=AdmissionClient(trace, _manifest()),
            model_permit_issuer=ModelIssuer(trace, _model_request_hash()),
            model_gateway=Gateway(trace, _projected_response, fail=True),
            offload=_direct_offload,
        )
        await driver.start()

        result = await driver.execute(
            _execution(),
            gate=RecordingGate(),
            checkpoints=SimpleNamespace(),
        )

        assert result.disposition == DriverExecutionDisposition.CONVERGENCE_PENDING
        assert trace[-2:] == ["save:MODEL_RECEIPT_APPENDED", "http:model"]
        assert repository.current is not None
        assert len(RuntimeStructuredState.from_fact(repository.current).receipts) == 1

    asyncio.run(verify())


def test_reentry_uses_exact_current_receipt_without_reissuing_permit() -> None:
    async def verify() -> None:
        trace: list[str] = []
        manifest = _manifest()
        repository = RecordingCheckpointRepository(trace)
        gateway = Gateway(trace, _projected_response, fail=True)
        driver = StructuredRunExecutionDriver(
            checkpoint_store=PostgresStructuredCheckpointStore(repository),
            admission_permit_issuer=AdmissionIssuer(trace),
            admission_manifest_client=AdmissionClient(trace, manifest),
            model_permit_issuer=ModelIssuer(trace, _model_request_hash()),
            model_gateway=gateway,
            offload=_direct_offload,
        )
        await driver.start()

        first = await driver.execute(
            _execution(), gate=RecordingGate(), checkpoints=SimpleNamespace())
        assert first.disposition == DriverExecutionDisposition.CONVERGENCE_PENDING
        assert trace.count("issue:model") == 1

        gateway.fail = False
        second = await driver.execute(
            _execution(), gate=RecordingGate(), checkpoints=SimpleNamespace())

        assert second.disposition == DriverExecutionDisposition.COMPLETED
        assert trace.count("issue:model") == 1
        assert trace[-1] == "http:model"

    asyncio.run(verify())


async def _direct_offload(function):
    return function()


def _execution() -> DriverExecutionRequest:
    authority = RuntimeExecutionAuthorityFact(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        runtime_thread_id=THREAD_ID,
        task_run_id=TASK_ID,
        task_step_id=STEP_ID,
        task_execution_generation=1,
        agent_instance_id=UUID("68000000-0000-4000-8000-00000000000c"),
        user_id=UUID("68000000-0000-4000-8000-00000000000d"),
        conversation_id=None,
        source_message_id=None,
        runtime_thread_revision=1,
        runtime_type="JAVA_CAPABILITY_STRUCTURED",
        runtime_agent_name="structured-runtime",
        capability_version_id=UUID("68000000-0000-4000-8000-00000000000e"),
        prompt_version_id=UUID("68000000-0000-4000-8000-00000000000f"),
        model_policy_id=UUID("68000000-0000-4000-8000-000000000010"),
        budget_reservation_id=UUID("68000000-0000-4000-8000-000000000011"),
        operation_kind=OperationKind.START,
        multitask_strategy=MultitaskStrategy.REJECT,
        request_hash="2" * 64,
        idempotency_key="structured-model-admission-0001",
        predecessor_runtime_run_id=None,
        expected_checkpoint_id=None,
        runtime_version="runtime-v1",
        agent_name="structured-agent-v1",
        lease_owner="worker-structured",
        lease_epoch=1,
        admission_contract_version="3.0",
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash="1" * 64,
        source_kind=RuntimeSourceKind.TASK_STEP,
    )
    return DriverExecutionRequest(
        authority,
        DriverFence(
            authority.tenant_id,
            authority.runtime_run_id,
            authority.task_execution_generation,
            authority.lease_owner,
            authority.lease_epoch,
            authority.admission_contract_version,
            authority.admission_snapshot_id,
            authority.admission_snapshot_hash,
        ),
    )


def _manifest() -> JavaCapabilityStructuredAdmissionManifest:
    ceiling = 100
    execution = _execution().authority
    return JavaCapabilityStructuredAdmissionManifest.model_validate(
        {
            "runtimeRunId": RUN_ID,
            "tenantId": TENANT_ID,
            "taskId": TASK_ID,
            "taskStepId": STEP_ID,
            "executionGeneration": 1,
            "actorUserId": execution.user_id,
            "admissionContractVersion": "3.0",
            "runtimeProfile": "JAVA_CAPABILITY_STRUCTURED",
            "admissionSnapshotId": ADMISSION_ID,
            "admissionSnapshotHash": "1" * 64,
            "requestHash": "2" * 64,
            "idempotencyKey": "structured-model-admission-0001",
            "inputSnapshotId": UUID("68000000-0000-4000-8000-000000000012"),
            "enterpriseAgentId": execution.agent_instance_id,
            "agentVersionId": UUID("68000000-0000-4000-8000-000000000013"),
            "configurationVersionId": UUID("68000000-0000-4000-8000-000000000014"),
            "pointReservationId": execution.budget_reservation_id,
            "capabilityPack": {
                "packCode": "QUOTATION",
                "packVersion": "1.0.0",
                "manifestHash": "3" * 64,
            },
            "modelRequirement": {
                "requiredCapabilityCodes": ["TEXT_CHAT"],
                "requiredFeatureCodes": ["JSON_SCHEMA_STRUCTURED_OUTPUT"],
                "responseContractCode": "quotation.model-candidate-drafts",
                "responseContractVersion": "1.0.0",
            },
            "modelResponseContract": {
                "reference": {
                    "kind": "MODEL_RESPONSE_SCHEMA",
                    "contractCode": "QUOTATION.MODEL-CANDIDATE-DRAFTS",
                    "version": "1.0.0",
                    "contractHash": "5" * 64,
                },
                "providerSchemaName": "quotation_candidate_drafts",
                "jsonSchema": '{"type":"object"}',
            },
            "candidateOutputContract": {
                "kind": "OUTPUT_SCHEMA",
                "contractCode": "QUOTATION.CANDIDATES",
                "version": "1.0.0",
                "contractHash": "4" * 64,
            },
            "candidateSchemaId": "quotation.candidates",
            "candidateSchemaVersion": "1.0.0",
            "modelRoute": {
                "routeBindingId": UUID("68000000-0000-4000-8000-000000000015"),
                "routeStateVersion": 1,
                "modelDefinitionId": UUID("68000000-0000-4000-8000-000000000016"),
                "modelConfigurationVersion": 1,
                "reservationCeilingMicroCredit": ceiling,
            },
            "modelQualification": {
                "policyId": UUID("68000000-0000-4000-8000-000000000017"),
                "policyVersion": 1,
                "policyHash": "8" * 64,
                "dataSensitivityCode": "SENSITIVE",
                "selectionReasonCode": "QUALIFIED_EXACT_ROUTE",
                "sensitivityEvidenceHash": "9" * 64,
            },
            "prompt": {
                "snapshotId": UUID("68000000-0000-4000-8000-000000000018"),
                "hash": "6" * 64,
            },
            "context": {
                "snapshotId": UUID("68000000-0000-4000-8000-000000000019"),
                "hash": "7" * 64,
            },
            "oneCallPolicy": {
                "policySnapshotId": UUID("68000000-0000-4000-8000-00000000001a"),
                "maxModelCalls": 1,
                "maxToolCalls": 0,
                "modelCallReservationCeiling": ceiling,
                "totalModelReservationCeiling": ceiling,
                "hash": structured_one_call_policy_hash(ceiling),
            },
        },
        strict=True,
    )


def _model_request_hash() -> str:
    from dianlian_runtime.harness.structured_model_receipt import (
        structured_model_request_hash,
    )

    return structured_model_request_hash(RUN_ID, ADMISSION_ID, "1" * 64)


def _projected_response(receipt) -> StructuredModelCallResponse:
    dispatch = receipt.request.dispatch_arm
    return StructuredModelCallResponse.model_validate(
        {
            "contractVersion": "1.0",
            "modelCallId": receipt.request.model_call_id,
            "modelRequestHash": receipt.request.model_request_hash,
            "disposition": "CANDIDATE_PROJECTED",
            "modelCallStatus": "RESPONSE_RECEIVED",
            "action": "NONE",
            "providerRetryAllowed": False,
            "persistedDispatch": dispatch.model_dump(mode="python", by_alias=True),
            "attemptedDispatch": dispatch.model_dump(mode="python", by_alias=True),
            "canonicalFact": {
                "outcomeEventId": UUID("68000000-0000-4000-8000-00000000001b"),
                "outcomeStatus": "SUCCEEDED",
                "sourceFactId": UUID("68000000-0000-4000-8000-00000000001c"),
                "sourceFactVersion": 1,
                "sourceFactHash": "b" * 64,
                "outcomeCode": "STRUCTURED_MODEL_SUCCEEDED",
                "resultHash": "c" * 64,
            },
            "candidateReceipt": {
                "documentId": UUID("68000000-0000-4000-8000-00000000001d"),
                "documentKind": "EXTRACTION_CANDIDATE_BATCH",
                "documentVersion": 1,
                "documentHash": "d" * 64,
            },
        },
        strict=True,
    )

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import pytest

from dianlian_runtime.supervisor.authorizer import (
    PostgresPermitAuthorizationService,
    create_postgres_permit_authorization_service,
)
from dianlian_runtime.supervisor.authorizer_contracts import (
    PermitAuthorizationOutcome,
    PermitAuthorizationRequest,
)
from dianlian_runtime.supervisor.contracts import (
    AdmitRuntimeRunRequest,
    AppendRuntimeRunEventRequest,
    AuthorizeRuntimeRunCancellationRequest,
    AuthorizeRuntimeRunRequest,
    BeginRuntimeRunCancellationRequest,
    ClaimRuntimeRunRequest,
    CompleteRuntimeRunRequest,
    ConsumeAndArmRuntimeExternalDispatchRequest,
    ConsumeRuntimeExternalPermitRequest,
    ExternalDispatchArmDecision,
    ExternalOperation,
    ExternalOperationAttemptStatus,
    ExternalOutcomeEvidenceKind,
    ExternalPermitStatus,
    FrozenJsonArray,
    FrozenJsonObject,
    IssueRuntimeExternalPermitRequest,
    LoadRuntimeExternalOperationBarrierRequest,
    LoadRuntimeExecutionAuthorityRequest,
    MultitaskStrategy,
    OperationKind,
    PrimitiveOutcome,
    ProgressEventType,
    ReconcileRuntimeExternalOperationOutcomeRequest,
    RecordRuntimeExternalOperationOutcomeRequest,
    RecordRuntimeCheckpointRequest,
    RequestRuntimeRunCancelRequest,
    RuntimeStatus,
    SelectNextRuntimeRunCandidateRequest,
    SupervisorPermissionBoundaryMisconfigured,
)
from dianlian_runtime.supervisor.postgres import PostgresRunSupervisorRepository


TEST_DSN = os.getenv("DIANLIAN_TEST_SUPERVISOR_RUNTIME_DATABASE_DSN")
AUTHORIZER_TEST_DSN = os.getenv(
    "DIANLIAN_TEST_SUPERVISOR_AUTHORIZER_DATABASE_DSN"
)
DISPATCH_AUTHORIZER_TEST_DSN = os.getenv(
    "DIANLIAN_TEST_SUPERVISOR_DISPATCH_AUTHORIZER_DATABASE_DSN"
)
RECONCILER_TEST_DSN = os.getenv(
    "DIANLIAN_TEST_SUPERVISOR_RECONCILER_DATABASE_DSN"
)
pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="DIANLIAN_TEST_SUPERVISOR_RUNTIME_DATABASE_DSN is not configured",
)


def _repository() -> PostgresRunSupervisorRepository:
    assert TEST_DSN is not None
    return PostgresRunSupervisorRepository(
        lambda: psycopg.connect(TEST_DSN, row_factory=dict_row)
    )


def _authorizer_repository() -> PostgresRunSupervisorRepository:
    assert AUTHORIZER_TEST_DSN is not None
    return PostgresRunSupervisorRepository(
        lambda: psycopg.connect(AUTHORIZER_TEST_DSN, row_factory=dict_row)
    )


def _reconciler_repository() -> PostgresRunSupervisorRepository:
    assert RECONCILER_TEST_DSN is not None
    return PostgresRunSupervisorRepository(
        lambda: psycopg.connect(RECONCILER_TEST_DSN, row_factory=dict_row)
    )


def _dispatch_authorizer_repository() -> PostgresRunSupervisorRepository:
    assert DISPATCH_AUTHORIZER_TEST_DSN is not None
    return PostgresRunSupervisorRepository(
        lambda: psycopg.connect(DISPATCH_AUTHORIZER_TEST_DSN, row_factory=dict_row)
    )


def _admit_queued_fixture(
    repository: PostgresRunSupervisorRepository,
    *,
    runtime_version: str,
    agent_name: str,
):
    runtime_run_id = uuid4()
    result = repository.admit(
        AdmitRuntimeRunRequest(
            tenant_id=uuid4(),
            runtime_thread_id=uuid4(),
            task_run_id=uuid4(),
            task_step_id=uuid4(),
            agent_instance_id=uuid4(),
            user_id=uuid4(),
            conversation_id=uuid4(),
            source_message_id=None,
            runtime_thread_revision=1,
            runtime_type="DEERFLOW",
            runtime_agent_name="candidate-integration",
            capability_version_id=uuid4(),
            prompt_version_id=uuid4(),
            model_policy_id=uuid4(),
            budget_reservation_id=uuid4(),
            input_artifact_ids=FrozenJsonArray([]),
            runtime_run_id=runtime_run_id,
            task_execution_generation=1,
            operation_kind=OperationKind.START,
            multitask_strategy=MultitaskStrategy.REJECT,
            request_hash="c" * 64,
            idempotency_key=f"admit-{runtime_run_id}",
            predecessor_runtime_run_id=None,
            expected_checkpoint_id=None,
            runtime_version=runtime_version,
            agent_name=agent_name,
            admission_contract_version="2.2",
            admission_snapshot_id=uuid4(),
            admission_snapshot_hash="f" * 64,
            accepted_event_id=uuid4(),
            accepted_event_payload=FrozenJsonObject(
                {"source": "candidate-integration"}
            ),
        )
    )
    assert result.outcome == PrimitiveOutcome.FACT_RETURNED
    assert result.fact is not None
    return result.fact


def test_restricted_runtime_repository_commits_a_fenced_run_lifecycle() -> None:
    repository = _repository()
    tenant_id = uuid4()
    runtime_thread_id = uuid4()
    runtime_run_id = uuid4()
    task_step_id = uuid4()
    accepted_event_id = uuid4()
    started_event_id = uuid4()
    progress_event_id = uuid4()
    checkpoint_event_id = uuid4()
    completed_event_id = uuid4()
    lease_owner = f"integration-worker-{uuid4()}"
    request_hash = "a" * 64

    admission = AdmitRuntimeRunRequest(
        tenant_id=tenant_id,
        runtime_thread_id=runtime_thread_id,
        task_run_id=uuid4(),
        task_step_id=task_step_id,
        agent_instance_id=uuid4(),
        user_id=uuid4(),
        conversation_id=uuid4(),
        source_message_id=None,
        runtime_thread_revision=1,
        runtime_type="DEERFLOW",
        runtime_agent_name="repository-integration",
        capability_version_id=uuid4(),
        prompt_version_id=uuid4(),
        model_policy_id=uuid4(),
        budget_reservation_id=uuid4(),
        input_artifact_ids=FrozenJsonArray(["artifact-1"]),
        runtime_run_id=runtime_run_id,
        task_execution_generation=1,
        operation_kind=OperationKind.START,
        multitask_strategy=MultitaskStrategy.REJECT,
        request_hash=request_hash,
        idempotency_key=f"admit-{runtime_run_id}",
        predecessor_runtime_run_id=None,
        expected_checkpoint_id=None,
        runtime_version="repository-s0",
        agent_name="repository-integration",
        admission_contract_version="2.2",
        admission_snapshot_id=uuid4(),
        admission_snapshot_hash="b" * 64,
        accepted_event_id=accepted_event_id,
        accepted_event_payload=FrozenJsonObject({"source": "repository-test"}),
    )

    admitted = repository.admit(admission)
    replayed_admission = repository.admit(admission)
    assert admitted == replayed_admission
    assert admitted.outcome == PrimitiveOutcome.FACT_RETURNED
    assert admitted.fact is not None
    assert admitted.fact.status == RuntimeStatus.QUEUED
    assert admitted.fact.lease_epoch == 0
    assert admitted.fact.run_version == 1

    claimed = repository.claim(
        ClaimRuntimeRunRequest(
            tenant_id=tenant_id,
            runtime_run_id=runtime_run_id,
            lease_owner=lease_owner,
            lease_seconds=60,
            started_event_id=started_event_id,
            event_payload=FrozenJsonObject({"source": "repository-test"}),
        )
    )
    assert claimed.outcome == PrimitiveOutcome.FACT_RETURNED
    assert claimed.fact is not None
    assert claimed.fact.status == RuntimeStatus.RUNNING
    assert claimed.fact.lease_owner == lease_owner
    assert claimed.fact.lease_epoch == 1
    assert claimed.fact.created_at.tzinfo is not None
    assert claimed.fact.updated_at.tzinfo is not None

    fence = {
        "tenant_id": tenant_id,
        "runtime_run_id": runtime_run_id,
        "lease_owner": lease_owner,
        "lease_epoch": 1,
    }
    authorized = repository.authorize(AuthorizeRuntimeRunRequest(**fence))
    assert authorized.outcome == PrimitiveOutcome.FACT_RETURNED
    assert authorized.fact is not None
    assert authorized.fact.runtime_run_id == runtime_run_id

    execution_authority = repository.load_execution_authority(
        LoadRuntimeExecutionAuthorityRequest(**fence)
    )
    assert execution_authority.outcome == PrimitiveOutcome.FACT_RETURNED
    assert execution_authority.fact is not None
    assert execution_authority.fact.tenant_id == admission.tenant_id
    assert execution_authority.fact.runtime_run_id == admission.runtime_run_id
    assert execution_authority.fact.runtime_thread_id == admission.runtime_thread_id
    assert execution_authority.fact.task_run_id == admission.task_run_id
    assert execution_authority.fact.task_step_id == admission.task_step_id
    assert (
        execution_authority.fact.task_execution_generation
        == admission.task_execution_generation
    )
    assert execution_authority.fact.agent_instance_id == admission.agent_instance_id
    assert execution_authority.fact.user_id == admission.user_id
    assert execution_authority.fact.conversation_id == admission.conversation_id
    assert execution_authority.fact.source_message_id == admission.source_message_id
    assert (
        execution_authority.fact.runtime_thread_revision
        == admission.runtime_thread_revision
    )
    assert execution_authority.fact.runtime_type == admission.runtime_type
    assert execution_authority.fact.runtime_agent_name == admission.runtime_agent_name
    assert (
        execution_authority.fact.capability_version_id
        == admission.capability_version_id
    )
    assert execution_authority.fact.prompt_version_id == admission.prompt_version_id
    assert execution_authority.fact.model_policy_id == admission.model_policy_id
    assert (
        execution_authority.fact.budget_reservation_id
        == admission.budget_reservation_id
    )
    assert execution_authority.fact.operation_kind == admission.operation_kind
    assert execution_authority.fact.multitask_strategy == admission.multitask_strategy
    assert execution_authority.fact.request_hash == admission.request_hash
    assert execution_authority.fact.idempotency_key == admission.idempotency_key
    assert (
        execution_authority.fact.predecessor_runtime_run_id
        == admission.predecessor_runtime_run_id
    )
    assert (
        execution_authority.fact.expected_checkpoint_id
        == admission.expected_checkpoint_id
    )
    assert execution_authority.fact.runtime_version == admission.runtime_version
    assert execution_authority.fact.agent_name == admission.agent_name
    assert execution_authority.fact.lease_owner == lease_owner
    assert execution_authority.fact.lease_epoch == 1
    assert (
        execution_authority.fact.admission_contract_version
        == admission.admission_contract_version
    )
    assert (
        execution_authority.fact.admission_snapshot_id
        == admission.admission_snapshot_id
    )
    assert (
        execution_authority.fact.admission_snapshot_hash
        == admission.admission_snapshot_hash
    )

    external_permit_id = uuid4()
    external_intent_id = uuid4()
    issue_event_id = uuid4()
    permit_request_hash = "9" * 64
    issued_permit = repository.issue_external_permit(
        IssueRuntimeExternalPermitRequest(
            tenant_id=tenant_id,
            runtime_run_id=runtime_run_id,
            lease_owner=lease_owner,
            lease_epoch=claimed.fact.lease_epoch,
            runtime_external_permit_id=external_permit_id,
            operation_kind=ExternalOperation.MODEL_INVOKE,
            intent_id=external_intent_id,
            request_hash=permit_request_hash,
            requested_ttl_seconds=30,
            issue_event_id=issue_event_id,
        )
    )
    replayed_permit = repository.issue_external_permit(
        IssueRuntimeExternalPermitRequest(
            tenant_id=tenant_id,
            runtime_run_id=runtime_run_id,
            lease_owner=lease_owner,
            lease_epoch=claimed.fact.lease_epoch,
            runtime_external_permit_id=external_permit_id,
            operation_kind=ExternalOperation.MODEL_INVOKE,
            intent_id=external_intent_id,
            request_hash=permit_request_hash,
            requested_ttl_seconds=30,
            issue_event_id=issue_event_id,
        )
    )
    assert issued_permit == replayed_permit
    assert issued_permit.outcome == PrimitiveOutcome.FACT_RETURNED
    assert issued_permit.fact is not None
    assert issued_permit.fact.status == ExternalPermitStatus.ISSUED
    assert issued_permit.fact.admission_snapshot_id == admission.admission_snapshot_id
    assert issued_permit.fact.admission_snapshot_hash == admission.admission_snapshot_hash

    cancellation_authority = repository.authorize_cancellation(
        AuthorizeRuntimeRunCancellationRequest(**fence)
    )
    assert cancellation_authority.outcome == PrimitiveOutcome.NOT_APPLIED
    assert cancellation_authority.fact is None

    progress = AppendRuntimeRunEventRequest(
        **fence,
        event_id=progress_event_id,
        event_type=ProgressEventType.STEP_PROGRESS,
        event_version=1,
        payload=FrozenJsonObject({"percent": 50}),
    )
    appended = repository.append_event(progress)
    replayed_progress = repository.append_event(progress)
    assert appended == replayed_progress
    assert appended.fact is not None
    assert appended.fact.sequence_no == 3
    assert appended.fact.payload.canonical == '{"percent":50}'

    checkpoint = RecordRuntimeCheckpointRequest(
        **fence,
        event_id=checkpoint_event_id,
        checkpoint_id=f"checkpoint-{runtime_run_id}",
        checkpoint_namespace="",
        checkpoint_schema_version="v1",
        event_payload=FrozenJsonObject({"source": "repository-test"}),
    )
    recorded = repository.record_checkpoint(checkpoint)
    replayed_checkpoint = repository.record_checkpoint(checkpoint)
    assert recorded == replayed_checkpoint
    assert recorded.fact is not None
    assert recorded.fact.sequence_no == 4
    assert recorded.fact.lease_epoch == 1

    completion = CompleteRuntimeRunRequest(
        **fence,
        event_id=completed_event_id,
        terminal_reason="SUCCEEDED",
        event_payload=FrozenJsonObject({"source": "repository-test"}),
    )
    completed = repository.complete(completion)
    replayed_completion = repository.complete(completion)
    assert completed == replayed_completion
    assert completed.fact is not None
    assert completed.fact.status == RuntimeStatus.COMPLETED
    assert completed.fact.current_checkpoint_id == f"checkpoint-{runtime_run_id}"
    assert completed.fact.terminal_event_id == completed_event_id
    assert completed.fact.lease_owner is None

    stale_authorization = repository.authorize(
        AuthorizeRuntimeRunRequest(**fence)
    )
    assert stale_authorization.outcome == PrimitiveOutcome.NOT_APPLIED
    assert stale_authorization.fact is None


@pytest.mark.skipif(
    not AUTHORIZER_TEST_DSN,
    reason="DIANLIAN_TEST_SUPERVISOR_AUTHORIZER_DATABASE_DSN is not configured",
)
def test_restricted_authorizer_is_ready_and_consumes_only_the_exact_issued_permit() -> None:
    runtime_repository = _repository()
    admitted = _admit_queued_fixture(
        runtime_repository,
        runtime_version=f"permit-runtime-{uuid4()}",
        agent_name=f"permit-agent-{uuid4()}",
    )
    lease_owner = f"permit-worker-{uuid4()}"
    claimed = runtime_repository.claim(
        ClaimRuntimeRunRequest(
            tenant_id=admitted.tenant_id,
            runtime_run_id=admitted.runtime_run_id,
            lease_owner=lease_owner,
            lease_seconds=60,
            started_event_id=uuid4(),
            event_payload=FrozenJsonObject({"source": "permit-authorizer"}),
        )
    )
    assert claimed.fact is not None
    runtime_external_permit_id = uuid4()
    intent_id = uuid4()
    request_hash = "8" * 64
    issued = runtime_repository.issue_external_permit(
        IssueRuntimeExternalPermitRequest(
            tenant_id=admitted.tenant_id,
            runtime_run_id=admitted.runtime_run_id,
            lease_owner=lease_owner,
            lease_epoch=claimed.fact.lease_epoch,
            runtime_external_permit_id=runtime_external_permit_id,
            operation_kind=ExternalOperation.ADMISSION_RESOLVE,
            intent_id=intent_id,
            request_hash=request_hash,
            requested_ttl_seconds=30,
            issue_event_id=uuid4(),
        )
    )
    assert issued.fact is not None
    consume_event_id = uuid4()
    request = PermitAuthorizationRequest.model_validate(
        {
            "tenantId": str(admitted.tenant_id),
            "runtimeExternalPermitId": str(runtime_external_permit_id),
            "runtimeRunId": str(admitted.runtime_run_id),
            "taskExecutionGeneration": admitted.task_execution_generation,
            "leaseOwner": lease_owner,
            "leaseEpoch": claimed.fact.lease_epoch,
            "admissionSnapshotId": str(issued.fact.admission_snapshot_id),
            "admissionSnapshotHash": issued.fact.admission_snapshot_hash,
            "operationKind": "ADMISSION_RESOLVE",
            "intentId": str(intent_id),
            "requestHash": request_hash,
            "consumeEventId": str(consume_event_id),
        }
    )
    assert AUTHORIZER_TEST_DSN is not None
    authorizer = create_postgres_permit_authorization_service(
        AUTHORIZER_TEST_DSN,
        connect_timeout_seconds=5,
        statement_timeout_seconds=5,
        lock_timeout_seconds=5,
    )

    authorizer.start()

    assert isinstance(authorizer, PostgresPermitAuthorizationService)
    assert authorizer.ready is True
    consumed = authorizer.authorize(
        request,
        consumed_by="repository-integration-authorizer",
    )
    replayed = authorizer.authorize(
        request,
        consumed_by="repository-integration-authorizer",
    )

    assert consumed == replayed == PermitAuthorizationOutcome.APPLIED
    assert authorizer.ready is True
    authorizer.close()
    assert authorizer.ready is False


@pytest.mark.skipif(
    not DISPATCH_AUTHORIZER_TEST_DSN or not RECONCILER_TEST_DSN,
    reason=(
        "DIANLIAN_TEST_SUPERVISOR_DISPATCH_AUTHORIZER_DATABASE_DSN and "
        "DIANLIAN_TEST_SUPERVISOR_RECONCILER_DATABASE_DSN are required"
    ),
)
def test_restricted_external_operation_channels_arm_record_reconcile_and_clear_barrier() -> None:
    runtime_repository = _repository()
    dispatch_authorizer_repository = _dispatch_authorizer_repository()
    reconciler_repository = _reconciler_repository()
    admitted = _admit_queued_fixture(
        runtime_repository,
        runtime_version=f"outcome-runtime-{uuid4()}",
        agent_name=f"outcome-agent-{uuid4()}",
    )
    lease_owner = f"outcome-worker-{uuid4()}"
    claimed = runtime_repository.claim(
        ClaimRuntimeRunRequest(
            tenant_id=admitted.tenant_id,
            runtime_run_id=admitted.runtime_run_id,
            lease_owner=lease_owner,
            lease_seconds=60,
            started_event_id=uuid4(),
            event_payload=FrozenJsonObject({"source": "external-outcome"}),
        )
    )
    assert claimed.fact is not None
    runtime_external_permit_id = uuid4()
    intent_id = uuid4()
    request_hash = "4" * 64
    issued = runtime_repository.issue_external_permit(
        IssueRuntimeExternalPermitRequest(
            tenant_id=admitted.tenant_id,
            runtime_run_id=admitted.runtime_run_id,
            lease_owner=lease_owner,
            lease_epoch=claimed.fact.lease_epoch,
            runtime_external_permit_id=runtime_external_permit_id,
            operation_kind=ExternalOperation.MODEL_INVOKE,
            intent_id=intent_id,
            request_hash=request_hash,
            requested_ttl_seconds=30,
            issue_event_id=uuid4(),
        )
    )
    assert issued.fact is not None
    binding = {
        "tenant_id": admitted.tenant_id,
        "runtime_external_permit_id": runtime_external_permit_id,
        "runtime_run_id": admitted.runtime_run_id,
        "task_execution_generation": admitted.task_execution_generation,
        "lease_owner": lease_owner,
        "lease_epoch": claimed.fact.lease_epoch,
        "admission_snapshot_id": issued.fact.admission_snapshot_id,
        "admission_snapshot_hash": issued.fact.admission_snapshot_hash,
        "operation_kind": ExternalOperation.MODEL_INVOKE,
        "intent_id": intent_id,
        "request_hash": request_hash,
    }
    barrier_request = LoadRuntimeExternalOperationBarrierRequest(
        tenant_id=admitted.tenant_id,
        runtime_run_id=admitted.runtime_run_id,
        task_execution_generation=admitted.task_execution_generation,
        lease_owner=lease_owner,
        lease_epoch=claimed.fact.lease_epoch,
    )
    clear_before_arm = runtime_repository.load_external_operation_barrier(
        barrier_request
    )
    assert clear_before_arm.fact is not None
    assert clear_before_arm.fact.blocking is False

    arm_event_id = uuid4()
    arm_request = ConsumeAndArmRuntimeExternalDispatchRequest(
        **binding,
        arm_event_id=arm_event_id,
        armed_by="repository-integration-authorizer",
    )
    armed = dispatch_authorizer_repository.consume_and_arm_external_dispatch(
        arm_request
    )
    assert armed.decision == ExternalDispatchArmDecision.GRANTED_NOW
    assert armed.fact is not None
    assert armed.fact.status == ExternalOperationAttemptStatus.DISPATCH_ARMED
    armed_barrier = runtime_repository.load_external_operation_barrier(barrier_request)
    assert armed_barrier.fact is not None
    assert armed_barrier.fact.dispatch_armed_count == 1
    assert armed_barrier.fact.outcome_unknown_count == 0
    assert armed_barrier.fact.blocking is True

    unknown_event_id = uuid4()
    source_fact_id = uuid4()
    unknown_request = RecordRuntimeExternalOperationOutcomeRequest(
        **binding,
        outcome_event_id=unknown_event_id,
        outcome_status=ExternalOperationAttemptStatus.OUTCOME_UNKNOWN,
        source_fact_id=source_fact_id,
        source_fact_version=1,
        source_fact_hash="5" * 64,
        outcome_code="JAVA_OUTCOME_UNKNOWN",
        evidence_kind=ExternalOutcomeEvidenceKind.JAVA_CANONICAL_FACT,
        result_hash=None,
        recorded_by="repository-integration-reconciler",
    )
    unknown = reconciler_repository.record_external_operation_outcome(
        unknown_request
    )
    replayed_unknown = reconciler_repository.record_external_operation_outcome(
        unknown_request
    )
    assert unknown == replayed_unknown
    assert unknown.fact is not None
    assert unknown.fact.status == ExternalOperationAttemptStatus.OUTCOME_UNKNOWN
    unknown_barrier = runtime_repository.load_external_operation_barrier(barrier_request)
    assert unknown_barrier.fact is not None
    assert unknown_barrier.fact.dispatch_armed_count == 0
    assert unknown_barrier.fact.outcome_unknown_count == 1

    reconcile_request = ReconcileRuntimeExternalOperationOutcomeRequest(
        **binding,
        expected_unknown_event_id=unknown_event_id,
        reconcile_event_id=uuid4(),
        outcome_status=ExternalOperationAttemptStatus.SUCCEEDED,
        source_fact_id=source_fact_id,
        source_fact_version=2,
        source_fact_hash="6" * 64,
        outcome_code="JAVA_SUCCEEDED_CONFIRMED",
        evidence_kind=ExternalOutcomeEvidenceKind.JAVA_CANONICAL_FACT,
        result_hash="7" * 64,
        recorded_by="repository-integration-reconciler",
    )
    reconciled = reconciler_repository.reconcile_external_operation_outcome(
        reconcile_request
    )
    replayed_reconciliation = (
        reconciler_repository.reconcile_external_operation_outcome(
            reconcile_request
        )
    )
    assert reconciled == replayed_reconciliation
    assert reconciled.fact is not None
    assert reconciled.fact.status == ExternalOperationAttemptStatus.SUCCEEDED
    assert reconciled.fact.source_fact_version == 2

    clear_after_reconciliation = runtime_repository.load_external_operation_barrier(
        barrier_request
    )
    assert clear_after_reconciliation.fact is not None
    assert clear_after_reconciliation.fact.blocking is False
    replayed_arm = (
        dispatch_authorizer_repository.consume_and_arm_external_dispatch(arm_request)
    )
    assert replayed_arm.decision == ExternalDispatchArmDecision.DO_NOT_DISPATCH
    assert replayed_arm.fact is not None
    assert replayed_arm.fact.status == ExternalOperationAttemptStatus.SUCCEEDED

    with pytest.raises(SupervisorPermissionBoundaryMisconfigured):
        dispatch_authorizer_repository.record_external_operation_outcome(
            unknown_request
        )
    with pytest.raises(SupervisorPermissionBoundaryMisconfigured):
        dispatch_authorizer_repository.reconcile_external_operation_outcome(
            reconcile_request
        )
    with pytest.raises(SupervisorPermissionBoundaryMisconfigured):
        reconciler_repository.consume_and_arm_external_dispatch(arm_request)


@pytest.mark.skipif(
    not AUTHORIZER_TEST_DSN or not DISPATCH_AUTHORIZER_TEST_DSN,
    reason=(
        "DIANLIAN_TEST_SUPERVISOR_AUTHORIZER_DATABASE_DSN and "
        "DIANLIAN_TEST_SUPERVISOR_DISPATCH_AUTHORIZER_DATABASE_DSN are required"
    ),
)
def test_admission_and_dispatch_authorizer_capabilities_are_not_interchangeable() -> None:
    permit_authorizer_repository = _authorizer_repository()
    dispatch_authorizer_repository = _dispatch_authorizer_repository()
    binding = {
        "tenant_id": uuid4(),
        "runtime_external_permit_id": uuid4(),
        "runtime_run_id": uuid4(),
        "task_execution_generation": 1,
        "lease_owner": "capability-separation-worker",
        "lease_epoch": 1,
        "admission_snapshot_id": uuid4(),
        "admission_snapshot_hash": "1" * 64,
        "intent_id": uuid4(),
        "request_hash": "2" * 64,
    }
    arm_request = ConsumeAndArmRuntimeExternalDispatchRequest(
        **binding,
        operation_kind=ExternalOperation.MODEL_INVOKE,
        arm_event_id=uuid4(),
        armed_by="dispatch-authorizer",
    )
    admission_request = ConsumeRuntimeExternalPermitRequest(
        **binding,
        operation_kind=ExternalOperation.ADMISSION_RESOLVE,
        consume_event_id=uuid4(),
        consumed_by="permit-authorizer",
    )

    with pytest.raises(SupervisorPermissionBoundaryMisconfigured):
        permit_authorizer_repository.consume_and_arm_external_dispatch(arm_request)
    with pytest.raises(SupervisorPermissionBoundaryMisconfigured):
        dispatch_authorizer_repository.consume_and_authorize_external_permit(
            admission_request
        )


def test_restricted_runtime_repository_separates_cancel_authority_states() -> None:
    repository = _repository()
    admitted = _admit_queued_fixture(
        repository,
        runtime_version=f"cancel-authority-{uuid4()}",
        agent_name=f"cancel-authority-{uuid4()}",
    )
    lease_owner = f"cancel-worker-{uuid4()}"
    claimed = repository.claim(
        ClaimRuntimeRunRequest(
            tenant_id=admitted.tenant_id,
            runtime_run_id=admitted.runtime_run_id,
            lease_owner=lease_owner,
            lease_seconds=60,
            started_event_id=uuid4(),
            event_payload=FrozenJsonObject({"source": "cancel-authority"}),
        )
    )
    assert claimed.fact is not None
    fence = {
        "tenant_id": admitted.tenant_id,
        "runtime_run_id": admitted.runtime_run_id,
        "lease_owner": lease_owner,
        "lease_epoch": claimed.fact.lease_epoch,
    }

    assert repository.load_execution_authority(
        LoadRuntimeExecutionAuthorityRequest(**fence)
    ).outcome == PrimitiveOutcome.FACT_RETURNED
    assert repository.authorize_cancellation(
        AuthorizeRuntimeRunCancellationRequest(**fence)
    ).outcome == PrimitiveOutcome.NOT_APPLIED

    cancel_requested = repository.request_cancel(
        RequestRuntimeRunCancelRequest(
            tenant_id=admitted.tenant_id,
            runtime_run_id=admitted.runtime_run_id,
            cancel_request_id=uuid4(),
            actor_id=uuid4(),
            reason_code="USER_REQUESTED",
            expected_run_version=claimed.fact.run_version,
            idempotency_key=f"cancel-{admitted.runtime_run_id}",
            request_hash="e" * 64,
            event_payload=FrozenJsonObject({"source": "cancel-authority"}),
        )
    )
    assert cancel_requested.outcome == PrimitiveOutcome.FACT_RETURNED
    assert repository.authorize(
        AuthorizeRuntimeRunRequest(**fence)
    ).outcome == PrimitiveOutcome.NOT_APPLIED
    assert repository.load_execution_authority(
        LoadRuntimeExecutionAuthorityRequest(**fence)
    ).outcome == PrimitiveOutcome.NOT_APPLIED
    assert repository.authorize_cancellation(
        AuthorizeRuntimeRunCancellationRequest(**fence)
    ).outcome == PrimitiveOutcome.NOT_APPLIED

    cancelling = repository.begin_cancellation(
        BeginRuntimeRunCancellationRequest(
            **fence,
            event_id=uuid4(),
            event_payload=FrozenJsonObject({"source": "cancel-authority"}),
        )
    )
    assert cancelling.outcome == PrimitiveOutcome.FACT_RETURNED
    assert cancelling.fact is not None
    assert cancelling.fact.status == RuntimeStatus.CANCELLING
    cancellation_authority = repository.authorize_cancellation(
        AuthorizeRuntimeRunCancellationRequest(**fence)
    )
    assert cancellation_authority.outcome == PrimitiveOutcome.FACT_RETURNED
    assert cancellation_authority.fact is not None
    assert cancellation_authority.fact.tenant_id == admitted.tenant_id
    assert cancellation_authority.fact.runtime_run_id == admitted.runtime_run_id
    assert cancellation_authority.fact.runtime_thread_id == admitted.runtime_thread_id
    assert cancellation_authority.fact.task_step_id == admitted.task_step_id
    assert (
        cancellation_authority.fact.task_execution_generation
        == admitted.task_execution_generation
    )
    assert cancellation_authority.fact.status == RuntimeStatus.CANCELLING
    assert cancellation_authority.fact.lease_owner == lease_owner
    assert cancellation_authority.fact.lease_epoch == claimed.fact.lease_epoch
    assert cancellation_authority.fact.run_version == cancelling.fact.run_version
    assert cancellation_authority.fact.cancel_requested_at is not None
    assert repository.authorize(
        AuthorizeRuntimeRunRequest(**fence)
    ).outcome == PrimitiveOutcome.NOT_APPLIED
    assert repository.load_execution_authority(
        LoadRuntimeExecutionAuthorityRequest(**fence)
    ).outcome == PrimitiveOutcome.NOT_APPLIED


def test_restricted_candidate_discovery_is_fifo_compatible_and_claim_fenced() -> None:
    repository = _repository()
    compatibility = SelectNextRuntimeRunCandidateRequest(
        runtime_version=f"candidate-runtime-{uuid4()}",
        agent_name=f"candidate-agent-{uuid4()}",
        admission_contract_version="2.2",
    )

    empty = repository.select_next_candidate(compatibility)
    assert empty.outcome == PrimitiveOutcome.NOT_APPLIED
    assert empty.fact is None

    cancelled = _admit_queued_fixture(
        repository,
        runtime_version=compatibility.runtime_version,
        agent_name=compatibility.agent_name,
    )
    cancel_result = repository.request_cancel(
        RequestRuntimeRunCancelRequest(
            tenant_id=cancelled.tenant_id,
            runtime_run_id=cancelled.runtime_run_id,
            cancel_request_id=uuid4(),
            actor_id=uuid4(),
            reason_code="USER_REQUESTED",
            expected_run_version=1,
            idempotency_key=f"cancel-{cancelled.runtime_run_id}",
            request_hash="d" * 64,
            event_payload=FrozenJsonObject({"source": "candidate-integration"}),
        )
    )
    assert cancel_result.outcome == PrimitiveOutcome.FACT_RETURNED

    first_queued = _admit_queued_fixture(
        repository,
        runtime_version=compatibility.runtime_version,
        agent_name=compatibility.agent_name,
    )
    second_queued = _admit_queued_fixture(
        repository,
        runtime_version=compatibility.runtime_version,
        agent_name=compatibility.agent_name,
    )
    _admit_queued_fixture(
        repository,
        runtime_version=f"incompatible-{uuid4()}",
        agent_name=compatibility.agent_name,
    )
    _admit_queued_fixture(
        repository,
        runtime_version=compatibility.runtime_version,
        agent_name=f"incompatible-{uuid4()}",
    )

    assert repository.select_next_candidate(
        SelectNextRuntimeRunCandidateRequest(
            f"missing-{uuid4()}", compatibility.agent_name, "2.2"
        )
    ).outcome == PrimitiveOutcome.NOT_APPLIED
    assert repository.select_next_candidate(
        SelectNextRuntimeRunCandidateRequest(
            compatibility.runtime_version, f"missing-{uuid4()}", "2.2"
        )
    ).outcome == PrimitiveOutcome.NOT_APPLIED

    expected_first = min(
        (first_queued, second_queued),
        key=lambda fact: (
            fact.created_at,
            fact.tenant_id.int,
            fact.runtime_run_id.int,
        ),
    )
    selected = repository.select_next_candidate(compatibility)
    replayed = repository.select_next_candidate(compatibility)
    assert selected == replayed
    assert selected.fact is not None
    assert selected.fact.tenant_id == expected_first.tenant_id
    assert selected.fact.runtime_run_id == expected_first.runtime_run_id
    assert selected.fact.runtime_run_id != cancelled.runtime_run_id

    ready = Barrier(3)

    def claim_candidate(worker_name: str):
        worker_repository = _repository()
        candidate = worker_repository.select_next_candidate(compatibility)
        assert candidate.fact == selected.fact
        ready.wait(timeout=5)
        assert candidate.fact is not None
        return worker_repository.claim(
            ClaimRuntimeRunRequest(
                tenant_id=candidate.fact.tenant_id,
                runtime_run_id=candidate.fact.runtime_run_id,
                lease_owner=worker_name,
                lease_seconds=60,
                started_event_id=uuid4(),
                event_payload=FrozenJsonObject(
                    {"source": "candidate-integration"}
                ),
            )
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_claim = executor.submit(claim_candidate, f"candidate-worker-{uuid4()}")
        second_claim = executor.submit(claim_candidate, f"candidate-worker-{uuid4()}")
        ready.wait(timeout=5)
        claim_results = [first_claim.result(timeout=5), second_claim.result(timeout=5)]

    assert sum(
        result.outcome == PrimitiveOutcome.FACT_RETURNED for result in claim_results
    ) == 1
    assert sum(
        result.outcome == PrimitiveOutcome.NOT_APPLIED for result in claim_results
    ) == 1

    selected_after_claim = repository.select_next_candidate(compatibility)
    assert selected_after_claim.fact is not None
    assert selected_after_claim.fact.runtime_run_id == (
        second_queued.runtime_run_id
        if expected_first.runtime_run_id == first_queued.runtime_run_id
        else first_queued.runtime_run_id
    )

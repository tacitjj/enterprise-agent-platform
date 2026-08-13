from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.pq import TransactionStatus

from dianlian_runtime.supervisor.contracts import (
    AdmitRuntimeRunRequest,
    AppendRuntimeRunEventRequest,
    AuthorizeRuntimeRunCancellationRequest,
    AuthorizeRuntimeRunRequest,
    BeginRuntimeRunCancellationRequest,
    CancellationTerminalStatus,
    ClaimRuntimeRunRequest,
    CompleteRuntimeRunRequest,
    ConsumeAndArmRuntimeExternalDispatchRequest,
    ConsumeRuntimeExternalPermitRequest,
    ExternalDispatchArmDecision,
    ExternalOperation,
    ExternalOperationAttemptStatus,
    ExternalOutcomeEvidenceKind,
    ExternalPermitStatus,
    FailRuntimeRunRequest,
    FinishRuntimeRunCancellationRequest,
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
    RenewRuntimeRunLeaseRequest,
    RequestRuntimeRunCancelRequest,
    RuntimeCancellationAuthorityFact,
    RuntimeExecutionAuthorityFact,
    RuntimeExternalDispatchArmResult,
    RuntimeExternalOperationAttemptFact,
    RuntimeExternalOperationBarrierFact,
    RuntimeExternalPermitFact,
    RuntimeRunCandidateFact,
    RuntimeRunEventFact,
    RuntimeRunFact,
    RuntimeStatus,
    SupervisorCommandConflict,
    SupervisorIntegrityOrContractViolation,
    SupervisorInvalidCommand,
    SupervisorOutcomeUnknown,
    SupervisorPermissionBoundaryMisconfigured,
    SupervisorTransientConflict,
    SupervisorUnavailable,
    SupervisorUnsupportedCommand,
    SelectNextRuntimeRunCandidateRequest,
    TakeoverRuntimeRunRequest,
)
from dianlian_runtime.supervisor.postgres import PostgresRunSupervisorRepository


NOW = datetime(2026, 8, 13, 4, 0, tzinfo=timezone(timedelta(hours=8)))
TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
RUN_ID = UUID("00000000-0000-0000-0000-000000000002")
THREAD_ID = UUID("00000000-0000-0000-0000-000000000003")
STEP_ID = UUID("00000000-0000-0000-0000-000000000004")
EVENT_ID = UUID("00000000-0000-0000-0000-000000000005")
ACTOR_ID = UUID("00000000-0000-0000-0000-000000000006")
TASK_ID = UUID("00000000-0000-0000-0000-000000000007")
AGENT_INSTANCE_ID = UUID("00000000-0000-0000-0000-000000000008")
USER_ID = UUID("00000000-0000-0000-0000-000000000009")
CONVERSATION_ID = UUID("00000000-0000-0000-0000-000000000010")
SOURCE_MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000011")
CAPABILITY_VERSION_ID = UUID("00000000-0000-0000-0000-000000000012")
PROMPT_VERSION_ID = UUID("00000000-0000-0000-0000-000000000013")
MODEL_POLICY_ID = UUID("00000000-0000-0000-0000-000000000014")
BUDGET_RESERVATION_ID = UUID("00000000-0000-0000-0000-000000000015")
ADMISSION_SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000016")
EXTERNAL_PERMIT_ID = UUID("00000000-0000-0000-0000-000000000017")
INTENT_ID = UUID("00000000-0000-0000-0000-000000000018")
CONSUME_EVENT_ID = UUID("00000000-0000-0000-0000-000000000019")
ARM_EVENT_ID = UUID("00000000-0000-0000-0000-000000000020")
OUTCOME_EVENT_ID = UUID("00000000-0000-0000-0000-000000000021")
SOURCE_FACT_ID = UUID("00000000-0000-0000-0000-000000000022")
RECONCILE_EVENT_ID = UUID("00000000-0000-0000-0000-000000000023")
HASH = "a" * 64
PAYLOAD = FrozenJsonObject({"z": [2, {"a": 1}]})


def _candidate_row() -> dict[str, object]:
    return {"tenant_id": TENANT_ID, "runtime_run_id": RUN_ID}


def _run_row() -> dict[str, object]:
    return {
        "tenant_id": TENANT_ID,
        "runtime_run_id": RUN_ID,
        "runtime_thread_id": THREAD_ID,
        "task_step_id": STEP_ID,
        "task_execution_generation": 1,
        "status": "RUNNING",
        "operation_kind": "START",
        "multitask_strategy": "REJECT",
        "request_hash": HASH,
        "idempotency_key": "command-1",
        "predecessor_runtime_run_id": None,
        "expected_checkpoint_id": None,
        "current_checkpoint_id": None,
        "current_checkpoint_sequence_no": None,
        "next_event_sequence_no": 3,
        "event_retention_floor_sequence": 1,
        "run_version": 2,
        "terminal_reason": None,
        "terminal_event_id": None,
        "lease_owner": "worker-1",
        "lease_until": NOW + timedelta(minutes=1),
        "lease_epoch": 1,
        "heartbeat_at": NOW,
        "attempt": 1,
        "runtime_version": "runtime-v1",
        "agent_name": "agent-v1",
        "failure_code": None,
        "cancel_requested_at": None,
        "started_at": NOW,
        "terminal_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _cancellation_authority_row() -> dict[str, object]:
    return {
        "tenant_id": TENANT_ID,
        "runtime_run_id": RUN_ID,
        "runtime_thread_id": THREAD_ID,
        "task_step_id": STEP_ID,
        "task_execution_generation": 1,
        "status": "CANCELLING",
        "lease_owner": "worker-1",
        "lease_epoch": 1,
        "run_version": 4,
        "cancel_requested_at": NOW,
    }


def _cancellation_authority_fact() -> RuntimeCancellationAuthorityFact:
    return RuntimeCancellationAuthorityFact(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        runtime_thread_id=THREAD_ID,
        task_step_id=STEP_ID,
        task_execution_generation=1,
        status=RuntimeStatus.CANCELLING,
        lease_owner="worker-1",
        lease_epoch=1,
        run_version=4,
        cancel_requested_at=NOW.astimezone(timezone.utc),
    )


def _execution_authority_row() -> dict[str, object]:
    return {
        "tenant_id": TENANT_ID,
        "runtime_run_id": RUN_ID,
        "runtime_thread_id": THREAD_ID,
        "task_run_id": TASK_ID,
        "task_step_id": STEP_ID,
        "task_execution_generation": 1,
        "agent_instance_id": AGENT_INSTANCE_ID,
        "user_id": USER_ID,
        "conversation_id": CONVERSATION_ID,
        "source_message_id": SOURCE_MESSAGE_ID,
        "runtime_thread_revision": 1,
        "runtime_type": "DEERFLOW",
        "runtime_agent_name": "runtime-agent",
        "capability_version_id": CAPABILITY_VERSION_ID,
        "prompt_version_id": PROMPT_VERSION_ID,
        "model_policy_id": MODEL_POLICY_ID,
        "budget_reservation_id": BUDGET_RESERVATION_ID,
        "operation_kind": "START",
        "multitask_strategy": "REJECT",
        "request_hash": HASH,
        "idempotency_key": "command-1",
        "predecessor_runtime_run_id": None,
        "expected_checkpoint_id": None,
        "runtime_version": "runtime-v1",
        "agent_name": "agent-v1",
        "lease_owner": "worker-1",
        "lease_epoch": 1,
        "admission_contract_version": "2.2",
        "admission_snapshot_id": ADMISSION_SNAPSHOT_ID,
        "admission_snapshot_hash": HASH,
    }


def _execution_authority_fact() -> RuntimeExecutionAuthorityFact:
    return RuntimeExecutionAuthorityFact(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        runtime_thread_id=THREAD_ID,
        task_run_id=TASK_ID,
        task_step_id=STEP_ID,
        task_execution_generation=1,
        agent_instance_id=AGENT_INSTANCE_ID,
        user_id=USER_ID,
        conversation_id=CONVERSATION_ID,
        source_message_id=SOURCE_MESSAGE_ID,
        runtime_thread_revision=1,
        runtime_type="DEERFLOW",
        runtime_agent_name="runtime-agent",
        capability_version_id=CAPABILITY_VERSION_ID,
        prompt_version_id=PROMPT_VERSION_ID,
        model_policy_id=MODEL_POLICY_ID,
        budget_reservation_id=BUDGET_RESERVATION_ID,
        operation_kind=OperationKind.START,
        multitask_strategy=MultitaskStrategy.REJECT,
        request_hash=HASH,
        idempotency_key="command-1",
        predecessor_runtime_run_id=None,
        expected_checkpoint_id=None,
        runtime_version="runtime-v1",
        agent_name="agent-v1",
        lease_owner="worker-1",
        lease_epoch=1,
        admission_contract_version="2.2",
        admission_snapshot_id=ADMISSION_SNAPSHOT_ID,
        admission_snapshot_hash=HASH,
    )


def _external_permit_row(*, consumed: bool = False) -> dict[str, object]:
    return {
        "tenant_id": TENANT_ID,
        "runtime_external_permit_id": EXTERNAL_PERMIT_ID,
        "runtime_run_id": RUN_ID,
        "runtime_thread_id": THREAD_ID,
        "task_step_id": STEP_ID,
        "task_execution_generation": 1,
        "admission_contract_version": "2.2",
        "admission_snapshot_id": ADMISSION_SNAPSHOT_ID,
        "admission_snapshot_hash": HASH,
        "operation_kind": "ADMISSION_RESOLVE" if consumed else "MODEL_INVOKE",
        "intent_id": INTENT_ID,
        "request_hash": HASH,
        "lease_owner": "worker-1",
        "lease_epoch": 1,
        "permit_attempt": 1,
        "status": "CONSUMED" if consumed else "ISSUED",
        "requested_ttl_seconds": 30,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(seconds=30),
        "issue_event_id": EVENT_ID,
        "consume_event_id": CONSUME_EVENT_ID if consumed else None,
        "consumed_by": "dianlian-platform" if consumed else None,
        "consumed_at": NOW + timedelta(seconds=1) if consumed else None,
        "updated_at": NOW + timedelta(seconds=1) if consumed else NOW,
    }


def _external_permit_fact(*, consumed: bool = False) -> RuntimeExternalPermitFact:
    return RuntimeExternalPermitFact(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=EXTERNAL_PERMIT_ID,
        runtime_run_id=RUN_ID,
        runtime_thread_id=THREAD_ID,
        task_step_id=STEP_ID,
        task_execution_generation=1,
        admission_contract_version="2.2",
        admission_snapshot_id=ADMISSION_SNAPSHOT_ID,
        admission_snapshot_hash=HASH,
        operation_kind=(
            ExternalOperation.ADMISSION_RESOLVE
            if consumed
            else ExternalOperation.MODEL_INVOKE
        ),
        intent_id=INTENT_ID,
        request_hash=HASH,
        lease_owner="worker-1",
        lease_epoch=1,
        permit_attempt=1,
        status=(
            ExternalPermitStatus.CONSUMED
            if consumed
            else ExternalPermitStatus.ISSUED
        ),
        requested_ttl_seconds=30,
        issued_at=NOW.astimezone(timezone.utc),
        expires_at=(NOW + timedelta(seconds=30)).astimezone(timezone.utc),
        issue_event_id=EVENT_ID,
        consume_event_id=CONSUME_EVENT_ID if consumed else None,
        consumed_by="dianlian-platform" if consumed else None,
        consumed_at=(
            (NOW + timedelta(seconds=1)).astimezone(timezone.utc)
            if consumed
            else None
        ),
        updated_at=(NOW + timedelta(seconds=1) if consumed else NOW).astimezone(
            timezone.utc
        ),
    )


def _issue_external_permit_request() -> IssueRuntimeExternalPermitRequest:
    return IssueRuntimeExternalPermitRequest(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        lease_owner="worker-1",
        lease_epoch=1,
        runtime_external_permit_id=EXTERNAL_PERMIT_ID,
        operation_kind=ExternalOperation.MODEL_INVOKE,
        intent_id=INTENT_ID,
        request_hash=HASH,
        requested_ttl_seconds=30,
        issue_event_id=EVENT_ID,
    )


def _consume_external_permit_request() -> ConsumeRuntimeExternalPermitRequest:
    return ConsumeRuntimeExternalPermitRequest(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=EXTERNAL_PERMIT_ID,
        runtime_run_id=RUN_ID,
        task_execution_generation=1,
        lease_owner="worker-1",
        lease_epoch=1,
        admission_snapshot_id=ADMISSION_SNAPSHOT_ID,
        admission_snapshot_hash=HASH,
        operation_kind=ExternalOperation.ADMISSION_RESOLVE,
        intent_id=INTENT_ID,
        request_hash=HASH,
        consume_event_id=CONSUME_EVENT_ID,
        consumed_by="dianlian-platform",
    )


def _external_attempt_row(
    *,
    status: str = "DISPATCH_ARMED",
    decision: str | None = None,
    source_fact_version: int = 1,
) -> dict[str, object]:
    terminal = status != "DISPATCH_ARMED"
    result_required = status in {"SUCCEEDED", "FAILED_CONFIRMED"}
    row: dict[str, object] = {
        "tenant_id": TENANT_ID,
        "runtime_external_permit_id": EXTERNAL_PERMIT_ID,
        "runtime_run_id": RUN_ID,
        "operation_kind": "MODEL_INVOKE",
        "intent_id": INTENT_ID,
        "permit_attempt": 1,
        "task_execution_generation": 1,
        "admission_snapshot_id": ADMISSION_SNAPSHOT_ID,
        "admission_snapshot_hash": HASH,
        "request_hash": HASH,
        "lease_owner": "worker-1",
        "lease_epoch": 1,
        "arm_event_id": ARM_EVENT_ID,
        "armed_by": "runtime-authorizer",
        "armed_at": NOW,
        "status": status,
        "last_event_id": OUTCOME_EVENT_ID if terminal else ARM_EVENT_ID,
        "source_fact_id": SOURCE_FACT_ID if terminal else None,
        "source_fact_version": source_fact_version if terminal else None,
        "source_fact_hash": HASH if terminal else None,
        "outcome_code": "CANONICAL_OUTCOME" if terminal else None,
        "evidence_kind": "JAVA_CANONICAL_FACT" if terminal else None,
        "result_hash": HASH if result_required else None,
        "recorded_by": "dianlian-platform" if terminal else None,
        "outcome_recorded_at": NOW + timedelta(seconds=1) if terminal else None,
        "updated_at": NOW + timedelta(seconds=1) if terminal else NOW,
    }
    if decision is not None:
        row["dispatch_decision"] = decision
    return row


def _consume_and_arm_request() -> ConsumeAndArmRuntimeExternalDispatchRequest:
    return ConsumeAndArmRuntimeExternalDispatchRequest(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=EXTERNAL_PERMIT_ID,
        runtime_run_id=RUN_ID,
        task_execution_generation=1,
        lease_owner="worker-1",
        lease_epoch=1,
        admission_snapshot_id=ADMISSION_SNAPSHOT_ID,
        admission_snapshot_hash=HASH,
        operation_kind=ExternalOperation.MODEL_INVOKE,
        intent_id=INTENT_ID,
        request_hash=HASH,
        arm_event_id=ARM_EVENT_ID,
        armed_by="runtime-authorizer",
    )


def _record_outcome_request(
    *,
    status: ExternalOperationAttemptStatus = ExternalOperationAttemptStatus.OUTCOME_UNKNOWN,
) -> RecordRuntimeExternalOperationOutcomeRequest:
    return RecordRuntimeExternalOperationOutcomeRequest(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=EXTERNAL_PERMIT_ID,
        runtime_run_id=RUN_ID,
        task_execution_generation=1,
        lease_owner="worker-1",
        lease_epoch=1,
        admission_snapshot_id=ADMISSION_SNAPSHOT_ID,
        admission_snapshot_hash=HASH,
        operation_kind=ExternalOperation.MODEL_INVOKE,
        intent_id=INTENT_ID,
        request_hash=HASH,
        outcome_event_id=OUTCOME_EVENT_ID,
        outcome_status=status,
        source_fact_id=SOURCE_FACT_ID,
        source_fact_version=1,
        source_fact_hash=HASH,
        outcome_code="CANONICAL_OUTCOME",
        evidence_kind=ExternalOutcomeEvidenceKind.JAVA_CANONICAL_FACT,
        result_hash=(
            HASH
            if status
            in {
                ExternalOperationAttemptStatus.SUCCEEDED,
                ExternalOperationAttemptStatus.FAILED_CONFIRMED,
            }
            else None
        ),
        recorded_by="dianlian-platform",
    )


def _reconcile_outcome_request() -> ReconcileRuntimeExternalOperationOutcomeRequest:
    return ReconcileRuntimeExternalOperationOutcomeRequest(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=EXTERNAL_PERMIT_ID,
        runtime_run_id=RUN_ID,
        task_execution_generation=1,
        lease_owner="worker-1",
        lease_epoch=1,
        admission_snapshot_id=ADMISSION_SNAPSHOT_ID,
        admission_snapshot_hash=HASH,
        operation_kind=ExternalOperation.MODEL_INVOKE,
        intent_id=INTENT_ID,
        request_hash=HASH,
        expected_unknown_event_id=OUTCOME_EVENT_ID,
        reconcile_event_id=RECONCILE_EVENT_ID,
        outcome_status=ExternalOperationAttemptStatus.SUCCEEDED,
        source_fact_id=SOURCE_FACT_ID,
        source_fact_version=2,
        source_fact_hash=HASH,
        outcome_code="CANONICAL_RECONCILED",
        evidence_kind=ExternalOutcomeEvidenceKind.JAVA_CANONICAL_FACT,
        result_hash=HASH,
        recorded_by="dianlian-platform",
    )


def _barrier_request() -> LoadRuntimeExternalOperationBarrierRequest:
    return LoadRuntimeExternalOperationBarrierRequest(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        task_execution_generation=1,
        lease_owner="worker-1",
        lease_epoch=1,
    )


def _barrier_row(*, blocking: bool = True) -> dict[str, object]:
    return {
        "tenant_id": TENANT_ID,
        "runtime_run_id": RUN_ID,
        "task_execution_generation": 1,
        "lease_owner": "worker-1",
        "lease_epoch": 1,
        "dispatch_armed_count": 1 if blocking else 0,
        "outcome_unknown_count": 0,
        "blocking": blocking,
        "oldest_blocking_at": NOW if blocking else None,
    }


def _event_row() -> dict[str, object]:
    return {
        "tenant_id": TENANT_ID,
        "runtime_run_id": RUN_ID,
        "runtime_thread_id": THREAD_ID,
        "event_id": EVENT_ID,
        "sequence_no": 3,
        "event_type": "STEP_PROGRESS",
        "event_version": 1,
        "run_version": 3,
        "lease_owner": "worker-1",
        "lease_epoch": 1,
        "checkpoint_id": None,
        "payload": {"nested": {"items": [1, 2]}},
        "occurred_at": NOW,
        "created_at": NOW,
    }


def _checkpoint_row() -> dict[str, object]:
    return {
        "tenant_id": TENANT_ID,
        "runtime_run_id": RUN_ID,
        "runtime_thread_id": THREAD_ID,
        "checkpoint_id": "checkpoint-1",
        "checkpoint_namespace": "",
        "sequence_no": 3,
        "event_id": EVENT_ID,
        "run_version": 3,
        "lease_epoch": 1,
        "checkpoint_schema_version": "v1",
        "created_at": NOW,
    }


def _control_row() -> dict[str, object]:
    return {
        "tenant_id": TENANT_ID,
        "control_id": EVENT_ID,
        "runtime_run_id": RUN_ID,
        "runtime_thread_id": THREAD_ID,
        "control_type": "CANCEL",
        "actor_id": ACTOR_ID,
        "reason_code": "USER_REQUESTED",
        "expected_run_version": 2,
        "idempotency_key": "cancel-1",
        "request_hash": HASH,
        "created_at": NOW,
    }


class FakeCursor(AbstractContextManager["FakeCursor"]):
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: str, parameters: object) -> None:
        self.connection.statement = statement
        self.connection.parameters = parameters
        if self.connection.execute_error is not None:
            raise self.connection.execute_error

    def fetchall(self) -> list[dict[str, object]]:
        return self.connection.rows


class FakeTransaction(AbstractContextManager[None]):
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> None:
        self.connection.trace.append("begin")
        if self.connection.begin_error is not None:
            raise self.connection.begin_error
        return None

    def __exit__(self, exception_type: object, *_args: object) -> None:
        if exception_type is not None:
            self.connection.trace.append("rollback")
            return None
        self.connection.trace.append("commit")
        if self.connection.commit_error is not None:
            raise self.connection.commit_error
        return None


class FakeConnection:
    def __init__(
        self,
        rows: list[dict[str, object]],
        *,
        execute_error: Exception | None = None,
        commit_error: Exception | None = None,
        begin_error: Exception | None = None,
        close_error: Exception | None = None,
    ) -> None:
        self.rows = rows
        self.execute_error = execute_error
        self.commit_error = commit_error
        self.begin_error = begin_error
        self.close_error = close_error
        self.statement = ""
        self.parameters: object = None
        self.trace: list[str] = []
        self.closed = False
        self.info = type(
            "FakeInfo",
            (),
            {"transaction_status": TransactionStatus.IDLE},
        )()

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def cursor(self, **_kwargs: object) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.trace.append("close")
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


def _repository(
    rows: list[dict[str, object]],
    **kwargs: object,
) -> tuple[PostgresRunSupervisorRepository, FakeConnection]:
    connection = FakeConnection(rows, **kwargs)
    return PostgresRunSupervisorRepository(lambda: connection), connection  # type: ignore[arg-type]


def _fenced_parameters() -> dict[str, object]:
    return {
        "tenant_id": TENANT_ID,
        "runtime_run_id": RUN_ID,
        "lease_owner": "worker-1",
        "lease_epoch": 1,
    }


def _requests() -> list[tuple[str, object, str, int, dict[str, object]]]:
    fenced = _fenced_parameters()
    return [
        (
            "select_next_candidate",
            SelectNextRuntimeRunCandidateRequest("runtime-v1", "agent-v1", "2.2"),
            "select_next_runtime_run_candidate",
            3,
            _candidate_row(),
        ),
        (
            "admit",
            AdmitRuntimeRunRequest(
                tenant_id=TENANT_ID,
                runtime_thread_id=THREAD_ID,
                task_run_id=uuid4(),
                task_step_id=STEP_ID,
                agent_instance_id=uuid4(),
                user_id=uuid4(),
                conversation_id=uuid4(),
                source_message_id=None,
                runtime_thread_revision=1,
                runtime_type="DEERFLOW",
                runtime_agent_name="runtime-agent",
                capability_version_id=uuid4(),
                prompt_version_id=uuid4(),
                model_policy_id=uuid4(),
                budget_reservation_id=uuid4(),
                input_artifact_ids=FrozenJsonArray(["artifact-1"]),
                runtime_run_id=RUN_ID,
                task_execution_generation=1,
                operation_kind=OperationKind.START,
                multitask_strategy=MultitaskStrategy.REJECT,
                request_hash=HASH,
                idempotency_key="command-1",
                predecessor_runtime_run_id=None,
                expected_checkpoint_id=None,
                runtime_version="runtime-v1",
                agent_name="agent-v1",
                admission_contract_version="2.2",
                admission_snapshot_id=ADMISSION_SNAPSHOT_ID,
                admission_snapshot_hash=HASH,
                accepted_event_id=EVENT_ID,
                accepted_event_payload=PAYLOAD,
            ),
            "admit_runtime_run",
            31,
            _run_row(),
        ),
        (
            "claim",
            ClaimRuntimeRunRequest(
                TENANT_ID,
                RUN_ID,
                "worker-1",
                30,
                EVENT_ID,
                PAYLOAD,
            ),
            "claim_runtime_run",
            6,
            _run_row(),
        ),
        (
            "renew_lease",
            RenewRuntimeRunLeaseRequest(**fenced, lease_seconds=30),
            "renew_runtime_run_lease",
            5,
            _run_row(),
        ),
        (
            "takeover",
            TakeoverRuntimeRunRequest(
                TENANT_ID,
                RUN_ID,
                "worker-2",
                30,
                EVENT_ID,
                PAYLOAD,
            ),
            "takeover_runtime_run",
            6,
            _run_row(),
        ),
        (
            "authorize",
            AuthorizeRuntimeRunRequest(**fenced),
            "authorize_runtime_run",
            4,
            _run_row(),
        ),
        (
            "authorize_cancellation",
            AuthorizeRuntimeRunCancellationRequest(**fenced),
            "authorize_runtime_run_cancellation",
            4,
            _cancellation_authority_row(),
        ),
        (
            "load_execution_authority",
            LoadRuntimeExecutionAuthorityRequest(**fenced),
            "load_runtime_execution_authority",
            4,
            _execution_authority_row(),
        ),
        (
            "issue_external_permit",
            _issue_external_permit_request(),
            "issue_runtime_external_permit",
            10,
            _external_permit_row(),
        ),
        (
            "consume_and_authorize_external_permit",
            _consume_external_permit_request(),
            "consume_and_authorize_runtime_external_permit",
            13,
            _external_permit_row(consumed=True),
        ),
        (
            "append_event",
            AppendRuntimeRunEventRequest(
                **fenced,
                event_id=EVENT_ID,
                event_type=ProgressEventType.STEP_PROGRESS,
                event_version=1,
                payload=PAYLOAD,
            ),
            "append_runtime_run_event",
            8,
            _event_row(),
        ),
        (
            "record_checkpoint",
            RecordRuntimeCheckpointRequest(
                **fenced,
                event_id=EVENT_ID,
                checkpoint_id="checkpoint-1",
                checkpoint_namespace="",
                checkpoint_schema_version="v1",
                event_payload=PAYLOAD,
            ),
            "record_runtime_checkpoint_ref",
            9,
            _checkpoint_row(),
        ),
        (
            "request_cancel",
            RequestRuntimeRunCancelRequest(
                TENANT_ID,
                RUN_ID,
                EVENT_ID,
                ACTOR_ID,
                "USER_REQUESTED",
                2,
                "cancel-1",
                HASH,
                PAYLOAD,
            ),
            "request_runtime_run_cancel",
            9,
            _control_row(),
        ),
        (
            "begin_cancellation",
            BeginRuntimeRunCancellationRequest(
                **fenced,
                event_id=EVENT_ID,
                event_payload=PAYLOAD,
            ),
            "begin_runtime_run_cancellation",
            6,
            _run_row(),
        ),
        (
            "complete",
            CompleteRuntimeRunRequest(
                **fenced,
                event_id=EVENT_ID,
                terminal_reason="SUCCEEDED",
                event_payload=PAYLOAD,
            ),
            "complete_runtime_run",
            7,
            _run_row(),
        ),
        (
            "fail",
            FailRuntimeRunRequest(
                **fenced,
                event_id=EVENT_ID,
                terminal_reason="EXECUTION_FAILED",
                failure_code="MODEL_FAILED",
                event_payload=PAYLOAD,
            ),
            "fail_runtime_run",
            8,
            _run_row(),
        ),
        (
            "finish_cancellation",
            FinishRuntimeRunCancellationRequest(
                **fenced,
                terminal_status=CancellationTerminalStatus.CANCELLED,
                event_id=EVENT_ID,
                terminal_reason="USER_REQUESTED",
                event_payload=PAYLOAD,
            ),
            "finish_runtime_run_cancellation",
            8,
            _run_row(),
        ),
    ]


@pytest.mark.parametrize(
    ("method", "command", "primitive", "parameter_count", "row"),
    _requests(),
)
def test_all_repository_methods_use_one_allowlisted_primitive_and_commit_after_mapping(
    method: str,
    command: object,
    primitive: str,
    parameter_count: int,
    row: dict[str, object],
) -> None:
    repository, connection = _repository([row])

    result = getattr(repository, method)(command)

    normalized = " ".join(connection.statement.split())
    assert normalized.startswith("SELECT ")
    assert f" FROM deer_runtime.{primitive}(" in normalized
    assert "SELECT *" not in normalized
    assert len(connection.parameters) == parameter_count  # type: ignore[arg-type]
    assert result.outcome == PrimitiveOutcome.FACT_RETURNED
    assert result.fact is not None
    assert connection.trace == ["begin", "commit", "close"]


def test_candidate_maps_to_a_strongly_typed_fact() -> None:
    repository, connection = _repository([_candidate_row()])

    result = repository.select_next_candidate(
        SelectNextRuntimeRunCandidateRequest("runtime-v1", "agent-v1", "2.2")
    )

    assert result.outcome == PrimitiveOutcome.FACT_RETURNED
    assert result.fact == RuntimeRunCandidateFact(TENANT_ID, RUN_ID)
    assert connection.parameters == ("runtime-v1", "agent-v1", "2.2")


def test_admit_binds_snapshot_receipt_after_runtime_compatibility() -> None:
    command = _requests()[1][1]
    assert isinstance(command, AdmitRuntimeRunRequest)
    repository, connection = _repository([_run_row()])

    repository.admit(command)

    assert connection.parameters is not None
    assert connection.parameters[24:30] == (  # type: ignore[index]
        command.runtime_version,
        command.agent_name,
        command.admission_contract_version,
        command.admission_snapshot_id,
        command.admission_snapshot_hash,
        command.accepted_event_id,
    )


def test_cancellation_authority_maps_only_the_fenced_cancellation_fact() -> None:
    repository, connection = _repository([_cancellation_authority_row()])

    result = repository.authorize_cancellation(
        AuthorizeRuntimeRunCancellationRequest(**_fenced_parameters())
    )

    assert result.fact == _cancellation_authority_fact()
    projection = " ".join(connection.statement.split()).split(" FROM ", 1)[0]
    assert projection == (
        "SELECT tenant_id, runtime_run_id, runtime_thread_id, task_step_id, "
        "task_execution_generation, status, lease_owner, lease_epoch, run_version, "
        "cancel_requested_at"
    )


def test_execution_authority_maps_only_immutable_scalar_references_and_fence() -> None:
    repository, connection = _repository([_execution_authority_row()])

    result = repository.load_execution_authority(
        LoadRuntimeExecutionAuthorityRequest(**_fenced_parameters())
    )

    assert result.fact == _execution_authority_fact()
    projection = " ".join(connection.statement.split()).split(" FROM ", 1)[0]
    assert projection == (
        "SELECT tenant_id, runtime_run_id, runtime_thread_id, task_run_id, "
        "task_step_id, task_execution_generation, agent_instance_id, user_id, "
        "conversation_id, source_message_id, runtime_thread_revision, runtime_type, "
        "runtime_agent_name, capability_version_id, prompt_version_id, "
        "model_policy_id, budget_reservation_id, operation_kind, multitask_strategy, "
        "request_hash, idempotency_key, predecessor_runtime_run_id, "
        "expected_checkpoint_id, runtime_version, agent_name, lease_owner, lease_epoch, "
        "admission_contract_version, admission_snapshot_id, admission_snapshot_hash"
    )


def test_external_permit_primitives_bind_frozen_signatures_and_explicit_projection() -> None:
    issue_repository, issue_connection = _repository([_external_permit_row()])
    authorize_repository, authorize_connection = _repository(
        [_external_permit_row(consumed=True)]
    )

    issued = issue_repository.issue_external_permit(
        _issue_external_permit_request()
    )
    consumed_and_authorized = (
        authorize_repository.consume_and_authorize_external_permit(
            _consume_external_permit_request()
        )
    )

    assert issued.fact == _external_permit_fact()
    assert consumed_and_authorized.fact == _external_permit_fact(consumed=True)
    assert issue_connection.parameters == (
        TENANT_ID,
        RUN_ID,
        "worker-1",
        1,
        EXTERNAL_PERMIT_ID,
        "MODEL_INVOKE",
        INTENT_ID,
        HASH,
        30,
        EVENT_ID,
    )
    assert authorize_connection.parameters == (
        TENANT_ID,
        EXTERNAL_PERMIT_ID,
        RUN_ID,
        1,
        "worker-1",
        1,
        ADMISSION_SNAPSHOT_ID,
        HASH,
        "ADMISSION_RESOLVE",
        INTENT_ID,
        HASH,
        CONSUME_EVENT_ID,
        "dianlian-platform",
    )
    expected_projection = (
        "SELECT tenant_id, runtime_external_permit_id, runtime_run_id, "
        "runtime_thread_id, task_step_id, task_execution_generation, "
        "admission_contract_version, admission_snapshot_id, "
        "admission_snapshot_hash, operation_kind, intent_id, request_hash, "
        "lease_owner, lease_epoch, permit_attempt, status, requested_ttl_seconds, "
        "issued_at, expires_at, issue_event_id, consume_event_id, consumed_by, "
        "consumed_at, updated_at"
    )
    for connection in (
        issue_connection,
        authorize_connection,
    ):
        projection = " ".join(connection.statement.split()).split(" FROM ", 1)[0]
        assert projection == expected_projection


def test_current_external_permit_wrapper_zero_rows_commit_as_not_applied() -> None:
    repository, connection = _repository([])

    result = repository.consume_and_authorize_external_permit(
        _consume_external_permit_request()
    )

    assert result.outcome == PrimitiveOutcome.NOT_APPLIED
    assert result.fact is None
    assert connection.trace == ["begin", "commit", "close"]


@pytest.mark.parametrize(
    ("database_error", "expected"),
    [
        (
            psycopg.errors.InsufficientPrivilege("permission"),
            SupervisorPermissionBoundaryMisconfigured,
        ),
        (psycopg.errors.InvalidParameterValue("invalid"), SupervisorInvalidCommand),
        (psycopg.errors.ConnectionFailure("lost"), SupervisorOutcomeUnknown),
    ],
)
def test_current_external_permit_wrapper_maps_errors_to_its_own_primitive(
    database_error: psycopg.Error,
    expected: type[Exception],
) -> None:
    repository, connection = _repository([], execute_error=database_error)

    with pytest.raises(expected) as raised:
        repository.consume_and_authorize_external_permit(
            _consume_external_permit_request()
        )

    assert raised.value.primitive.value == (
        "consume_and_authorize_runtime_external_permit"
    )
    assert connection.trace == ["begin", "rollback", "close"]


def test_current_external_permit_wrapper_commit_loss_is_outcome_unknown() -> None:
    repository, connection = _repository(
        [_external_permit_row(consumed=True)],
        commit_error=psycopg.errors.ConnectionFailure("commit lost"),
    )

    with pytest.raises(SupervisorOutcomeUnknown) as raised:
        repository.consume_and_authorize_external_permit(
            _consume_external_permit_request()
        )

    assert raised.value.primitive.value == (
        "consume_and_authorize_runtime_external_permit"
    )
    assert connection.trace == ["begin", "commit", "close"]


def test_external_operation_primitives_bind_frozen_signatures_and_explicit_projections() -> None:
    arm_repository, arm_connection = _repository(
        [_external_attempt_row(decision="GRANTED_NOW")]
    )
    record_repository, record_connection = _repository(
        [_external_attempt_row(status="OUTCOME_UNKNOWN")]
    )
    reconciled_row = _external_attempt_row(
        status="SUCCEEDED",
        source_fact_version=2,
    )
    reconciled_row["last_event_id"] = RECONCILE_EVENT_ID
    reconcile_repository, reconcile_connection = _repository([reconciled_row])
    barrier_repository, barrier_connection = _repository([_barrier_row()])

    armed = arm_repository.consume_and_arm_external_dispatch(
        _consume_and_arm_request()
    )
    recorded = record_repository.record_external_operation_outcome(
        _record_outcome_request()
    )
    reconciled = reconcile_repository.reconcile_external_operation_outcome(
        _reconcile_outcome_request()
    )
    barrier = barrier_repository.load_external_operation_barrier(_barrier_request())

    assert armed.outcome == PrimitiveOutcome.FACT_RETURNED
    assert armed.decision == ExternalDispatchArmDecision.GRANTED_NOW
    assert isinstance(armed.fact, RuntimeExternalOperationAttemptFact)
    assert armed.fact.status == ExternalOperationAttemptStatus.DISPATCH_ARMED
    assert armed.fact.armed_at.tzinfo == timezone.utc
    assert recorded.fact is not None
    assert recorded.fact.status == ExternalOperationAttemptStatus.OUTCOME_UNKNOWN
    assert reconciled.fact is not None
    assert reconciled.fact.status == ExternalOperationAttemptStatus.SUCCEEDED
    assert reconciled.fact.source_fact_version == 2
    assert barrier.fact == RuntimeExternalOperationBarrierFact(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        task_execution_generation=1,
        lease_owner="worker-1",
        lease_epoch=1,
        dispatch_armed_count=1,
        outcome_unknown_count=0,
        blocking=True,
        oldest_blocking_at=NOW.astimezone(timezone.utc),
    )
    assert arm_connection.parameters == (
        TENANT_ID,
        EXTERNAL_PERMIT_ID,
        RUN_ID,
        1,
        "worker-1",
        1,
        ADMISSION_SNAPSHOT_ID,
        HASH,
        "MODEL_INVOKE",
        INTENT_ID,
        HASH,
        ARM_EVENT_ID,
        "runtime-authorizer",
    )
    assert record_connection.parameters == (
        TENANT_ID,
        EXTERNAL_PERMIT_ID,
        RUN_ID,
        1,
        "worker-1",
        1,
        ADMISSION_SNAPSHOT_ID,
        HASH,
        "MODEL_INVOKE",
        INTENT_ID,
        HASH,
        OUTCOME_EVENT_ID,
        "OUTCOME_UNKNOWN",
        SOURCE_FACT_ID,
        1,
        HASH,
        "CANONICAL_OUTCOME",
        "JAVA_CANONICAL_FACT",
        None,
        "dianlian-platform",
    )
    assert reconcile_connection.parameters == (
        TENANT_ID,
        EXTERNAL_PERMIT_ID,
        RUN_ID,
        1,
        "worker-1",
        1,
        ADMISSION_SNAPSHOT_ID,
        HASH,
        "MODEL_INVOKE",
        INTENT_ID,
        HASH,
        OUTCOME_EVENT_ID,
        RECONCILE_EVENT_ID,
        "SUCCEEDED",
        SOURCE_FACT_ID,
        2,
        HASH,
        "CANONICAL_RECONCILED",
        "JAVA_CANONICAL_FACT",
        HASH,
        "dianlian-platform",
    )
    assert barrier_connection.parameters == (TENANT_ID, RUN_ID, 1, "worker-1", 1)

    attempt_projection = (
        "tenant_id, runtime_external_permit_id, runtime_run_id, operation_kind, "
        "intent_id, permit_attempt, task_execution_generation, admission_snapshot_id, "
        "admission_snapshot_hash, request_hash, lease_owner, lease_epoch, arm_event_id, "
        "armed_by, armed_at, status, last_event_id, source_fact_id, "
        "source_fact_version, source_fact_hash, outcome_code, evidence_kind, result_hash, "
        "recorded_by, outcome_recorded_at, updated_at"
    )
    arm_projection = " ".join(arm_connection.statement.split()).split(" FROM ", 1)[0]
    assert arm_projection == f"SELECT dispatch_decision, {attempt_projection}"
    for connection in (record_connection, reconcile_connection):
        projection = " ".join(connection.statement.split()).split(" FROM ", 1)[0]
        assert projection == f"SELECT {attempt_projection}"
    barrier_projection = " ".join(barrier_connection.statement.split()).split(
        " FROM ",
        1,
    )[0]
    assert barrier_projection == (
        "SELECT tenant_id, runtime_run_id, task_execution_generation, lease_owner, "
        "lease_epoch, dispatch_armed_count, outcome_unknown_count, blocking, "
        "oldest_blocking_at"
    )
    for connection in (
        arm_connection,
        record_connection,
        reconcile_connection,
        barrier_connection,
    ):
        assert connection.trace == ["begin", "commit", "close"]


def test_arm_replay_is_strongly_typed_do_not_dispatch_even_after_outcome() -> None:
    row = _external_attempt_row(
        status="SUCCEEDED",
        decision="DO_NOT_DISPATCH",
        source_fact_version=2,
    )
    repository, connection = _repository([row])

    result = repository.consume_and_arm_external_dispatch(
        _consume_and_arm_request()
    )

    assert result.decision == ExternalDispatchArmDecision.DO_NOT_DISPATCH
    assert result.fact is not None
    assert result.fact.status == ExternalOperationAttemptStatus.SUCCEEDED
    assert connection.trace == ["begin", "commit", "close"]


def test_arm_zero_rows_is_not_applied_without_a_dispatch_decision() -> None:
    repository, connection = _repository([])

    result = repository.consume_and_arm_external_dispatch(
        _consume_and_arm_request()
    )

    assert result == RuntimeExternalDispatchArmResult(
        outcome=PrimitiveOutcome.NOT_APPLIED,
        decision=None,
        fact=None,
    )
    assert connection.trace == ["begin", "commit", "close"]


@pytest.mark.parametrize(
    ("method", "command"),
    [
        ("record_external_operation_outcome", _record_outcome_request()),
        ("reconcile_external_operation_outcome", _reconcile_outcome_request()),
        ("load_external_operation_barrier", _barrier_request()),
    ],
)
def test_external_outcome_and_barrier_zero_rows_remain_not_applied(
    method: str,
    command: object,
) -> None:
    repository, connection = _repository([])

    result = getattr(repository, method)(command)

    assert result.outcome == PrimitiveOutcome.NOT_APPLIED
    assert result.fact is None
    assert connection.trace == ["begin", "commit", "close"]


@pytest.mark.parametrize(
    ("command", "field", "malicious_value", "expected_error"),
    [
        (_issue_external_permit_request(), "lease_epoch", True, TypeError),
        (_issue_external_permit_request(), "operation_kind", "MODEL_INVOKE", TypeError),
        (_issue_external_permit_request(), "request_hash", "A" * 64, ValueError),
        (_issue_external_permit_request(), "requested_ttl_seconds", 61, ValueError),
        (
            _consume_external_permit_request(),
            "task_execution_generation",
            0,
            ValueError,
        ),
        (
            _consume_external_permit_request(),
            "admission_snapshot_id",
            UUID(int=0),
            ValueError,
        ),
        (_consume_external_permit_request(), "consumed_by", "", ValueError),
    ],
)
def test_external_permit_requests_reject_unfrozen_authority_fields(
    command: object,
    field: str,
    malicious_value: object,
    expected_error: type[Exception],
) -> None:
    with pytest.raises(expected_error):
        replace(command, **{field: malicious_value})


@pytest.mark.parametrize(
    ("consumed", "field", "malicious_value"),
    [
        (False, "admission_contract_version", "2.1"),
        (False, "admission_snapshot_hash", "A" * 64),
        (False, "operation_kind", "UNKNOWN"),
        (False, "status", "CONSUMED"),
        (False, "permit_attempt", True),
        (False, "permit_attempt", 2**31),
        (False, "requested_ttl_seconds", 61),
        (False, "consume_event_id", CONSUME_EVENT_ID),
        (False, "updated_at", NOW - timedelta(seconds=1)),
        (True, "consumed_by", None),
        (True, "consumed_at", NOW.replace(tzinfo=None)),
        (True, "consumed_at", NOW + timedelta(seconds=30)),
        (True, "expires_at", NOW - timedelta(seconds=1)),
    ],
)
def test_external_permit_mapper_rejects_malicious_rows_and_rolls_back(
    consumed: bool,
    field: str,
    malicious_value: object,
) -> None:
    row = _external_permit_row(consumed=consumed)
    row[field] = malicious_value
    repository, connection = _repository([row])
    method = (
        "consume_and_authorize_external_permit"
        if consumed
        else "issue_external_permit"
    )
    request = (
        _consume_external_permit_request()
        if consumed
        else _issue_external_permit_request()
    )

    with pytest.raises(SupervisorIntegrityOrContractViolation):
        getattr(repository, method)(request)

    assert connection.trace == ["begin", "rollback", "close"]


@pytest.mark.parametrize(
    ("command", "field", "malicious_value", "expected_error"),
    [
        (
            _consume_and_arm_request(),
            "operation_kind",
            ExternalOperation.ADMISSION_RESOLVE,
            ValueError,
        ),
        (_consume_and_arm_request(), "task_execution_generation", True, TypeError),
        (_consume_and_arm_request(), "admission_snapshot_hash", "A" * 64, ValueError),
        (_consume_and_arm_request(), "armed_by", "", ValueError),
        (
            _record_outcome_request(),
            "outcome_status",
            ExternalOperationAttemptStatus.DISPATCH_ARMED,
            ValueError,
        ),
        (
            _record_outcome_request(status=ExternalOperationAttemptStatus.SUCCEEDED),
            "result_hash",
            None,
            TypeError,
        ),
        (_record_outcome_request(), "result_hash", HASH, ValueError),
        (_record_outcome_request(), "evidence_kind", "JAVA_CANONICAL_FACT", TypeError),
        (_record_outcome_request(), "source_fact_version", True, TypeError),
        (_record_outcome_request(), "outcome_code", "provider-result", ValueError),
        (
            _reconcile_outcome_request(),
            "outcome_status",
            ExternalOperationAttemptStatus.OUTCOME_UNKNOWN,
            ValueError,
        ),
        (_barrier_request(), "lease_epoch", True, TypeError),
    ],
)
def test_external_operation_requests_reject_unfrozen_authority_or_outcome_fields(
    command: object,
    field: str,
    malicious_value: object,
    expected_error: type[Exception],
) -> None:
    with pytest.raises(expected_error):
        replace(command, **{field: malicious_value})


def test_external_dispatch_arm_result_cannot_conflate_grant_replay_and_rejection() -> None:
    fact_row = _external_attempt_row()
    repository, _connection = _repository(
        [{**fact_row, "dispatch_decision": "GRANTED_NOW"}]
    )
    fact = repository.consume_and_arm_external_dispatch(
        _consume_and_arm_request()
    ).fact
    assert fact is not None

    with pytest.raises(ValueError, match="cannot contain"):
        RuntimeExternalDispatchArmResult(
            PrimitiveOutcome.NOT_APPLIED,
            ExternalDispatchArmDecision.DO_NOT_DISPATCH,
            fact,
        )
    with pytest.raises(TypeError, match="decision"):
        RuntimeExternalDispatchArmResult(
            PrimitiveOutcome.FACT_RETURNED,
            None,
            fact,
        )
    terminal_fact = replace(
        fact,
        status=ExternalOperationAttemptStatus.SUCCEEDED,
        last_event_id=OUTCOME_EVENT_ID,
        source_fact_id=SOURCE_FACT_ID,
        source_fact_version=1,
        source_fact_hash=HASH,
        outcome_code="CANONICAL_OUTCOME",
        evidence_kind=ExternalOutcomeEvidenceKind.JAVA_CANONICAL_FACT,
        result_hash=HASH,
        recorded_by="dianlian-platform",
        outcome_recorded_at=NOW.astimezone(timezone.utc),
        updated_at=NOW.astimezone(timezone.utc),
    )
    with pytest.raises(ValueError, match="DISPATCH_ARMED"):
        RuntimeExternalDispatchArmResult(
            PrimitiveOutcome.FACT_RETURNED,
            ExternalDispatchArmDecision.GRANTED_NOW,
            terminal_fact,
        )


def test_external_dispatch_arm_mapper_validates_decision_before_commit() -> None:
    row = _external_attempt_row(
        status="SUCCEEDED",
        decision="GRANTED_NOW",
    )
    repository, connection = _repository([row])

    with pytest.raises(SupervisorIntegrityOrContractViolation):
        repository.consume_and_arm_external_dispatch(_consume_and_arm_request())

    assert connection.trace == ["begin", "rollback", "close"]


@pytest.mark.parametrize(
    ("row", "field", "malicious_value"),
    [
        (_external_attempt_row(), "status", "UNKNOWN"),
        (_external_attempt_row(), "operation_kind", "ADMISSION_RESOLVE"),
        (_external_attempt_row(), "permit_attempt", True),
        (_external_attempt_row(), "armed_at", NOW.replace(tzinfo=None)),
        (
            _external_attempt_row(status="OUTCOME_UNKNOWN"),
            "evidence_kind",
            "PROVIDER_RECEIPT",
        ),
        (
            _external_attempt_row(status="OUTCOME_UNKNOWN"),
            "result_hash",
            HASH,
        ),
        (
            _external_attempt_row(status="OUTCOME_UNKNOWN"),
            "last_event_id",
            ARM_EVENT_ID,
        ),
        (
            _external_attempt_row(status="SUCCEEDED"),
            "source_fact_hash",
            "A" * 64,
        ),
    ],
)
def test_external_operation_attempt_mapper_rejects_noncanonical_rows(
    row: dict[str, object],
    field: str,
    malicious_value: object,
) -> None:
    row[field] = malicious_value
    repository, connection = _repository([row])

    with pytest.raises(SupervisorIntegrityOrContractViolation):
        repository.record_external_operation_outcome(_record_outcome_request())

    assert connection.trace == ["begin", "rollback", "close"]


@pytest.mark.parametrize(
    ("field", "malicious_value"),
    [
        ("dispatch_armed_count", -1),
        ("outcome_unknown_count", True),
        ("blocking", 1),
        ("oldest_blocking_at", None),
    ],
)
def test_external_operation_barrier_mapper_rejects_inconsistent_rows(
    field: str,
    malicious_value: object,
) -> None:
    row = _barrier_row()
    row[field] = malicious_value
    repository, connection = _repository([row])

    with pytest.raises(SupervisorIntegrityOrContractViolation):
        repository.load_external_operation_barrier(_barrier_request())

    assert connection.trace == ["begin", "rollback", "close"]


@pytest.mark.parametrize(
    ("method", "command", "database_error", "expected", "primitive"),
    [
        (
            "consume_and_arm_external_dispatch",
            _consume_and_arm_request(),
            psycopg.errors.UniqueViolation("conflict"),
            SupervisorCommandConflict,
            "consume_and_arm_runtime_external_dispatch",
        ),
        (
            "record_external_operation_outcome",
            _record_outcome_request(),
            psycopg.errors.InvalidParameterValue("invalid"),
            SupervisorInvalidCommand,
            "record_runtime_external_operation_outcome",
        ),
        (
            "reconcile_external_operation_outcome",
            _reconcile_outcome_request(),
            psycopg.errors.InsufficientPrivilege("permission"),
            SupervisorPermissionBoundaryMisconfigured,
            "reconcile_runtime_external_operation_outcome",
        ),
        (
            "load_external_operation_barrier",
            _barrier_request(),
            psycopg.errors.InvalidParameterValue("invalid"),
            SupervisorInvalidCommand,
            "load_runtime_external_operation_barrier",
        ),
    ],
)
def test_external_operation_sqlstates_map_to_each_named_primitive(
    method: str,
    command: object,
    database_error: psycopg.Error,
    expected: type[Exception],
    primitive: str,
) -> None:
    repository, connection = _repository([], execute_error=database_error)

    with pytest.raises(expected) as raised:
        getattr(repository, method)(command)

    assert raised.value.primitive.value == primitive
    assert connection.trace == ["begin", "rollback", "close"]


def test_authority_fact_constructors_reject_weak_enums_and_boolean_integers() -> None:
    with pytest.raises(ValueError, match="must be CANCELLING"):
        replace(
            _cancellation_authority_fact(),
            status=RuntimeStatus.RUNNING,
        )
    with pytest.raises(TypeError, match="must be an integer"):
        replace(
            _cancellation_authority_fact(),
            task_execution_generation=True,
        )
    with pytest.raises(TypeError, match="must be an OperationKind"):
        replace(
            _execution_authority_fact(),
            operation_kind="START",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="must be a MultitaskStrategy"):
        replace(
            _execution_authority_fact(),
            multitask_strategy="REJECT",  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="must be an integer"):
        replace(_execution_authority_fact(), lease_epoch=True)
    with pytest.raises(ValueError, match="must differ"):
        replace(
            _execution_authority_fact(),
            operation_kind=OperationKind.RETRY,
            predecessor_runtime_run_id=RUN_ID,
        )


@pytest.mark.parametrize(
    ("method", "command", "base_row", "field", "malicious_value"),
    [
        (
            "authorize_cancellation",
            AuthorizeRuntimeRunCancellationRequest(**_fenced_parameters()),
            _cancellation_authority_row(),
            "status",
            "RUNNING",
        ),
        (
            "authorize_cancellation",
            AuthorizeRuntimeRunCancellationRequest(**_fenced_parameters()),
            _cancellation_authority_row(),
            "lease_epoch",
            0,
        ),
        (
            "authorize_cancellation",
            AuthorizeRuntimeRunCancellationRequest(**_fenced_parameters()),
            _cancellation_authority_row(),
            "cancel_requested_at",
            NOW.replace(tzinfo=None),
        ),
        (
            "load_execution_authority",
            LoadRuntimeExecutionAuthorityRequest(**_fenced_parameters()),
            _execution_authority_row(),
            "request_hash",
            "not-a-sha256",
        ),
        (
            "load_execution_authority",
            LoadRuntimeExecutionAuthorityRequest(**_fenced_parameters()),
            _execution_authority_row(),
            "lease_owner",
            "",
        ),
        (
            "load_execution_authority",
            LoadRuntimeExecutionAuthorityRequest(**_fenced_parameters()),
            _execution_authority_row(),
            "task_execution_generation",
            0,
        ),
        (
            "load_execution_authority",
            LoadRuntimeExecutionAuthorityRequest(**_fenced_parameters()),
            _execution_authority_row(),
            "runtime_thread_revision",
            True,
        ),
        (
            "load_execution_authority",
            LoadRuntimeExecutionAuthorityRequest(**_fenced_parameters()),
            _execution_authority_row(),
            "runtime_type",
            "deerflow",
        ),
        (
            "load_execution_authority",
            LoadRuntimeExecutionAuthorityRequest(**_fenced_parameters()),
            _execution_authority_row(),
            "predecessor_runtime_run_id",
            EVENT_ID,
        ),
        (
            "load_execution_authority",
            LoadRuntimeExecutionAuthorityRequest(**_fenced_parameters()),
            _execution_authority_row(),
            "operation_kind",
            "RETRY",
        ),
        (
            "load_execution_authority",
            LoadRuntimeExecutionAuthorityRequest(**_fenced_parameters()),
            _execution_authority_row(),
            "admission_contract_version",
            "2.1",
        ),
        (
            "load_execution_authority",
            LoadRuntimeExecutionAuthorityRequest(**_fenced_parameters()),
            _execution_authority_row(),
            "admission_snapshot_id",
            UUID(int=0),
        ),
        (
            "load_execution_authority",
            LoadRuntimeExecutionAuthorityRequest(**_fenced_parameters()),
            _execution_authority_row(),
            "admission_snapshot_hash",
            "A" * 64,
        ),
    ],
)
def test_authority_mappers_reject_malicious_rows_and_roll_back(
    method: str,
    command: object,
    base_row: dict[str, object],
    field: str,
    malicious_value: object,
) -> None:
    row = dict(base_row)
    row[field] = malicious_value
    repository, connection = _repository([row])

    with pytest.raises(SupervisorIntegrityOrContractViolation):
        getattr(repository, method)(command)

    assert connection.trace == ["begin", "rollback", "close"]


def test_zero_rows_are_not_applied_without_guessing_cause() -> None:
    repository, connection = _repository([])

    result = repository.authorize(
        AuthorizeRuntimeRunRequest(**_fenced_parameters())
    )

    assert result.outcome == PrimitiveOutcome.NOT_APPLIED
    assert result.fact is None
    assert connection.trace == ["begin", "commit", "close"]


def test_event_row_maps_to_utc_and_deeply_frozen_canonical_json() -> None:
    repository, _connection = _repository([_event_row()])

    result = repository.append_event(
        AppendRuntimeRunEventRequest(
            **_fenced_parameters(),
            event_id=EVENT_ID,
            event_type=ProgressEventType.STEP_PROGRESS,
            event_version=1,
            payload=PAYLOAD,
        )
    )

    assert isinstance(result.fact, RuntimeRunEventFact)
    assert result.fact.occurred_at == NOW.astimezone(timezone.utc)
    assert result.fact.payload.canonical == '{"nested":{"items":[1,2]}}'
    assert isinstance(result.fact.payload.value, MappingProxyType)
    with pytest.raises(TypeError):
        result.fact.payload.value["nested"] = {}  # type: ignore[index]


def test_naive_database_timestamp_is_a_contract_violation_and_rolls_back() -> None:
    row = _run_row()
    row["created_at"] = datetime(2026, 8, 13)
    repository, connection = _repository([row])

    with pytest.raises(SupervisorIntegrityOrContractViolation):
        repository.authorize(AuthorizeRuntimeRunRequest(**_fenced_parameters()))

    assert connection.trace == ["begin", "rollback", "close"]


@pytest.mark.parametrize(
    ("database_error", "expected"),
    [
        (psycopg.errors.UniqueViolation("conflict"), SupervisorCommandConflict),
        (psycopg.errors.InvalidParameterValue("invalid"), SupervisorInvalidCommand),
        (psycopg.errors.FeatureNotSupported("unsupported"), SupervisorUnsupportedCommand),
        (
            psycopg.errors.InsufficientPrivilege("permission"),
            SupervisorPermissionBoundaryMisconfigured,
        ),
        (
            psycopg.errors.ObjectNotInPrerequisiteState("integrity"),
            SupervisorIntegrityOrContractViolation,
        ),
        (psycopg.errors.ForeignKeyViolation("integrity"), SupervisorIntegrityOrContractViolation),
        (psycopg.errors.SerializationFailure("retry"), SupervisorTransientConflict),
        (psycopg.errors.DeadlockDetected("retry"), SupervisorTransientConflict),
    ],
)
def test_sqlstate_mapping_is_stable_and_rolls_back(
    database_error: psycopg.Error,
    expected: type[Exception],
) -> None:
    repository, connection = _repository([], execute_error=database_error)

    with pytest.raises(expected):
        repository.authorize(AuthorizeRuntimeRunRequest(**_fenced_parameters()))

    assert connection.trace == ["begin", "rollback", "close"]


def test_connection_acquisition_failure_is_unavailable() -> None:
    repository = PostgresRunSupervisorRepository(
        lambda: (_ for _ in ()).throw(psycopg.OperationalError("offline"))
    )

    with pytest.raises(SupervisorUnavailable):
        repository.authorize(AuthorizeRuntimeRunRequest(**_fenced_parameters()))


def test_transaction_begin_connection_failure_is_unavailable() -> None:
    repository, connection = _repository(
        [],
        begin_error=psycopg.errors.ConnectionFailure("begin lost"),
    )

    with pytest.raises(SupervisorUnavailable):
        repository.authorize(AuthorizeRuntimeRunRequest(**_fenced_parameters()))

    assert connection.trace == ["begin", "close"]


def test_factory_connection_in_an_active_transaction_is_rejected_before_sql() -> None:
    repository, connection = _repository([_run_row()])
    connection.info.transaction_status = TransactionStatus.INTRANS

    with pytest.raises(SupervisorIntegrityOrContractViolation):
        repository.authorize(AuthorizeRuntimeRunRequest(**_fenced_parameters()))

    assert connection.statement == ""
    assert connection.trace == ["close"]


def test_stateful_primitive_connection_loss_after_execute_is_outcome_unknown() -> None:
    repository, connection = _repository(
        [],
        execute_error=psycopg.errors.ConnectionFailure("lost"),
    )

    with pytest.raises(SupervisorOutcomeUnknown):
        repository.renew_lease(
            RenewRuntimeRunLeaseRequest(
                **_fenced_parameters(),
                lease_seconds=30,
            )
        )

    assert connection.trace == ["begin", "rollback", "close"]


def test_stateful_primitive_commit_failure_is_outcome_unknown() -> None:
    repository, connection = _repository(
        [_run_row()],
        commit_error=psycopg.errors.ConnectionFailure("commit lost"),
    )

    with pytest.raises(SupervisorOutcomeUnknown):
        repository.renew_lease(
            RenewRuntimeRunLeaseRequest(
                **_fenced_parameters(),
                lease_seconds=30,
            )
        )

    assert connection.trace == ["begin", "commit", "close"]


@pytest.mark.parametrize(
    ("method", "command", "row"),
    [
        (
            "consume_and_arm_external_dispatch",
            _consume_and_arm_request(),
            _external_attempt_row(decision="GRANTED_NOW"),
        ),
        (
            "record_external_operation_outcome",
            _record_outcome_request(),
            _external_attempt_row(status="OUTCOME_UNKNOWN"),
        ),
        (
            "reconcile_external_operation_outcome",
            _reconcile_outcome_request(),
            _external_attempt_row(status="SUCCEEDED", source_fact_version=2),
        ),
    ],
)
@pytest.mark.parametrize("failure_stage", ["execute", "commit"])
def test_external_operation_writes_surface_connection_loss_as_outcome_unknown(
    method: str,
    command: object,
    row: dict[str, object],
    failure_stage: str,
) -> None:
    error = psycopg.errors.ConnectionFailure(f"{failure_stage} lost")
    kwargs = (
        {"execute_error": error}
        if failure_stage == "execute"
        else {"commit_error": error}
    )
    repository, connection = _repository([row], **kwargs)

    with pytest.raises(SupervisorOutcomeUnknown):
        getattr(repository, method)(command)

    assert connection.trace == (
        ["begin", "rollback", "close"]
        if failure_stage == "execute"
        else ["begin", "commit", "close"]
    )


@pytest.mark.parametrize("failure_stage", ["execute", "commit"])
def test_external_operation_barrier_connection_loss_is_retryable_unavailable(
    failure_stage: str,
) -> None:
    error = psycopg.errors.ConnectionFailure(f"{failure_stage} lost")
    kwargs = (
        {"execute_error": error}
        if failure_stage == "execute"
        else {"commit_error": error}
    )
    repository, connection = _repository([_barrier_row()], **kwargs)

    with pytest.raises(SupervisorUnavailable):
        repository.load_external_operation_barrier(_barrier_request())

    assert connection.trace == (
        ["begin", "rollback", "close"]
        if failure_stage == "execute"
        else ["begin", "commit", "close"]
    )


@pytest.mark.parametrize(
    ("method", "command", "row"),
    [
        (
            "authorize",
            AuthorizeRuntimeRunRequest(**_fenced_parameters()),
            _run_row(),
        ),
        (
            "authorize_cancellation",
            AuthorizeRuntimeRunCancellationRequest(**_fenced_parameters()),
            _cancellation_authority_row(),
        ),
        (
            "load_execution_authority",
            LoadRuntimeExecutionAuthorityRequest(**_fenced_parameters()),
            _execution_authority_row(),
        ),
    ],
)
@pytest.mark.parametrize("failure_stage", ["execute", "commit"])
def test_all_authority_reads_map_connection_loss_to_unavailable(
    method: str,
    command: object,
    row: dict[str, object],
    failure_stage: str,
) -> None:
    error = psycopg.errors.ConnectionFailure(f"{failure_stage} lost")
    kwargs = (
        {"execute_error": error}
        if failure_stage == "execute"
        else {"commit_error": error}
    )
    repository, connection = _repository([row], **kwargs)

    with pytest.raises(SupervisorUnavailable):
        getattr(repository, method)(command)

    assert connection.trace == (
        ["begin", "rollback", "close"]
        if failure_stage == "execute"
        else ["begin", "commit", "close"]
    )


@pytest.mark.parametrize(
    ("connection_error", "row", "expected_trace"),
    [
        (
            psycopg.errors.ConnectionFailure("read lost"),
            None,
            ["begin", "rollback", "close"],
        ),
        (
            psycopg.errors.ConnectionFailure("read commit lost"),
            _candidate_row(),
            ["begin", "commit", "close"],
        ),
    ],
)
def test_candidate_connection_loss_is_retryable_unavailable(
    connection_error: psycopg.Error,
    row: dict[str, object] | None,
    expected_trace: list[str],
) -> None:
    kwargs = (
        {"execute_error": connection_error}
        if row is None
        else {"commit_error": connection_error}
    )
    repository, connection = _repository([] if row is None else [row], **kwargs)

    with pytest.raises(SupervisorUnavailable):
        repository.select_next_candidate(
            SelectNextRuntimeRunCandidateRequest("runtime-v1", "agent-v1", "2.2")
        )

    assert connection.trace == expected_trace


def test_deferred_integrity_error_at_commit_is_a_known_contract_violation() -> None:
    repository, connection = _repository(
        [_run_row()],
        commit_error=psycopg.errors.ForeignKeyViolation("deferred failure"),
    )

    with pytest.raises(SupervisorIntegrityOrContractViolation):
        repository.authorize(AuthorizeRuntimeRunRequest(**_fenced_parameters()))

    assert connection.trace == ["begin", "commit", "close"]


def test_multiple_rows_are_a_contract_violation_and_roll_back() -> None:
    repository, connection = _repository([_run_row(), _run_row()])

    with pytest.raises(SupervisorIntegrityOrContractViolation):
        repository.authorize(AuthorizeRuntimeRunRequest(**_fenced_parameters()))

    assert connection.trace == ["begin", "rollback", "close"]


def test_close_failure_does_not_replace_a_successful_committed_result() -> None:
    repository, connection = _repository(
        [_run_row()],
        close_error=psycopg.OperationalError("close failed"),
    )

    result = repository.authorize(
        AuthorizeRuntimeRunRequest(**_fenced_parameters())
    )

    assert result.outcome == PrimitiveOutcome.FACT_RETURNED
    assert connection.trace == ["begin", "commit", "close"]


def test_close_failure_does_not_replace_the_primary_database_error() -> None:
    repository, connection = _repository(
        [],
        execute_error=psycopg.errors.UniqueViolation("conflict"),
        close_error=psycopg.OperationalError("close failed"),
    )

    with pytest.raises(SupervisorCommandConflict):
        repository.authorize(AuthorizeRuntimeRunRequest(**_fenced_parameters()))

    assert connection.trace == ["begin", "rollback", "close"]


def test_repository_source_cannot_read_or_mutate_supervisor_tables_directly() -> None:
    source = Path(inspect.getfile(PostgresRunSupervisorRepository)).read_text()
    upper = source.upper()

    assert "SELECT *" not in upper
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE "):
        assert verb not in upper
    called_primitives = set(
        re.findall(r"\bFROM\s+deer_runtime\.([a-z_]+)\s*\(", source, re.IGNORECASE)
    )
    assert called_primitives == {
        "admit_runtime_run",
        "claim_runtime_run",
        "renew_runtime_run_lease",
        "takeover_runtime_run",
        "authorize_runtime_run",
        "authorize_runtime_run_cancellation",
        "load_runtime_execution_authority",
        "issue_runtime_external_permit",
        "consume_and_authorize_runtime_external_permit",
        "consume_and_arm_runtime_external_dispatch",
        "record_runtime_external_operation_outcome",
        "reconcile_runtime_external_operation_outcome",
        "load_runtime_external_operation_barrier",
        "append_runtime_run_event",
        "record_runtime_checkpoint_ref",
        "request_runtime_run_cancel",
        "begin_runtime_run_cancellation",
        "complete_runtime_run",
        "fail_runtime_run",
        "finish_runtime_run_cancellation",
        "select_next_runtime_run_candidate",
    }
    direct_relation = re.compile(
        r"\b(?:FROM|JOIN)\s+deer_runtime\."
        r"(?:schema_migration|runtime_thread|runtime_run|runtime_run_event|"
        r"runtime_run_control|runtime_checkpoint_ref|runtime_external_intent|"
        r"runtime_external_permit_attempt|runtime_external_permit_event|"
        r"runtime_external_operation_attempt|runtime_external_operation_event)"
        r"\b(?!\s*\()",
        re.IGNORECASE,
    )
    assert direct_relation.search(source) is None


def test_frozen_json_rejects_non_string_keys_recursively() -> None:
    with pytest.raises(TypeError, match="keys must be strings"):
        FrozenJsonObject({"nested": {1: "coerced"}})  # type: ignore[dict-item]


def test_candidate_request_rejects_blank_or_oversized_compatibility_keys() -> None:
    with pytest.raises(ValueError):
        SelectNextRuntimeRunCandidateRequest("", "agent-v1", "2.2")
    with pytest.raises(ValueError):
        SelectNextRuntimeRunCandidateRequest("runtime-v1", "a" * 129, "2.2")
    with pytest.raises(ValueError, match="must be 2.2"):
        SelectNextRuntimeRunCandidateRequest("runtime-v1", "agent-v1", "2.1")


def test_admission_request_rejects_unbound_or_unsupported_snapshot_receipts() -> None:
    admission = _requests()[1][1]
    assert isinstance(admission, AdmitRuntimeRunRequest)

    with pytest.raises(ValueError, match="must be 2.2"):
        replace(admission, admission_contract_version="2.1")
    with pytest.raises(ValueError, match="nil UUID"):
        replace(admission, admission_snapshot_id=UUID(int=0))
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        replace(admission, admission_snapshot_hash="A" * 64)

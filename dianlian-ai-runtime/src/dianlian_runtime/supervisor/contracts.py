from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
import json
import re
from types import MappingProxyType
from typing import Generic, Mapping, Sequence, TypeVar
from uuid import UUID


_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_MAX_INTEGER = 2**31 - 1
_MAX_BIGINT = 2**63 - 1
_SUPPORTED_ADMISSION_CONTRACT_VERSION = "2.2"


class RuntimeStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_USER_INPUT = "WAITING_USER_INPUT"
    WAITING_AUTH = "WAITING_AUTH"
    PAUSED = "PAUSED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    CANCEL_OUTCOME_UNKNOWN = "CANCEL_OUTCOME_UNKNOWN"


class OperationKind(StrEnum):
    START = "START"
    CONTINUE = "CONTINUE"
    RETRY = "RETRY"
    REPLAN = "REPLAN"
    REPLACE = "REPLACE"


class MultitaskStrategy(StrEnum):
    REJECT = "REJECT"
    SAFE_QUEUE = "SAFE_QUEUE"
    INTERRUPT = "INTERRUPT"


class ProgressEventType(StrEnum):
    PLAN_CREATED = "PLAN_CREATED"
    STEP_STARTED = "STEP_STARTED"
    STEP_PROGRESS = "STEP_PROGRESS"


class CancellationTerminalStatus(StrEnum):
    CANCELLED = "CANCELLED"
    CANCEL_OUTCOME_UNKNOWN = "CANCEL_OUTCOME_UNKNOWN"


class ExternalOperation(StrEnum):
    ADMISSION_RESOLVE = "ADMISSION_RESOLVE"
    MODEL_INVOKE = "MODEL_INVOKE"
    TOOL_INVOKE = "TOOL_INVOKE"


class ExternalPermitStatus(StrEnum):
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"


class ExternalOperationAttemptStatus(StrEnum):
    DISPATCH_ARMED = "DISPATCH_ARMED"
    NOT_DISPATCHED = "NOT_DISPATCHED"
    SUCCEEDED = "SUCCEEDED"
    FAILED_CONFIRMED = "FAILED_CONFIRMED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"


class ExternalDispatchArmDecision(StrEnum):
    GRANTED_NOW = "GRANTED_NOW"
    DO_NOT_DISPATCH = "DO_NOT_DISPATCH"


class ExternalOutcomeEvidenceKind(StrEnum):
    JAVA_CANONICAL_FACT = "JAVA_CANONICAL_FACT"


class PrimitiveOutcome(StrEnum):
    FACT_RETURNED = "FACT_RETURNED"
    NOT_APPLIED = "NOT_APPLIED"


class SupervisorPrimitive(StrEnum):
    SELECT_CANDIDATE = "select_next_runtime_run_candidate"
    ADMIT = "admit_runtime_run"
    CLAIM = "claim_runtime_run"
    RENEW_LEASE = "renew_runtime_run_lease"
    TAKEOVER = "takeover_runtime_run"
    AUTHORIZE = "authorize_runtime_run"
    AUTHORIZE_CANCELLATION = "authorize_runtime_run_cancellation"
    LOAD_EXECUTION_AUTHORITY = "load_runtime_execution_authority"
    APPEND_EVENT = "append_runtime_run_event"
    RECORD_CHECKPOINT = "record_runtime_checkpoint_ref"
    REQUEST_CANCEL = "request_runtime_run_cancel"
    BEGIN_CANCELLATION = "begin_runtime_run_cancellation"
    COMPLETE = "complete_runtime_run"
    FAIL = "fail_runtime_run"
    FINISH_CANCELLATION = "finish_runtime_run_cancellation"
    ISSUE_EXTERNAL_PERMIT = "issue_runtime_external_permit"
    CONSUME_AND_AUTHORIZE_EXTERNAL_PERMIT = (
        "consume_and_authorize_runtime_external_permit"
    )
    CONSUME_AND_ARM_EXTERNAL_DISPATCH = (
        "consume_and_arm_runtime_external_dispatch"
    )
    RECORD_EXTERNAL_OPERATION_OUTCOME = (
        "record_runtime_external_operation_outcome"
    )
    RECONCILE_EXTERNAL_OPERATION_OUTCOME = (
        "reconcile_runtime_external_operation_outcome"
    )
    LOAD_EXTERNAL_OPERATION_BARRIER = (
        "load_runtime_external_operation_barrier"
    )


class SupervisorErrorCode(StrEnum):
    COMMAND_CONFLICT = "SUPERVISOR_COMMAND_CONFLICT"
    INVALID_COMMAND = "SUPERVISOR_INVALID_COMMAND"
    UNSUPPORTED_COMMAND = "SUPERVISOR_UNSUPPORTED_COMMAND"
    PERMISSION_BOUNDARY_MISCONFIGURED = "SUPERVISOR_PERMISSION_BOUNDARY_MISCONFIGURED"
    INTEGRITY_OR_CONTRACT_VIOLATION = "SUPERVISOR_INTEGRITY_OR_CONTRACT_VIOLATION"
    TRANSIENT_CONFLICT = "SUPERVISOR_TRANSIENT_CONFLICT"
    UNAVAILABLE = "SUPERVISOR_UNAVAILABLE"
    OUTCOME_UNKNOWN = "SUPERVISOR_OUTCOME_UNKNOWN"


class SupervisorRepositoryError(RuntimeError):
    def __init__(
        self,
        code: SupervisorErrorCode,
        primitive: SupervisorPrimitive,
        sqlstate: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.primitive = primitive
        self.sqlstate = sqlstate


class SupervisorCommandConflict(SupervisorRepositoryError):
    pass


class SupervisorInvalidCommand(SupervisorRepositoryError):
    pass


class SupervisorUnsupportedCommand(SupervisorRepositoryError):
    pass


class SupervisorPermissionBoundaryMisconfigured(SupervisorRepositoryError):
    pass


class SupervisorIntegrityOrContractViolation(SupervisorRepositoryError):
    pass


class SupervisorTransientConflict(SupervisorRepositoryError):
    pass


class SupervisorUnavailable(SupervisorRepositoryError):
    pass


class SupervisorOutcomeUnknown(SupervisorRepositoryError):
    pass


def _freeze_json(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _canonical_json(value: object) -> tuple[str, object]:
    _validate_json_keys(value)
    try:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exception:
        raise ValueError("value must be finite JSON data") from exception
    parsed = json.loads(canonical)
    return canonical, _freeze_json(parsed)


def _validate_json_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            _validate_json_keys(item)
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        for item in value:
            _validate_json_keys(item)


@dataclass(frozen=True, slots=True, init=False)
class FrozenJsonObject:
    canonical: str
    value: Mapping[str, object] = field(repr=False, compare=False)

    def __init__(self, value: Mapping[str, object]) -> None:
        if not isinstance(value, Mapping):
            raise TypeError("JSON object must be a mapping")
        canonical, frozen = _canonical_json(dict(value))
        if not isinstance(frozen, Mapping):
            raise TypeError("JSON object must have an object root")
        object.__setattr__(self, "canonical", canonical)
        object.__setattr__(self, "value", frozen)

    def to_builtin(self) -> dict[str, object]:
        return json.loads(self.canonical)


@dataclass(frozen=True, slots=True, init=False)
class FrozenJsonArray:
    canonical: str
    value: tuple[object, ...] = field(repr=False, compare=False)

    def __init__(self, value: Sequence[object]) -> None:
        if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
            raise TypeError("JSON array must be a non-string sequence")
        canonical, frozen = _canonical_json(list(value))
        if not isinstance(frozen, tuple):
            raise TypeError("JSON array must have an array root")
        object.__setattr__(self, "canonical", canonical)
        object.__setattr__(self, "value", frozen)

    def to_builtin(self) -> list[object]:
        return json.loads(self.canonical)


def _require_uuid(name: str, value: object, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if not isinstance(value, UUID):
        raise TypeError(f"{name} must be a UUID")
    if value.int == 0:
        raise ValueError(f"{name} must not be the nil UUID")


def _require_text(
    name: str,
    value: object,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if (not allow_empty and not value.strip()) or len(value) > maximum:
        raise ValueError(f"{name} is outside its allowed length")


def _require_positive(name: str, value: object, *, maximum: int | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 1 or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is outside its allowed range")


def _require_non_negative(
    name: str,
    value: object,
    *,
    maximum: int | None = None,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0 or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is outside its allowed range")


def _require_hash(name: str, value: object) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if _HASH_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _require_admission_contract_version(value: object) -> None:
    if not isinstance(value, str):
        raise TypeError("admission_contract_version must be a string")
    if value != _SUPPORTED_ADMISSION_CONTRACT_VERSION:
        raise ValueError("admission_contract_version must be 2.2")


def _require_code(name: str, value: object) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if _CODE_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a stable uppercase code")


def _require_aware_datetime(name: str, value: object) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError(f"{name} must be a timezone-aware datetime")


def _require_utc_datetime(name: str, value: object) -> None:
    _require_aware_datetime(name, value)
    assert isinstance(value, datetime)
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be normalized to UTC")


@dataclass(frozen=True, slots=True)
class SelectNextRuntimeRunCandidateRequest:
    runtime_version: str
    agent_name: str
    admission_contract_version: str

    def __post_init__(self) -> None:
        _require_text("runtime_version", self.runtime_version, maximum=128)
        _require_text("agent_name", self.agent_name, maximum=128)
        _require_admission_contract_version(self.admission_contract_version)


@dataclass(frozen=True, slots=True)
class AdmitRuntimeRunRequest:
    tenant_id: UUID
    runtime_thread_id: UUID
    task_run_id: UUID
    task_step_id: UUID
    agent_instance_id: UUID
    user_id: UUID
    conversation_id: UUID
    source_message_id: UUID | None
    runtime_thread_revision: int
    runtime_type: str
    runtime_agent_name: str
    capability_version_id: UUID
    prompt_version_id: UUID
    model_policy_id: UUID
    budget_reservation_id: UUID
    input_artifact_ids: FrozenJsonArray
    runtime_run_id: UUID
    task_execution_generation: int
    operation_kind: OperationKind
    multitask_strategy: MultitaskStrategy
    request_hash: str
    idempotency_key: str
    predecessor_runtime_run_id: UUID | None
    expected_checkpoint_id: str | None
    runtime_version: str
    agent_name: str
    admission_contract_version: str
    admission_snapshot_id: UUID
    admission_snapshot_hash: str
    accepted_event_id: UUID
    accepted_event_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "runtime_thread_id",
            "task_run_id",
            "task_step_id",
            "agent_instance_id",
            "user_id",
            "conversation_id",
            "capability_version_id",
            "prompt_version_id",
            "model_policy_id",
            "budget_reservation_id",
            "runtime_run_id",
            "admission_snapshot_id",
            "accepted_event_id",
        ):
            _require_uuid(name, getattr(self, name))
        _require_uuid("source_message_id", self.source_message_id, optional=True)
        _require_uuid(
            "predecessor_runtime_run_id",
            self.predecessor_runtime_run_id,
            optional=True,
        )
        _require_positive(
            "runtime_thread_revision",
            self.runtime_thread_revision,
            maximum=_MAX_BIGINT,
        )
        _require_positive(
            "task_execution_generation",
            self.task_execution_generation,
            maximum=_MAX_BIGINT,
        )
        _require_text("runtime_type", self.runtime_type, maximum=32)
        _require_code("runtime_type", self.runtime_type)
        _require_text("runtime_agent_name", self.runtime_agent_name, maximum=128)
        _require_text("idempotency_key", self.idempotency_key, maximum=200)
        _require_hash("request_hash", self.request_hash)
        if not isinstance(self.operation_kind, OperationKind):
            raise TypeError("operation_kind must be an OperationKind")
        if not isinstance(self.multitask_strategy, MultitaskStrategy):
            raise TypeError("multitask_strategy must be a MultitaskStrategy")
        if not isinstance(self.input_artifact_ids, FrozenJsonArray):
            raise TypeError("input_artifact_ids must be a FrozenJsonArray")
        if self.expected_checkpoint_id is not None:
            _require_text(
                "expected_checkpoint_id",
                self.expected_checkpoint_id,
                maximum=160,
            )
        _require_text("runtime_version", self.runtime_version, maximum=128)
        _require_text("agent_name", self.agent_name, maximum=128)
        _require_admission_contract_version(self.admission_contract_version)
        _require_hash("admission_snapshot_hash", self.admission_snapshot_hash)
        if not isinstance(self.accepted_event_payload, FrozenJsonObject):
            raise TypeError("accepted_event_payload must be a FrozenJsonObject")


@dataclass(frozen=True, slots=True)
class ClaimRuntimeRunRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    lease_owner: str
    lease_seconds: int
    started_event_id: UUID
    event_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        _validate_run_key(self.tenant_id, self.runtime_run_id)
        _require_text("lease_owner", self.lease_owner, maximum=160)
        _require_positive("lease_seconds", self.lease_seconds, maximum=3600)
        if self.lease_seconds < 5:
            raise ValueError("lease_seconds must be at least 5")
        _require_uuid("started_event_id", self.started_event_id)
        _require_json_object("event_payload", self.event_payload)


@dataclass(frozen=True, slots=True)
class RenewRuntimeRunLeaseRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    lease_owner: str
    lease_epoch: int
    lease_seconds: int

    def __post_init__(self) -> None:
        _validate_fence(self.tenant_id, self.runtime_run_id, self.lease_owner, self.lease_epoch)
        _require_positive("lease_seconds", self.lease_seconds, maximum=3600)
        if self.lease_seconds < 5:
            raise ValueError("lease_seconds must be at least 5")


@dataclass(frozen=True, slots=True)
class TakeoverRuntimeRunRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    new_lease_owner: str
    lease_seconds: int
    takeover_event_id: UUID
    event_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        _validate_run_key(self.tenant_id, self.runtime_run_id)
        _require_text("new_lease_owner", self.new_lease_owner, maximum=160)
        _require_positive("lease_seconds", self.lease_seconds, maximum=3600)
        if self.lease_seconds < 5:
            raise ValueError("lease_seconds must be at least 5")
        _require_uuid("takeover_event_id", self.takeover_event_id)
        _require_json_object("event_payload", self.event_payload)


@dataclass(frozen=True, slots=True)
class AuthorizeRuntimeRunRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    lease_owner: str
    lease_epoch: int

    def __post_init__(self) -> None:
        _validate_fence(self.tenant_id, self.runtime_run_id, self.lease_owner, self.lease_epoch)


@dataclass(frozen=True, slots=True)
class AuthorizeRuntimeRunCancellationRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    lease_owner: str
    lease_epoch: int

    def __post_init__(self) -> None:
        _validate_fence(self.tenant_id, self.runtime_run_id, self.lease_owner, self.lease_epoch)


@dataclass(frozen=True, slots=True)
class LoadRuntimeExecutionAuthorityRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    lease_owner: str
    lease_epoch: int

    def __post_init__(self) -> None:
        _validate_fence(self.tenant_id, self.runtime_run_id, self.lease_owner, self.lease_epoch)


@dataclass(frozen=True, slots=True)
class IssueRuntimeExternalPermitRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    lease_owner: str
    lease_epoch: int
    runtime_external_permit_id: UUID
    operation_kind: ExternalOperation
    intent_id: UUID
    request_hash: str
    requested_ttl_seconds: int
    issue_event_id: UUID

    def __post_init__(self) -> None:
        _validate_fence(
            self.tenant_id,
            self.runtime_run_id,
            self.lease_owner,
            self.lease_epoch,
        )
        _require_uuid(
            "runtime_external_permit_id",
            self.runtime_external_permit_id,
        )
        if not isinstance(self.operation_kind, ExternalOperation):
            raise TypeError("operation_kind must be an ExternalOperation")
        _require_uuid("intent_id", self.intent_id)
        _require_hash("request_hash", self.request_hash)
        _require_positive(
            "requested_ttl_seconds",
            self.requested_ttl_seconds,
            maximum=60,
        )
        _require_uuid("issue_event_id", self.issue_event_id)


@dataclass(frozen=True, slots=True)
class ConsumeRuntimeExternalPermitRequest:
    tenant_id: UUID
    runtime_external_permit_id: UUID
    runtime_run_id: UUID
    task_execution_generation: int
    lease_owner: str
    lease_epoch: int
    admission_snapshot_id: UUID
    admission_snapshot_hash: str
    operation_kind: ExternalOperation
    intent_id: UUID
    request_hash: str
    consume_event_id: UUID
    consumed_by: str

    def __post_init__(self) -> None:
        _validate_fence(
            self.tenant_id,
            self.runtime_run_id,
            self.lease_owner,
            self.lease_epoch,
        )
        _require_uuid(
            "runtime_external_permit_id",
            self.runtime_external_permit_id,
        )
        _require_positive(
            "task_execution_generation",
            self.task_execution_generation,
            maximum=_MAX_BIGINT,
        )
        if not isinstance(self.operation_kind, ExternalOperation):
            raise TypeError("operation_kind must be an ExternalOperation")
        if self.operation_kind != ExternalOperation.ADMISSION_RESOLVE:
            raise ValueError(
                "consume-and-authorize operation_kind must be ADMISSION_RESOLVE"
            )
        _require_uuid("intent_id", self.intent_id)
        _require_hash("request_hash", self.request_hash)
        _require_uuid("admission_snapshot_id", self.admission_snapshot_id)
        _require_hash("admission_snapshot_hash", self.admission_snapshot_hash)
        _require_uuid("consume_event_id", self.consume_event_id)
        _require_text("consumed_by", self.consumed_by, maximum=160)


@dataclass(frozen=True, slots=True)
class ConsumeAndArmRuntimeExternalDispatchRequest:
    tenant_id: UUID
    runtime_external_permit_id: UUID
    runtime_run_id: UUID
    task_execution_generation: int
    lease_owner: str
    lease_epoch: int
    admission_snapshot_id: UUID
    admission_snapshot_hash: str
    operation_kind: ExternalOperation
    intent_id: UUID
    request_hash: str
    arm_event_id: UUID
    armed_by: str

    def __post_init__(self) -> None:
        _validate_external_dispatch_binding(self)
        _require_uuid("arm_event_id", self.arm_event_id)
        _require_text("armed_by", self.armed_by, maximum=160)


@dataclass(frozen=True, slots=True)
class RecordRuntimeExternalOperationOutcomeRequest:
    tenant_id: UUID
    runtime_external_permit_id: UUID
    runtime_run_id: UUID
    task_execution_generation: int
    lease_owner: str
    lease_epoch: int
    admission_snapshot_id: UUID
    admission_snapshot_hash: str
    operation_kind: ExternalOperation
    intent_id: UUID
    request_hash: str
    outcome_event_id: UUID
    outcome_status: ExternalOperationAttemptStatus
    source_fact_id: UUID
    source_fact_version: int
    source_fact_hash: str
    outcome_code: str
    evidence_kind: ExternalOutcomeEvidenceKind
    result_hash: str | None
    recorded_by: str

    def __post_init__(self) -> None:
        _validate_external_dispatch_binding(self)
        _require_uuid("outcome_event_id", self.outcome_event_id)
        _validate_external_outcome(
            outcome_status=self.outcome_status,
            allowed_statuses={
                ExternalOperationAttemptStatus.NOT_DISPATCHED,
                ExternalOperationAttemptStatus.SUCCEEDED,
                ExternalOperationAttemptStatus.FAILED_CONFIRMED,
                ExternalOperationAttemptStatus.OUTCOME_UNKNOWN,
            },
            source_fact_id=self.source_fact_id,
            source_fact_version=self.source_fact_version,
            source_fact_hash=self.source_fact_hash,
            outcome_code=self.outcome_code,
            evidence_kind=self.evidence_kind,
            result_hash=self.result_hash,
            recorded_by=self.recorded_by,
        )


@dataclass(frozen=True, slots=True)
class ReconcileRuntimeExternalOperationOutcomeRequest:
    tenant_id: UUID
    runtime_external_permit_id: UUID
    runtime_run_id: UUID
    task_execution_generation: int
    lease_owner: str
    lease_epoch: int
    admission_snapshot_id: UUID
    admission_snapshot_hash: str
    operation_kind: ExternalOperation
    intent_id: UUID
    request_hash: str
    expected_unknown_event_id: UUID
    reconcile_event_id: UUID
    outcome_status: ExternalOperationAttemptStatus
    source_fact_id: UUID
    source_fact_version: int
    source_fact_hash: str
    outcome_code: str
    evidence_kind: ExternalOutcomeEvidenceKind
    result_hash: str | None
    recorded_by: str

    def __post_init__(self) -> None:
        _validate_external_dispatch_binding(self)
        _require_uuid("expected_unknown_event_id", self.expected_unknown_event_id)
        _require_uuid("reconcile_event_id", self.reconcile_event_id)
        _validate_external_outcome(
            outcome_status=self.outcome_status,
            allowed_statuses={
                ExternalOperationAttemptStatus.NOT_DISPATCHED,
                ExternalOperationAttemptStatus.SUCCEEDED,
                ExternalOperationAttemptStatus.FAILED_CONFIRMED,
            },
            source_fact_id=self.source_fact_id,
            source_fact_version=self.source_fact_version,
            source_fact_hash=self.source_fact_hash,
            outcome_code=self.outcome_code,
            evidence_kind=self.evidence_kind,
            result_hash=self.result_hash,
            recorded_by=self.recorded_by,
        )


@dataclass(frozen=True, slots=True)
class LoadRuntimeExternalOperationBarrierRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    task_execution_generation: int
    lease_owner: str
    lease_epoch: int

    def __post_init__(self) -> None:
        _validate_fence(
            self.tenant_id,
            self.runtime_run_id,
            self.lease_owner,
            self.lease_epoch,
        )
        _require_positive(
            "task_execution_generation",
            self.task_execution_generation,
            maximum=_MAX_BIGINT,
        )


@dataclass(frozen=True, slots=True)
class AppendRuntimeRunEventRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    lease_owner: str
    lease_epoch: int
    event_id: UUID
    event_type: ProgressEventType
    event_version: int
    payload: FrozenJsonObject

    def __post_init__(self) -> None:
        _validate_fence(self.tenant_id, self.runtime_run_id, self.lease_owner, self.lease_epoch)
        _require_uuid("event_id", self.event_id)
        if not isinstance(self.event_type, ProgressEventType):
            raise TypeError("event_type must be a ProgressEventType")
        _require_positive("event_version", self.event_version, maximum=32767)
        _require_json_object("payload", self.payload)


@dataclass(frozen=True, slots=True)
class RecordRuntimeCheckpointRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    lease_owner: str
    lease_epoch: int
    event_id: UUID
    checkpoint_id: str
    checkpoint_namespace: str
    checkpoint_schema_version: str
    event_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        _validate_fence(self.tenant_id, self.runtime_run_id, self.lease_owner, self.lease_epoch)
        _require_uuid("event_id", self.event_id)
        _require_text("checkpoint_id", self.checkpoint_id, maximum=160)
        _require_text(
            "checkpoint_namespace",
            self.checkpoint_namespace,
            maximum=160,
            allow_empty=True,
        )
        _require_text(
            "checkpoint_schema_version",
            self.checkpoint_schema_version,
            maximum=64,
        )
        _require_json_object("event_payload", self.event_payload)


@dataclass(frozen=True, slots=True)
class RequestRuntimeRunCancelRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    cancel_request_id: UUID
    actor_id: UUID
    reason_code: str
    expected_run_version: int
    idempotency_key: str
    request_hash: str
    event_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        _validate_run_key(self.tenant_id, self.runtime_run_id)
        _require_uuid("cancel_request_id", self.cancel_request_id)
        _require_uuid("actor_id", self.actor_id)
        _require_code("reason_code", self.reason_code)
        _require_positive(
            "expected_run_version",
            self.expected_run_version,
            maximum=_MAX_BIGINT,
        )
        _require_text("idempotency_key", self.idempotency_key, maximum=200)
        _require_hash("request_hash", self.request_hash)
        _require_json_object("event_payload", self.event_payload)


@dataclass(frozen=True, slots=True)
class BeginRuntimeRunCancellationRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    lease_owner: str
    lease_epoch: int
    event_id: UUID
    event_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        _validate_fenced_event(self)


@dataclass(frozen=True, slots=True)
class CompleteRuntimeRunRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    lease_owner: str
    lease_epoch: int
    event_id: UUID
    terminal_reason: str
    event_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        _validate_fenced_event(self)
        _require_code("terminal_reason", self.terminal_reason)


@dataclass(frozen=True, slots=True)
class FailRuntimeRunRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    lease_owner: str
    lease_epoch: int
    event_id: UUID
    terminal_reason: str
    failure_code: str
    event_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        _validate_fenced_event(self)
        _require_code("terminal_reason", self.terminal_reason)
        _require_code("failure_code", self.failure_code)


@dataclass(frozen=True, slots=True)
class FinishRuntimeRunCancellationRequest:
    tenant_id: UUID
    runtime_run_id: UUID
    lease_owner: str
    lease_epoch: int
    terminal_status: CancellationTerminalStatus
    event_id: UUID
    terminal_reason: str
    event_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        _validate_fenced_event(self)
        if not isinstance(self.terminal_status, CancellationTerminalStatus):
            raise TypeError("terminal_status must be a CancellationTerminalStatus")
        _require_code("terminal_reason", self.terminal_reason)


def _validate_run_key(tenant_id: UUID, runtime_run_id: UUID) -> None:
    _require_uuid("tenant_id", tenant_id)
    _require_uuid("runtime_run_id", runtime_run_id)


def _validate_fence(
    tenant_id: UUID,
    runtime_run_id: UUID,
    lease_owner: str,
    lease_epoch: int,
) -> None:
    _validate_run_key(tenant_id, runtime_run_id)
    _require_text("lease_owner", lease_owner, maximum=160)
    _require_positive("lease_epoch", lease_epoch, maximum=_MAX_BIGINT)


def _validate_external_dispatch_binding(request: object) -> None:
    _validate_fence(
        getattr(request, "tenant_id"),
        getattr(request, "runtime_run_id"),
        getattr(request, "lease_owner"),
        getattr(request, "lease_epoch"),
    )
    _require_uuid(
        "runtime_external_permit_id",
        getattr(request, "runtime_external_permit_id"),
    )
    _require_positive(
        "task_execution_generation",
        getattr(request, "task_execution_generation"),
        maximum=_MAX_BIGINT,
    )
    _require_uuid(
        "admission_snapshot_id",
        getattr(request, "admission_snapshot_id"),
    )
    _require_hash(
        "admission_snapshot_hash",
        getattr(request, "admission_snapshot_hash"),
    )
    operation_kind = getattr(request, "operation_kind")
    if not isinstance(operation_kind, ExternalOperation):
        raise TypeError("operation_kind must be an ExternalOperation")
    if operation_kind not in {
        ExternalOperation.MODEL_INVOKE,
        ExternalOperation.TOOL_INVOKE,
    }:
        raise ValueError("operation_kind must be MODEL_INVOKE or TOOL_INVOKE")
    _require_uuid("intent_id", getattr(request, "intent_id"))
    _require_hash("request_hash", getattr(request, "request_hash"))


def _validate_external_outcome(
    *,
    outcome_status: object,
    allowed_statuses: set[ExternalOperationAttemptStatus],
    source_fact_id: object,
    source_fact_version: object,
    source_fact_hash: object,
    outcome_code: object,
    evidence_kind: object,
    result_hash: object,
    recorded_by: object,
) -> None:
    if not isinstance(outcome_status, ExternalOperationAttemptStatus):
        raise TypeError("outcome_status must be an ExternalOperationAttemptStatus")
    if outcome_status not in allowed_statuses:
        raise ValueError("outcome_status is not allowed for this operation")
    _require_uuid("source_fact_id", source_fact_id)
    _require_positive(
        "source_fact_version",
        source_fact_version,
        maximum=_MAX_BIGINT,
    )
    _require_hash("source_fact_hash", source_fact_hash)
    _require_code("outcome_code", outcome_code)
    if not isinstance(evidence_kind, ExternalOutcomeEvidenceKind):
        raise TypeError("evidence_kind must be an ExternalOutcomeEvidenceKind")
    if outcome_status in {
        ExternalOperationAttemptStatus.SUCCEEDED,
        ExternalOperationAttemptStatus.FAILED_CONFIRMED,
    }:
        _require_hash("result_hash", result_hash)
    elif result_hash is not None:
        raise ValueError("result_hash must be null for this outcome_status")
    _require_text("recorded_by", recorded_by, maximum=160)


def _require_json_object(name: str, value: object) -> None:
    if not isinstance(value, FrozenJsonObject):
        raise TypeError(f"{name} must be a FrozenJsonObject")


def _validate_fenced_event(request: object) -> None:
    _validate_fence(
        getattr(request, "tenant_id"),
        getattr(request, "runtime_run_id"),
        getattr(request, "lease_owner"),
        getattr(request, "lease_epoch"),
    )
    _require_uuid("event_id", getattr(request, "event_id"))
    _require_json_object("event_payload", getattr(request, "event_payload"))


@dataclass(frozen=True, slots=True)
class RuntimeRunCandidateFact:
    tenant_id: UUID
    runtime_run_id: UUID

    def __post_init__(self) -> None:
        _validate_run_key(self.tenant_id, self.runtime_run_id)


@dataclass(frozen=True, slots=True)
class RuntimeCancellationAuthorityFact:
    tenant_id: UUID
    runtime_run_id: UUID
    runtime_thread_id: UUID
    task_step_id: UUID
    task_execution_generation: int
    status: RuntimeStatus
    lease_owner: str
    lease_epoch: int
    run_version: int
    cancel_requested_at: datetime

    def __post_init__(self) -> None:
        _validate_run_key(self.tenant_id, self.runtime_run_id)
        _require_uuid("runtime_thread_id", self.runtime_thread_id)
        _require_uuid("task_step_id", self.task_step_id)
        _require_positive(
            "task_execution_generation",
            self.task_execution_generation,
            maximum=_MAX_BIGINT,
        )
        if not isinstance(self.status, RuntimeStatus):
            raise TypeError("status must be a RuntimeStatus")
        if self.status != RuntimeStatus.CANCELLING:
            raise ValueError("cancellation authority status must be CANCELLING")
        _require_text("lease_owner", self.lease_owner, maximum=160)
        _require_positive("lease_epoch", self.lease_epoch, maximum=_MAX_BIGINT)
        _require_positive("run_version", self.run_version, maximum=_MAX_BIGINT)
        _require_aware_datetime("cancel_requested_at", self.cancel_requested_at)


@dataclass(frozen=True, slots=True)
class RuntimeExecutionAuthorityFact:
    tenant_id: UUID
    runtime_run_id: UUID
    runtime_thread_id: UUID
    task_run_id: UUID
    task_step_id: UUID
    task_execution_generation: int
    agent_instance_id: UUID
    user_id: UUID
    conversation_id: UUID
    source_message_id: UUID | None
    runtime_thread_revision: int
    runtime_type: str
    runtime_agent_name: str
    capability_version_id: UUID
    prompt_version_id: UUID
    model_policy_id: UUID
    budget_reservation_id: UUID
    operation_kind: OperationKind
    multitask_strategy: MultitaskStrategy
    request_hash: str
    idempotency_key: str
    predecessor_runtime_run_id: UUID | None
    expected_checkpoint_id: str | None
    runtime_version: str
    agent_name: str
    lease_owner: str
    lease_epoch: int
    admission_contract_version: str
    admission_snapshot_id: UUID
    admission_snapshot_hash: str

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "runtime_run_id",
            "runtime_thread_id",
            "task_run_id",
            "task_step_id",
            "agent_instance_id",
            "user_id",
            "conversation_id",
            "capability_version_id",
            "prompt_version_id",
            "model_policy_id",
            "budget_reservation_id",
            "admission_snapshot_id",
        ):
            _require_uuid(name, getattr(self, name))
        _require_uuid("source_message_id", self.source_message_id, optional=True)
        _require_uuid(
            "predecessor_runtime_run_id",
            self.predecessor_runtime_run_id,
            optional=True,
        )
        _require_positive(
            "task_execution_generation",
            self.task_execution_generation,
            maximum=_MAX_BIGINT,
        )
        _require_positive(
            "runtime_thread_revision",
            self.runtime_thread_revision,
            maximum=_MAX_BIGINT,
        )
        if not isinstance(self.operation_kind, OperationKind):
            raise TypeError("operation_kind must be an OperationKind")
        if not isinstance(self.multitask_strategy, MultitaskStrategy):
            raise TypeError("multitask_strategy must be a MultitaskStrategy")
        _require_hash("request_hash", self.request_hash)
        _require_text("idempotency_key", self.idempotency_key, maximum=200)
        _require_text("runtime_type", self.runtime_type, maximum=32)
        _require_code("runtime_type", self.runtime_type)
        _require_text("runtime_agent_name", self.runtime_agent_name, maximum=128)
        _require_text("runtime_version", self.runtime_version, maximum=128)
        _require_text("agent_name", self.agent_name, maximum=128)
        if self.expected_checkpoint_id is not None:
            _require_text(
                "expected_checkpoint_id",
                self.expected_checkpoint_id,
                maximum=160,
            )
        _require_text("lease_owner", self.lease_owner, maximum=160)
        _require_positive("lease_epoch", self.lease_epoch, maximum=_MAX_BIGINT)
        _require_admission_contract_version(self.admission_contract_version)
        _require_hash("admission_snapshot_hash", self.admission_snapshot_hash)
        if (
            self.operation_kind == OperationKind.START
            and self.predecessor_runtime_run_id is not None
        ):
            raise ValueError("START execution authority cannot have a predecessor")
        if (
            self.operation_kind != OperationKind.START
            and self.predecessor_runtime_run_id is None
        ):
            raise ValueError("non-START execution authority requires a predecessor")
        if self.predecessor_runtime_run_id == self.runtime_run_id:
            raise ValueError("execution authority predecessor must differ from runtime_run_id")


@dataclass(frozen=True, slots=True)
class RuntimeExternalPermitFact:
    tenant_id: UUID
    runtime_external_permit_id: UUID
    runtime_run_id: UUID
    runtime_thread_id: UUID
    task_step_id: UUID
    task_execution_generation: int
    admission_contract_version: str
    admission_snapshot_id: UUID
    admission_snapshot_hash: str
    operation_kind: ExternalOperation
    intent_id: UUID
    request_hash: str
    lease_owner: str
    lease_epoch: int
    permit_attempt: int
    status: ExternalPermitStatus
    requested_ttl_seconds: int
    issued_at: datetime
    expires_at: datetime
    issue_event_id: UUID
    consume_event_id: UUID | None
    consumed_by: str | None
    consumed_at: datetime | None
    updated_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "runtime_external_permit_id",
            "runtime_run_id",
            "runtime_thread_id",
            "task_step_id",
            "admission_snapshot_id",
            "intent_id",
            "issue_event_id",
        ):
            _require_uuid(name, getattr(self, name))
        _require_uuid("consume_event_id", self.consume_event_id, optional=True)
        _require_positive(
            "task_execution_generation",
            self.task_execution_generation,
            maximum=_MAX_BIGINT,
        )
        _require_admission_contract_version(self.admission_contract_version)
        _require_hash("admission_snapshot_hash", self.admission_snapshot_hash)
        if not isinstance(self.operation_kind, ExternalOperation):
            raise TypeError("operation_kind must be an ExternalOperation")
        _require_hash("request_hash", self.request_hash)
        _require_text("lease_owner", self.lease_owner, maximum=160)
        _require_positive("lease_epoch", self.lease_epoch, maximum=_MAX_BIGINT)
        _require_positive("permit_attempt", self.permit_attempt, maximum=_MAX_INTEGER)
        if not isinstance(self.status, ExternalPermitStatus):
            raise TypeError("status must be an ExternalPermitStatus")
        _require_positive(
            "requested_ttl_seconds",
            self.requested_ttl_seconds,
            maximum=60,
        )
        for name in ("issued_at", "expires_at", "updated_at"):
            _require_aware_datetime(name, getattr(self, name))
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be later than issued_at")
        if self.updated_at < self.issued_at:
            raise ValueError("updated_at must not precede issued_at")
        if self.consumed_by is not None:
            _require_text("consumed_by", self.consumed_by, maximum=160)
        if self.consumed_at is not None:
            _require_aware_datetime("consumed_at", self.consumed_at)
        consumed_fields = (
            self.consume_event_id,
            self.consumed_by,
            self.consumed_at,
        )
        if self.status == ExternalPermitStatus.ISSUED and any(
            value is not None for value in consumed_fields
        ):
            raise ValueError("ISSUED permit cannot contain consumption facts")
        if self.status == ExternalPermitStatus.CONSUMED and any(
            value is None for value in consumed_fields
        ):
            raise ValueError("CONSUMED permit requires complete consumption facts")
        if self.consumed_at is not None and self.consumed_at < self.issued_at:
            raise ValueError("consumed_at must not precede issued_at")
        if self.consumed_at is not None and self.consumed_at >= self.expires_at:
            raise ValueError("consumed_at must precede expires_at")
        if self.consumed_at is not None and self.updated_at < self.consumed_at:
            raise ValueError("updated_at must not precede consumed_at")


@dataclass(frozen=True, slots=True)
class RuntimeExternalOperationAttemptFact:
    tenant_id: UUID
    runtime_external_permit_id: UUID
    runtime_run_id: UUID
    operation_kind: ExternalOperation
    intent_id: UUID
    permit_attempt: int
    task_execution_generation: int
    admission_snapshot_id: UUID
    admission_snapshot_hash: str
    request_hash: str
    lease_owner: str
    lease_epoch: int
    arm_event_id: UUID
    armed_by: str
    armed_at: datetime
    status: ExternalOperationAttemptStatus
    last_event_id: UUID
    source_fact_id: UUID | None
    source_fact_version: int | None
    source_fact_hash: str | None
    outcome_code: str | None
    evidence_kind: ExternalOutcomeEvidenceKind | None
    result_hash: str | None
    recorded_by: str | None
    outcome_recorded_at: datetime | None
    updated_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "runtime_external_permit_id",
            "runtime_run_id",
            "intent_id",
            "admission_snapshot_id",
            "arm_event_id",
            "last_event_id",
        ):
            _require_uuid(name, getattr(self, name))
        if not isinstance(self.operation_kind, ExternalOperation):
            raise TypeError("operation_kind must be an ExternalOperation")
        if self.operation_kind not in {
            ExternalOperation.MODEL_INVOKE,
            ExternalOperation.TOOL_INVOKE,
        }:
            raise ValueError("operation_kind must be MODEL_INVOKE or TOOL_INVOKE")
        _require_positive("permit_attempt", self.permit_attempt, maximum=_MAX_INTEGER)
        _require_positive(
            "task_execution_generation",
            self.task_execution_generation,
            maximum=_MAX_BIGINT,
        )
        _require_hash("admission_snapshot_hash", self.admission_snapshot_hash)
        _require_hash("request_hash", self.request_hash)
        _require_text("lease_owner", self.lease_owner, maximum=160)
        _require_positive("lease_epoch", self.lease_epoch, maximum=_MAX_BIGINT)
        _require_text("armed_by", self.armed_by, maximum=160)
        _require_utc_datetime("armed_at", self.armed_at)
        _require_utc_datetime("updated_at", self.updated_at)
        if self.updated_at < self.armed_at:
            raise ValueError("updated_at must not precede armed_at")
        if not isinstance(self.status, ExternalOperationAttemptStatus):
            raise TypeError("status must be an ExternalOperationAttemptStatus")

        outcome_fields = (
            self.source_fact_id,
            self.source_fact_version,
            self.source_fact_hash,
            self.outcome_code,
            self.evidence_kind,
            self.recorded_by,
            self.outcome_recorded_at,
        )
        if self.status == ExternalOperationAttemptStatus.DISPATCH_ARMED:
            if any(value is not None for value in outcome_fields) or self.result_hash is not None:
                raise ValueError("DISPATCH_ARMED attempt cannot contain outcome facts")
            if self.last_event_id != self.arm_event_id:
                raise ValueError("DISPATCH_ARMED last_event_id must equal arm_event_id")
            return

        if any(value is None for value in outcome_fields):
            raise ValueError("terminal attempt requires complete canonical outcome facts")
        if self.last_event_id == self.arm_event_id:
            raise ValueError("terminal attempt last_event_id must differ from arm_event_id")
        assert self.source_fact_id is not None
        assert self.source_fact_version is not None
        assert self.source_fact_hash is not None
        assert self.outcome_code is not None
        assert self.evidence_kind is not None
        assert self.recorded_by is not None
        assert self.outcome_recorded_at is not None
        _validate_external_outcome(
            outcome_status=self.status,
            allowed_statuses={
                ExternalOperationAttemptStatus.NOT_DISPATCHED,
                ExternalOperationAttemptStatus.SUCCEEDED,
                ExternalOperationAttemptStatus.FAILED_CONFIRMED,
                ExternalOperationAttemptStatus.OUTCOME_UNKNOWN,
            },
            source_fact_id=self.source_fact_id,
            source_fact_version=self.source_fact_version,
            source_fact_hash=self.source_fact_hash,
            outcome_code=self.outcome_code,
            evidence_kind=self.evidence_kind,
            result_hash=self.result_hash,
            recorded_by=self.recorded_by,
        )
        _require_utc_datetime("outcome_recorded_at", self.outcome_recorded_at)
        if self.outcome_recorded_at < self.armed_at:
            raise ValueError("outcome_recorded_at must not precede armed_at")
        if self.updated_at < self.outcome_recorded_at:
            raise ValueError("updated_at must not precede outcome_recorded_at")


@dataclass(frozen=True, slots=True)
class RuntimeExternalOperationBarrierFact:
    tenant_id: UUID
    runtime_run_id: UUID
    task_execution_generation: int
    lease_owner: str
    lease_epoch: int
    dispatch_armed_count: int
    outcome_unknown_count: int
    blocking: bool
    oldest_blocking_at: datetime | None

    def __post_init__(self) -> None:
        _validate_fence(
            self.tenant_id,
            self.runtime_run_id,
            self.lease_owner,
            self.lease_epoch,
        )
        _require_positive(
            "task_execution_generation",
            self.task_execution_generation,
            maximum=_MAX_BIGINT,
        )
        _require_non_negative(
            "dispatch_armed_count",
            self.dispatch_armed_count,
            maximum=_MAX_BIGINT,
        )
        _require_non_negative(
            "outcome_unknown_count",
            self.outcome_unknown_count,
            maximum=_MAX_BIGINT,
        )
        if not isinstance(self.blocking, bool):
            raise TypeError("blocking must be a boolean")
        expected_blocking = self.dispatch_armed_count + self.outcome_unknown_count > 0
        if self.blocking != expected_blocking:
            raise ValueError("blocking must match the durable blocking counts")
        if self.blocking:
            _require_utc_datetime("oldest_blocking_at", self.oldest_blocking_at)
        elif self.oldest_blocking_at is not None:
            raise ValueError("oldest_blocking_at must be null when not blocking")


@dataclass(frozen=True, slots=True)
class RuntimeRunFact:
    tenant_id: UUID
    runtime_run_id: UUID
    runtime_thread_id: UUID
    task_step_id: UUID
    task_execution_generation: int
    status: RuntimeStatus
    operation_kind: OperationKind
    multitask_strategy: MultitaskStrategy
    request_hash: str
    idempotency_key: str
    predecessor_runtime_run_id: UUID | None
    expected_checkpoint_id: str | None
    current_checkpoint_id: str | None
    current_checkpoint_sequence_no: int | None
    next_event_sequence_no: int
    event_retention_floor_sequence: int
    run_version: int
    terminal_reason: str | None
    terminal_event_id: UUID | None
    lease_owner: str | None
    lease_until: datetime | None
    lease_epoch: int
    heartbeat_at: datetime | None
    attempt: int
    runtime_version: str
    agent_name: str
    failure_code: str | None
    cancel_requested_at: datetime | None
    started_at: datetime | None
    terminal_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeRunEventFact:
    tenant_id: UUID
    runtime_run_id: UUID
    runtime_thread_id: UUID
    event_id: UUID
    sequence_no: int
    event_type: str
    event_version: int
    run_version: int
    lease_owner: str | None
    lease_epoch: int
    checkpoint_id: str | None
    payload: FrozenJsonObject
    occurred_at: datetime
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeCheckpointFact:
    tenant_id: UUID
    runtime_run_id: UUID
    runtime_thread_id: UUID
    checkpoint_id: str
    checkpoint_namespace: str
    sequence_no: int
    event_id: UUID
    run_version: int
    lease_epoch: int
    checkpoint_schema_version: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeRunControlFact:
    tenant_id: UUID
    control_id: UUID
    runtime_run_id: UUID
    runtime_thread_id: UUID
    control_type: str
    actor_id: UUID
    reason_code: str
    expected_run_version: int
    idempotency_key: str
    request_hash: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeExternalDispatchArmResult:
    outcome: PrimitiveOutcome
    decision: ExternalDispatchArmDecision | None
    fact: RuntimeExternalOperationAttemptFact | None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, PrimitiveOutcome):
            raise TypeError("outcome must be a PrimitiveOutcome")
        if self.outcome == PrimitiveOutcome.NOT_APPLIED:
            if self.decision is not None or self.fact is not None:
                raise ValueError("NOT_APPLIED arm result cannot contain a decision or fact")
            return
        if self.outcome != PrimitiveOutcome.FACT_RETURNED:
            raise ValueError("unsupported arm result outcome")
        if not isinstance(self.decision, ExternalDispatchArmDecision):
            raise TypeError("decision must be an ExternalDispatchArmDecision")
        if not isinstance(self.fact, RuntimeExternalOperationAttemptFact):
            raise TypeError("fact must be a RuntimeExternalOperationAttemptFact")
        if (
            self.decision == ExternalDispatchArmDecision.GRANTED_NOW
            and self.fact.status != ExternalOperationAttemptStatus.DISPATCH_ARMED
        ):
            raise ValueError("GRANTED_NOW must return a DISPATCH_ARMED attempt")


FactT = TypeVar("FactT")


@dataclass(frozen=True, slots=True)
class PrimitiveResult(Generic[FactT]):
    outcome: PrimitiveOutcome
    fact: FactT | None

    def __post_init__(self) -> None:
        success = self.outcome == PrimitiveOutcome.FACT_RETURNED
        if success is (self.fact is None):
            raise ValueError("primitive outcome and fact presence are inconsistent")

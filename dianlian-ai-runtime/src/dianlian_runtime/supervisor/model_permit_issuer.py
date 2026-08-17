from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, cast
from uuid import UUID, uuid5

from dianlian_runtime.supervisor.contracts import (
    ExternalOperation,
    ExternalPermitStatus,
    IssueRuntimeExternalPermitRequest,
    PrimitiveOutcome,
    PrimitiveResult,
    RuntimeExecutionAuthorityFact,
    RuntimeExternalPermitFact,
    SupervisorOutcomeUnknown,
    SupervisorTransientConflict,
    SupervisorUnavailable,
)
from dianlian_runtime.supervisor.driver import DriverFence


MODEL_PERMIT_FENCE_REQUIRED = "MODEL_PERMIT_FENCE_REQUIRED"
MODEL_PERMIT_OUTCOME_UNKNOWN = "MODEL_PERMIT_OUTCOME_UNKNOWN"
_IDENTITY_SCHEMA_VERSION = "dianlian.model-permit-identity.v1"
_MODEL_PERMIT_NAMESPACE = UUID("34a93061-0557-5b96-83ba-d0f0e61af43c")
_MODEL_ISSUE_EVENT_NAMESPACE = UUID("c27a58e2-b3bd-5797-a325-b91640e5bd4d")
_MODEL_ARM_EVENT_NAMESPACE = UUID("25cde90a-7432-54c8-986b-aa0890495481")


class ModelPermitFenceRequired(RuntimeError):
    """The caller must stop; this boundary never creates a replacement attempt."""

    code = MODEL_PERMIT_FENCE_REQUIRED

    def __init__(self) -> None:
        super().__init__(MODEL_PERMIT_FENCE_REQUIRED)


class ModelPermitOutcomeUnknown(RuntimeError):
    code = MODEL_PERMIT_OUTCOME_UNKNOWN

    def __init__(self) -> None:
        super().__init__(MODEL_PERMIT_OUTCOME_UNKNOWN)


class ModelPermitDisposition(StrEnum):
    CURRENT_ISSUED = "CURRENT_ISSUED"
    HISTORICAL_CONSUMED = "HISTORICAL_CONSUMED"


class ModelPermitRepository(Protocol):
    def issue_external_permit(
        self,
        request: IssueRuntimeExternalPermitRequest,
    ) -> PrimitiveResult[RuntimeExternalPermitFact]: ...


@dataclass(frozen=True, slots=True)
class IssueModelPermitRequest:
    """Caller-owned model intent, already durable before permit issuance.

    ``intent_id`` is the persisted stable model-call id. ``request_hash`` is the
    canonical business-intent hash and excludes permit, lease and event metadata.
    """

    authority: RuntimeExecutionAuthorityFact
    fence: DriverFence
    intent_id: UUID
    request_hash: str
    requested_ttl_seconds: int

    def __post_init__(self) -> None:
        if not isinstance(self.authority, RuntimeExecutionAuthorityFact):
            raise TypeError("authority must be a RuntimeExecutionAuthorityFact")
        if not isinstance(self.fence, DriverFence):
            raise TypeError("fence must be a DriverFence")
        authority = self.authority
        fence = self.fence
        if (
            authority.tenant_id != fence.tenant_id
            or authority.runtime_run_id != fence.runtime_run_id
            or authority.task_execution_generation
            != fence.task_execution_generation
            or authority.lease_owner != fence.lease_owner
            or authority.lease_epoch != fence.lease_epoch
            or authority.admission_contract_version
            != fence.admission_contract_version
            or authority.admission_snapshot_id != fence.admission_snapshot_id
            or authority.admission_snapshot_hash
            != fence.admission_snapshot_hash
        ):
            raise ValueError("execution authority and fence do not match")
        _require_uuid("intent_id", self.intent_id)
        _require_hash("request_hash", self.request_hash)
        if (
            isinstance(self.requested_ttl_seconds, bool)
            or not isinstance(self.requested_ttl_seconds, int)
        ):
            raise TypeError("requested_ttl_seconds must be an integer")
        if not 1 <= self.requested_ttl_seconds <= 60:
            raise ValueError("requested_ttl_seconds is outside its allowed range")


@dataclass(frozen=True, slots=True)
class ModelPermitReceipt:
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
    issue_event_id: UUID
    arm_event_id: UUID
    permit_attempt: int
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "runtime_external_permit_id",
            "runtime_run_id",
            "admission_snapshot_id",
            "intent_id",
            "issue_event_id",
            "arm_event_id",
        ):
            _require_uuid(name, getattr(self, name))
        _require_positive(
            "task_execution_generation",
            self.task_execution_generation,
        )
        _require_text("lease_owner", self.lease_owner, maximum=160)
        _require_positive("lease_epoch", self.lease_epoch)
        _require_hash("admission_snapshot_hash", self.admission_snapshot_hash)
        if not isinstance(self.operation_kind, ExternalOperation):
            raise TypeError("operation_kind must be an ExternalOperation")
        if self.operation_kind != ExternalOperation.MODEL_INVOKE:
            raise ValueError("model permit receipt operation must be MODEL_INVOKE")
        _require_hash("request_hash", self.request_hash)
        _require_positive(
            "permit_attempt",
            self.permit_attempt,
            maximum=2**31 - 1,
        )
        _require_aware_datetime("issued_at", self.issued_at)
        _require_aware_datetime("expires_at", self.expires_at)
        if self.expires_at <= self.issued_at:
            raise ValueError("model permit receipt expiry must follow issuance")


@dataclass(frozen=True, slots=True)
class ModelPermitIssueResult:
    """Closed recovery routing result; the receipt remains status-free.

    A historical observation never authorizes provider dispatch. Recovery must
    pass a fresh live Driver gate and replay the exact Supervisor operation; it
    must not persist an observed permit status into an HTTP body or receipt store.
    """

    disposition: ModelPermitDisposition
    receipt: ModelPermitReceipt
    provider_dispatch_allowed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ModelPermitDisposition):
            raise TypeError("disposition must be a ModelPermitDisposition")
        if not isinstance(self.receipt, ModelPermitReceipt):
            raise TypeError("receipt must be a ModelPermitReceipt")
        if not isinstance(self.provider_dispatch_allowed, bool):
            raise TypeError("provider_dispatch_allowed must be a boolean")
        expected = self.disposition == ModelPermitDisposition.CURRENT_ISSUED
        if self.provider_dispatch_allowed != expected:
            raise ValueError(
                "provider_dispatch_allowed does not match permit disposition"
            )


class DormantModelPermitIssuer:
    """Pure v1.2 permit boundary, composed only by governed opt-in.

    It performs exactly one repository call. A response-loss retry belongs to the
    caller and must reuse the same request so every derived identity remains stable.
    The supplied DriverFence is structural evidence only, not a live authorization;
    the future driver must authorize immediately before calling this boundary.
    Activation remains blocked until that gate and the Java recovery path are composed.
    """

    def __init__(
        self,
        repository: ModelPermitRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(getattr(repository, "issue_external_permit", None)):
            raise TypeError("repository must provide issue_external_permit")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def issue(self, request: IssueModelPermitRequest) -> ModelPermitIssueResult:
        if not isinstance(request, IssueModelPermitRequest):
            raise TypeError("request must be an IssueModelPermitRequest")
        authority = request.authority
        identities = derive_model_permit_identities(
            tenant_id=authority.tenant_id,
            runtime_run_id=authority.runtime_run_id,
            task_execution_generation=authority.task_execution_generation,
            lease_owner=authority.lease_owner,
            lease_epoch=authority.lease_epoch,
            admission_snapshot_id=authority.admission_snapshot_id,
            admission_snapshot_hash=authority.admission_snapshot_hash,
            intent_id=request.intent_id,
            request_hash=request.request_hash,
        )
        command = IssueRuntimeExternalPermitRequest(
            tenant_id=authority.tenant_id,
            runtime_run_id=authority.runtime_run_id,
            lease_owner=authority.lease_owner,
            lease_epoch=authority.lease_epoch,
            runtime_external_permit_id=identities.runtime_external_permit_id,
            operation_kind=ExternalOperation.MODEL_INVOKE,
            intent_id=request.intent_id,
            request_hash=request.request_hash,
            requested_ttl_seconds=request.requested_ttl_seconds,
            issue_event_id=identities.issue_event_id,
        )
        try:
            result = self._repository.issue_external_permit(command)
        except (
            SupervisorOutcomeUnknown,
            SupervisorTransientConflict,
            SupervisorUnavailable,
        ) as exception:
            raise ModelPermitOutcomeUnknown() from exception
        except Exception as exception:
            raise ModelPermitFenceRequired() from exception
        if not isinstance(result, PrimitiveResult):
            raise ModelPermitFenceRequired()
        if result.outcome != PrimitiveOutcome.FACT_RETURNED or result.fact is None:
            raise ModelPermitFenceRequired()
        try:
            now_value = self._clock()
            _require_aware_datetime("clock result", now_value)
            now = cast(datetime, now_value)
        except Exception as exception:
            raise ModelPermitFenceRequired() from exception
        fact = result.fact
        if not isinstance(fact, RuntimeExternalPermitFact):
            raise ModelPermitFenceRequired()
        if _fact_matches_current_issued(
            fact,
            request=request,
            identities=identities,
            now=now,
        ):
            return ModelPermitIssueResult(
                disposition=ModelPermitDisposition.CURRENT_ISSUED,
                receipt=_receipt_from_fact(
                    fact,
                    arm_event_id=identities.arm_event_id,
                ),
                provider_dispatch_allowed=True,
            )
        historical_identities = derive_model_permit_identities(
            tenant_id=fact.tenant_id,
            runtime_run_id=fact.runtime_run_id,
            task_execution_generation=fact.task_execution_generation,
            lease_owner=fact.lease_owner,
            lease_epoch=fact.lease_epoch,
            admission_snapshot_id=fact.admission_snapshot_id,
            admission_snapshot_hash=fact.admission_snapshot_hash,
            intent_id=fact.intent_id,
            request_hash=fact.request_hash,
        )
        if not _fact_matches_historical_consumed(
            fact,
            request=request,
            identities=historical_identities,
            now=now,
        ):
            raise ModelPermitFenceRequired()
        return ModelPermitIssueResult(
            disposition=ModelPermitDisposition.HISTORICAL_CONSUMED,
            receipt=_receipt_from_fact(
                fact,
                arm_event_id=cast(UUID, fact.consume_event_id),
            ),
            provider_dispatch_allowed=False,
        )


def _receipt_from_fact(
    fact: RuntimeExternalPermitFact,
    *,
    arm_event_id: UUID,
) -> ModelPermitReceipt:
    return ModelPermitReceipt(
        tenant_id=fact.tenant_id,
        runtime_external_permit_id=fact.runtime_external_permit_id,
        runtime_run_id=fact.runtime_run_id,
        task_execution_generation=fact.task_execution_generation,
        lease_owner=fact.lease_owner,
        lease_epoch=fact.lease_epoch,
        admission_snapshot_id=fact.admission_snapshot_id,
        admission_snapshot_hash=fact.admission_snapshot_hash,
        operation_kind=fact.operation_kind,
        intent_id=fact.intent_id,
        request_hash=fact.request_hash,
        issue_event_id=fact.issue_event_id,
        arm_event_id=arm_event_id,
        permit_attempt=fact.permit_attempt,
        issued_at=fact.issued_at,
        expires_at=fact.expires_at,
    )


@dataclass(frozen=True, slots=True)
class _ModelPermitIdentities:
    runtime_external_permit_id: UUID
    issue_event_id: UUID
    arm_event_id: UUID


def derive_model_permit_identities(
    *,
    tenant_id: UUID,
    runtime_run_id: UUID,
    task_execution_generation: int,
    lease_owner: str,
    lease_epoch: int,
    admission_snapshot_id: UUID,
    admission_snapshot_hash: str,
    intent_id: UUID,
    request_hash: str,
) -> _ModelPermitIdentities:
    """Derive unambiguous one-shot identities for one model intent and lease epoch."""

    _require_uuid("tenant_id", tenant_id)
    _require_uuid("runtime_run_id", runtime_run_id)
    _require_uuid("admission_snapshot_id", admission_snapshot_id)
    _require_uuid("intent_id", intent_id)
    _require_positive("task_execution_generation", task_execution_generation)
    _require_text("lease_owner", lease_owner, maximum=160)
    _require_positive("lease_epoch", lease_epoch)
    _require_hash("admission_snapshot_hash", admission_snapshot_hash)
    _require_hash("request_hash", request_hash)
    binding = [
        _IDENTITY_SCHEMA_VERSION,
        str(tenant_id),
        str(runtime_run_id),
        task_execution_generation,
        lease_owner,
        lease_epoch,
        str(admission_snapshot_id),
        admission_snapshot_hash,
        ExternalOperation.MODEL_INVOKE.value,
        str(intent_id),
        request_hash,
    ]
    return _ModelPermitIdentities(
        runtime_external_permit_id=_derive_id(
            _MODEL_PERMIT_NAMESPACE,
            "MODEL_PERMIT",
            binding,
        ),
        issue_event_id=_derive_id(
            _MODEL_ISSUE_EVENT_NAMESPACE,
            "MODEL_PERMIT_ISSUED",
            binding,
        ),
        arm_event_id=_derive_id(
            _MODEL_ARM_EVENT_NAMESPACE,
            "MODEL_DISPATCH_ARMED",
            binding,
        ),
    )


def _derive_id(namespace: UUID, purpose: str, binding: list[object]) -> UUID:
    name = json.dumps(
        [purpose, *binding],
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return uuid5(namespace, name)


def _fact_matches_logical_intent(
    fact: RuntimeExternalPermitFact,
    *,
    request: IssueModelPermitRequest,
) -> bool:
    authority = request.authority
    return (
        fact.tenant_id == authority.tenant_id
        and fact.runtime_run_id == authority.runtime_run_id
        and fact.runtime_thread_id == authority.runtime_thread_id
        and fact.task_step_id == authority.task_step_id
        and fact.task_execution_generation == authority.task_execution_generation
        and fact.admission_contract_version
        == authority.admission_contract_version
        and fact.admission_snapshot_id == authority.admission_snapshot_id
        and fact.admission_snapshot_hash == authority.admission_snapshot_hash
        and fact.operation_kind == ExternalOperation.MODEL_INVOKE
        and fact.intent_id == request.intent_id
        and fact.request_hash == request.request_hash
    )


def _fact_matches_current_issued(
    fact: RuntimeExternalPermitFact,
    *,
    request: IssueModelPermitRequest,
    identities: _ModelPermitIdentities,
    now: datetime,
) -> bool:
    authority = request.authority
    return (
        _fact_matches_logical_intent(fact, request=request)
        and fact.runtime_external_permit_id
        == identities.runtime_external_permit_id
        and fact.lease_owner == authority.lease_owner
        and fact.lease_epoch == authority.lease_epoch
        and isinstance(fact.permit_attempt, int)
        and not isinstance(fact.permit_attempt, bool)
        and fact.permit_attempt >= 1
        and fact.status == ExternalPermitStatus.ISSUED
        and fact.requested_ttl_seconds == request.requested_ttl_seconds
        and fact.issue_event_id == identities.issue_event_id
        and fact.expires_at - fact.issued_at
        == timedelta(seconds=request.requested_ttl_seconds)
        and fact.issued_at <= now < fact.expires_at
        and fact.updated_at == fact.issued_at
    )


def _fact_matches_historical_consumed(
    fact: RuntimeExternalPermitFact,
    *,
    request: IssueModelPermitRequest,
    identities: _ModelPermitIdentities,
    now: datetime,
) -> bool:
    return (
        _fact_matches_logical_intent(fact, request=request)
        and fact.status == ExternalPermitStatus.CONSUMED
        and (
            fact.lease_epoch < request.authority.lease_epoch
            or (
                fact.lease_epoch == request.authority.lease_epoch
                and fact.lease_owner == request.authority.lease_owner
            )
        )
        and fact.runtime_external_permit_id
        == identities.runtime_external_permit_id
        and fact.issue_event_id == identities.issue_event_id
        and fact.consume_event_id == identities.arm_event_id
        and fact.expires_at - fact.issued_at
        == timedelta(seconds=fact.requested_ttl_seconds)
        and fact.consumed_at is not None
        and fact.consumed_at == fact.updated_at
        and fact.consumed_at <= now
    )


def _require_uuid(name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{name} must be a UUID")
    if value.int == 0:
        raise ValueError(f"{name} must not be the nil UUID")


def _require_hash(name: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _require_positive(
    name: str,
    value: object,
    *,
    maximum: int = 2**63 - 1,
) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not 1 <= value <= maximum:
        raise ValueError(f"{name} is outside its allowed range")


def _require_text(name: str, value: object, *, maximum: int) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value.strip() or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{name} is outside its allowed range")


def _require_aware_datetime(name: str, value: object) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")

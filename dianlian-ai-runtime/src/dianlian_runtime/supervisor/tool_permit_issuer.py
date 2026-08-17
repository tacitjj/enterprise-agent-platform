from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, cast
from uuid import NAMESPACE_URL, UUID, uuid5

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


TOOL_PERMIT_FENCE_REQUIRED = "TOOL_PERMIT_FENCE_REQUIRED"
TOOL_PERMIT_OUTCOME_UNKNOWN = "TOOL_PERMIT_OUTCOME_UNKNOWN"
_IDENTITY_SCHEMA_VERSION = "dianlian.tool-permit-identity.v1"
_TOOL_PERMIT_NAMESPACE = uuid5(NAMESPACE_URL, "dianlian:tool-permit:v1")
_TOOL_ISSUE_EVENT_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "dianlian:tool-permit-issued:v1",
)
_TOOL_ARM_EVENT_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "dianlian:tool-dispatch-armed:v1",
)


class ToolPermitFenceRequired(RuntimeError):
    code = TOOL_PERMIT_FENCE_REQUIRED

    def __init__(self) -> None:
        super().__init__(TOOL_PERMIT_FENCE_REQUIRED)


class ToolPermitOutcomeUnknown(RuntimeError):
    code = TOOL_PERMIT_OUTCOME_UNKNOWN

    def __init__(self) -> None:
        super().__init__(TOOL_PERMIT_OUTCOME_UNKNOWN)


class ToolPermitDisposition(StrEnum):
    CURRENT_ISSUED = "CURRENT_ISSUED"
    HISTORICAL_CONSUMED = "HISTORICAL_CONSUMED"


class ToolPermitRepository(Protocol):
    def issue_external_permit(
        self,
        request: IssueRuntimeExternalPermitRequest,
    ) -> PrimitiveResult[RuntimeExternalPermitFact]: ...


@dataclass(frozen=True, slots=True)
class IssueToolPermitRequest:
    """One durable H12 tool intent bound to the current structural fence."""

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
        _require_positive(
            "requested_ttl_seconds",
            self.requested_ttl_seconds,
            maximum=60,
        )


@dataclass(frozen=True, slots=True)
class ToolPermitReceipt:
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
        if self.operation_kind != ExternalOperation.TOOL_INVOKE:
            raise ValueError("tool permit receipt operation must be TOOL_INVOKE")
        _require_hash("request_hash", self.request_hash)
        _require_positive("permit_attempt", self.permit_attempt, maximum=2**31 - 1)
        _require_aware_datetime("issued_at", self.issued_at)
        _require_aware_datetime("expires_at", self.expires_at)
        if self.expires_at <= self.issued_at:
            raise ValueError("tool permit receipt expiry must follow issuance")


@dataclass(frozen=True, slots=True)
class ToolPermitIssueResult:
    disposition: ToolPermitDisposition
    receipt: ToolPermitReceipt
    tool_dispatch_allowed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, ToolPermitDisposition):
            raise TypeError("disposition must be a ToolPermitDisposition")
        if not isinstance(self.receipt, ToolPermitReceipt):
            raise TypeError("receipt must be a ToolPermitReceipt")
        if not isinstance(self.tool_dispatch_allowed, bool):
            raise TypeError("tool_dispatch_allowed must be a boolean")
        expected = self.disposition == ToolPermitDisposition.CURRENT_ISSUED
        if self.tool_dispatch_allowed != expected:
            raise ValueError(
                "tool_dispatch_allowed does not match permit disposition"
            )


class DormantToolPermitIssuer:
    """One-call TOOL_INVOKE permit boundary, composed only by governed opt-in.

    The caller must pass a fresh live gate immediately before this synchronous
    boundary. Historical consumed evidence is returned only for exact Java and
    Supervisor convergence; it never authorizes another Tool executor call.
    """

    def __init__(
        self,
        repository: ToolPermitRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(getattr(repository, "issue_external_permit", None)):
            raise TypeError("repository must provide issue_external_permit")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def issue(self, request: IssueToolPermitRequest) -> ToolPermitIssueResult:
        if not isinstance(request, IssueToolPermitRequest):
            raise TypeError("request must be an IssueToolPermitRequest")
        authority = request.authority
        identities = derive_tool_permit_identities(
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
            operation_kind=ExternalOperation.TOOL_INVOKE,
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
            raise ToolPermitOutcomeUnknown() from exception
        except Exception as exception:
            raise ToolPermitFenceRequired() from exception
        if (
            not isinstance(result, PrimitiveResult)
            or result.outcome != PrimitiveOutcome.FACT_RETURNED
            or not isinstance(result.fact, RuntimeExternalPermitFact)
        ):
            raise ToolPermitFenceRequired()
        try:
            now_value = self._clock()
            _require_aware_datetime("clock result", now_value)
            now = cast(datetime, now_value)
        except Exception as exception:
            raise ToolPermitFenceRequired() from exception

        fact = result.fact
        if _matches_current_issued(
            fact,
            request=request,
            identities=identities,
            now=now,
        ):
            return ToolPermitIssueResult(
                ToolPermitDisposition.CURRENT_ISSUED,
                _receipt_from_fact(fact, arm_event_id=identities.arm_event_id),
                True,
            )

        historical_identities = derive_tool_permit_identities(
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
        if not _matches_historical_consumed(
            fact,
            request=request,
            identities=historical_identities,
            now=now,
        ):
            raise ToolPermitFenceRequired()
        return ToolPermitIssueResult(
            ToolPermitDisposition.HISTORICAL_CONSUMED,
            _receipt_from_fact(fact, arm_event_id=cast(UUID, fact.consume_event_id)),
            False,
        )


@dataclass(frozen=True, slots=True)
class ToolPermitIdentities:
    runtime_external_permit_id: UUID
    issue_event_id: UUID
    arm_event_id: UUID


def derive_tool_permit_identities(
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
) -> ToolPermitIdentities:
    _require_uuid("tenant_id", tenant_id)
    _require_uuid("runtime_run_id", runtime_run_id)
    _require_positive("task_execution_generation", task_execution_generation)
    _require_text("lease_owner", lease_owner, maximum=160)
    _require_positive("lease_epoch", lease_epoch)
    _require_uuid("admission_snapshot_id", admission_snapshot_id)
    _require_hash("admission_snapshot_hash", admission_snapshot_hash)
    _require_uuid("intent_id", intent_id)
    _require_hash("request_hash", request_hash)
    binding: list[object] = [
        _IDENTITY_SCHEMA_VERSION,
        str(tenant_id),
        str(runtime_run_id),
        task_execution_generation,
        lease_owner,
        lease_epoch,
        str(admission_snapshot_id),
        admission_snapshot_hash,
        ExternalOperation.TOOL_INVOKE.value,
        str(intent_id),
        request_hash,
    ]
    return ToolPermitIdentities(
        _derive_id(_TOOL_PERMIT_NAMESPACE, "TOOL_PERMIT", binding),
        _derive_id(_TOOL_ISSUE_EVENT_NAMESPACE, "TOOL_PERMIT_ISSUED", binding),
        _derive_id(_TOOL_ARM_EVENT_NAMESPACE, "TOOL_DISPATCH_ARMED", binding),
    )


def _receipt_from_fact(
    fact: RuntimeExternalPermitFact,
    *,
    arm_event_id: UUID,
) -> ToolPermitReceipt:
    return ToolPermitReceipt(
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


def _matches_logical_intent(
    fact: RuntimeExternalPermitFact,
    *,
    request: IssueToolPermitRequest,
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
        == "2.2"
        and fact.admission_snapshot_id == authority.admission_snapshot_id
        and fact.admission_snapshot_hash == authority.admission_snapshot_hash
        and fact.operation_kind == ExternalOperation.TOOL_INVOKE
        and fact.intent_id == request.intent_id
        and fact.request_hash == request.request_hash
    )


def _matches_current_issued(
    fact: RuntimeExternalPermitFact,
    *,
    request: IssueToolPermitRequest,
    identities: ToolPermitIdentities,
    now: datetime,
) -> bool:
    authority = request.authority
    return (
        _matches_logical_intent(fact, request=request)
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


def _matches_historical_consumed(
    fact: RuntimeExternalPermitFact,
    *,
    request: IssueToolPermitRequest,
    identities: ToolPermitIdentities,
    now: datetime,
) -> bool:
    return (
        _matches_logical_intent(fact, request=request)
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


def _derive_id(namespace: UUID, purpose: str, binding: list[object]) -> UUID:
    return uuid5(
        namespace,
        json.dumps(
            [purpose, *binding],
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ),
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

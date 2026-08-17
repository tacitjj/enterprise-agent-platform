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


ADMISSION_PERMIT_FENCE_REQUIRED = "ADMISSION_PERMIT_FENCE_REQUIRED"
ADMISSION_PERMIT_OUTCOME_UNKNOWN = "ADMISSION_PERMIT_OUTCOME_UNKNOWN"
_IDENTITY_SCHEMA_VERSION = "dianlian.admission-permit-identity.v1"


class AdmissionPermitFenceRequired(RuntimeError):
    code = ADMISSION_PERMIT_FENCE_REQUIRED

    def __init__(self) -> None:
        super().__init__(ADMISSION_PERMIT_FENCE_REQUIRED)


class AdmissionPermitOutcomeUnknown(RuntimeError):
    code = ADMISSION_PERMIT_OUTCOME_UNKNOWN

    def __init__(self) -> None:
        super().__init__(ADMISSION_PERMIT_OUTCOME_UNKNOWN)


class AdmissionPermitDisposition(StrEnum):
    CURRENT_ISSUED = "CURRENT_ISSUED"
    CURRENT_CONSUMED = "CURRENT_CONSUMED"
    HISTORICAL_CONSUMED = "HISTORICAL_CONSUMED"


class AdmissionPermitRepository(Protocol):
    def issue_external_permit(
        self,
        request: IssueRuntimeExternalPermitRequest,
    ) -> PrimitiveResult[RuntimeExternalPermitFact]: ...


@dataclass(frozen=True, slots=True)
class IssueAdmissionPermitRequest:
    """Current structural authority for one immutable admission snapshot read."""

    authority: RuntimeExecutionAuthorityFact
    fence: DriverFence
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
        _require_positive(
            "requested_ttl_seconds",
            self.requested_ttl_seconds,
            maximum=60,
        )


@dataclass(frozen=True, slots=True)
class AdmissionPermitIssueResult:
    """Classifies a permit fact without turning historical evidence into authority."""

    disposition: AdmissionPermitDisposition
    permit: RuntimeExternalPermitFact
    manifest_resolve_allowed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, AdmissionPermitDisposition):
            raise TypeError("disposition must be an AdmissionPermitDisposition")
        if not isinstance(self.permit, RuntimeExternalPermitFact):
            raise TypeError("permit must be a RuntimeExternalPermitFact")
        if not isinstance(self.manifest_resolve_allowed, bool):
            raise TypeError("manifest_resolve_allowed must be a boolean")
        expected = self.disposition in {
            AdmissionPermitDisposition.CURRENT_ISSUED,
            AdmissionPermitDisposition.CURRENT_CONSUMED,
        }
        if self.manifest_resolve_allowed != expected:
            raise ValueError(
                "manifest_resolve_allowed does not match permit disposition"
            )


@dataclass(frozen=True, slots=True)
class AdmissionPermitIdentities:
    runtime_external_permit_id: UUID
    issue_event_id: UUID
    consume_event_id: UUID


class DormantAdmissionPermitIssuer:
    """One-call ADMISSION_RESOLVE boundary, composed only by governed opt-in.

    ``manifest_resolve_allowed`` only means that the returned fact is eligible for
    the existing Java manifest client. The future driver must still pass a fresh
    live gate immediately before issuance and the Java current-authority wrapper
    remains the linear authorization point. Historical consumed facts are exact
    reconciliation evidence only.
    """

    def __init__(
        self,
        repository: AdmissionPermitRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(getattr(repository, "issue_external_permit", None)):
            raise TypeError("repository must provide issue_external_permit")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def issue(
        self,
        request: IssueAdmissionPermitRequest,
    ) -> AdmissionPermitIssueResult:
        if not isinstance(request, IssueAdmissionPermitRequest):
            raise TypeError("request must be an IssueAdmissionPermitRequest")
        authority = request.authority
        identities = derive_admission_permit_identities(
            tenant_id=authority.tenant_id,
            runtime_run_id=authority.runtime_run_id,
            task_execution_generation=authority.task_execution_generation,
            lease_owner=authority.lease_owner,
            lease_epoch=authority.lease_epoch,
            admission_snapshot_id=authority.admission_snapshot_id,
            admission_snapshot_hash=authority.admission_snapshot_hash,
        )
        command = IssueRuntimeExternalPermitRequest(
            tenant_id=authority.tenant_id,
            runtime_run_id=authority.runtime_run_id,
            lease_owner=authority.lease_owner,
            lease_epoch=authority.lease_epoch,
            runtime_external_permit_id=identities.runtime_external_permit_id,
            operation_kind=ExternalOperation.ADMISSION_RESOLVE,
            intent_id=authority.admission_snapshot_id,
            request_hash=authority.admission_snapshot_hash,
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
            raise AdmissionPermitOutcomeUnknown() from exception
        except Exception as exception:
            raise AdmissionPermitFenceRequired() from exception
        if (
            not isinstance(result, PrimitiveResult)
            or result.outcome != PrimitiveOutcome.FACT_RETURNED
            or not isinstance(result.fact, RuntimeExternalPermitFact)
        ):
            raise AdmissionPermitFenceRequired()
        try:
            now_value = self._clock()
            _require_aware_datetime("clock result", now_value)
            now = cast(datetime, now_value)
        except Exception as exception:
            raise AdmissionPermitFenceRequired() from exception

        fact = result.fact
        if _matches_current_issued(
            fact,
            request=request,
            identities=identities,
            now=now,
        ):
            return AdmissionPermitIssueResult(
                AdmissionPermitDisposition.CURRENT_ISSUED,
                fact,
                True,
            )
        if _matches_current_consumed(
            fact,
            request=request,
            identities=identities,
            now=now,
        ):
            return AdmissionPermitIssueResult(
                AdmissionPermitDisposition.CURRENT_CONSUMED,
                fact,
                True,
            )

        historical_identities = derive_admission_permit_identities(
            tenant_id=fact.tenant_id,
            runtime_run_id=fact.runtime_run_id,
            task_execution_generation=fact.task_execution_generation,
            lease_owner=fact.lease_owner,
            lease_epoch=fact.lease_epoch,
            admission_snapshot_id=fact.admission_snapshot_id,
            admission_snapshot_hash=fact.admission_snapshot_hash,
        )
        if not _matches_historical_consumed(
            fact,
            request=request,
            identities=historical_identities,
            now=now,
        ):
            raise AdmissionPermitFenceRequired()
        return AdmissionPermitIssueResult(
            AdmissionPermitDisposition.HISTORICAL_CONSUMED,
            fact,
            False,
        )


def derive_admission_permit_identities(
    *,
    tenant_id: UUID,
    runtime_run_id: UUID,
    task_execution_generation: int,
    lease_owner: str,
    lease_epoch: int,
    admission_snapshot_id: UUID,
    admission_snapshot_hash: str,
) -> AdmissionPermitIdentities:
    _require_uuid("tenant_id", tenant_id)
    _require_uuid("runtime_run_id", runtime_run_id)
    _require_positive(
        "task_execution_generation",
        task_execution_generation,
    )
    _require_text("lease_owner", lease_owner, maximum=160)
    _require_positive("lease_epoch", lease_epoch)
    _require_uuid("admission_snapshot_id", admission_snapshot_id)
    _require_hash("admission_snapshot_hash", admission_snapshot_hash)
    binding: list[object] = [
        _IDENTITY_SCHEMA_VERSION,
        str(tenant_id),
        str(runtime_run_id),
        task_execution_generation,
        lease_owner,
        lease_epoch,
        str(admission_snapshot_id),
        admission_snapshot_hash,
        ExternalOperation.ADMISSION_RESOLVE.value,
        str(admission_snapshot_id),
        admission_snapshot_hash,
    ]
    permit_id = _derive_id("ADMISSION_PERMIT", binding)
    return AdmissionPermitIdentities(
        runtime_external_permit_id=permit_id,
        issue_event_id=_derive_id("ADMISSION_PERMIT_ISSUED", binding),
        consume_event_id=uuid5(
            NAMESPACE_URL,
            f"dianlian:admission-manifest:consume:{permit_id}",
        ),
    )


def _derive_id(purpose: str, binding: list[object]) -> UUID:
    name = json.dumps(
        [purpose, *binding],
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return uuid5(NAMESPACE_URL, name)


def _matches_logical_binding(
    fact: RuntimeExternalPermitFact,
    *,
    request: IssueAdmissionPermitRequest,
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
        and fact.operation_kind == ExternalOperation.ADMISSION_RESOLVE
        and fact.intent_id == authority.admission_snapshot_id
        and fact.request_hash == authority.admission_snapshot_hash
    )


def _matches_exact_identity(
    fact: RuntimeExternalPermitFact,
    identities: AdmissionPermitIdentities,
) -> bool:
    return (
        fact.runtime_external_permit_id
        == identities.runtime_external_permit_id
        and fact.issue_event_id == identities.issue_event_id
    )


def _matches_current_issued(
    fact: RuntimeExternalPermitFact,
    *,
    request: IssueAdmissionPermitRequest,
    identities: AdmissionPermitIdentities,
    now: datetime,
) -> bool:
    authority = request.authority
    return (
        _matches_logical_binding(fact, request=request)
        and _matches_exact_identity(fact, identities)
        and fact.lease_owner == authority.lease_owner
        and fact.lease_epoch == authority.lease_epoch
        and fact.status == ExternalPermitStatus.ISSUED
        and fact.requested_ttl_seconds == request.requested_ttl_seconds
        and fact.expires_at - fact.issued_at
        == timedelta(seconds=request.requested_ttl_seconds)
        and fact.issued_at <= now < fact.expires_at
        and fact.updated_at == fact.issued_at
    )


def _matches_current_consumed(
    fact: RuntimeExternalPermitFact,
    *,
    request: IssueAdmissionPermitRequest,
    identities: AdmissionPermitIdentities,
    now: datetime,
) -> bool:
    authority = request.authority
    return (
        _matches_logical_binding(fact, request=request)
        and _matches_exact_identity(fact, identities)
        and fact.lease_owner == authority.lease_owner
        and fact.lease_epoch == authority.lease_epoch
        and fact.status == ExternalPermitStatus.CONSUMED
        and fact.requested_ttl_seconds == request.requested_ttl_seconds
        and fact.expires_at - fact.issued_at
        == timedelta(seconds=request.requested_ttl_seconds)
        and fact.consume_event_id == identities.consume_event_id
        and fact.consumed_at is not None
        and fact.consumed_at == fact.updated_at
        and fact.consumed_at <= now
    )


def _matches_historical_consumed(
    fact: RuntimeExternalPermitFact,
    *,
    request: IssueAdmissionPermitRequest,
    identities: AdmissionPermitIdentities,
    now: datetime,
) -> bool:
    return (
        _matches_logical_binding(fact, request=request)
        and _matches_exact_identity(fact, identities)
        and fact.lease_epoch < request.authority.lease_epoch
        and fact.status == ExternalPermitStatus.CONSUMED
        and fact.expires_at - fact.issued_at
        == timedelta(seconds=fact.requested_ttl_seconds)
        and fact.consume_event_id == identities.consume_event_id
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

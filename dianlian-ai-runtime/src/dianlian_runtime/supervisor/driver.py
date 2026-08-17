from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from dianlian_runtime.supervisor.contracts import (
    FrozenJsonObject,
    RuntimeExecutionAuthorityFact,
    require_supported_admission_contract_version,
)


class DriverExecutionDisposition(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED_CONFIRMED = "FAILED_CONFIRMED"
    CONVERGENCE_PENDING = "CONVERGENCE_PENDING"
    FENCED = "FENCED"


class LocalQuiesceDisposition(StrEnum):
    QUIESCED = "QUIESCED"
    NOT_CONFIRMED = "NOT_CONFIRMED"


class DriverFenceRevoked(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DriverFence:
    tenant_id: UUID
    runtime_run_id: UUID
    task_execution_generation: int
    lease_owner: str
    lease_epoch: int
    admission_contract_version: str
    admission_snapshot_id: UUID
    admission_snapshot_hash: str

    def __post_init__(self) -> None:
        _require_uuid("tenant_id", self.tenant_id)
        _require_uuid("runtime_run_id", self.runtime_run_id)
        _require_positive(
            "task_execution_generation",
            self.task_execution_generation,
        )
        _require_text("lease_owner", self.lease_owner, maximum=160)
        _require_positive("lease_epoch", self.lease_epoch)
        require_supported_admission_contract_version(
            self.admission_contract_version
        )
        _require_uuid("admission_snapshot_id", self.admission_snapshot_id)
        _require_hash("admission_snapshot_hash", self.admission_snapshot_hash)


@dataclass(frozen=True, slots=True)
class DriverExecutionRequest:
    """Opaque durable identities only; never carries manifest bodies or credentials."""

    authority: RuntimeExecutionAuthorityFact
    fence: DriverFence

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


@dataclass(frozen=True, slots=True)
class PersistedDriverCheckpoint:
    checkpoint_id: str
    checkpoint_namespace: str
    checkpoint_schema_version: str
    event_payload: FrozenJsonObject

    def __post_init__(self) -> None:
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
        if not isinstance(self.event_payload, FrozenJsonObject):
            raise TypeError("event_payload must be a FrozenJsonObject")


@dataclass(frozen=True, slots=True)
class DriverExecutionResult:
    disposition: DriverExecutionDisposition
    terminal_reason: str | None
    failure_code: str | None
    event_payload: FrozenJsonObject

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, DriverExecutionDisposition):
            raise TypeError("disposition must be a DriverExecutionDisposition")
        if not isinstance(self.event_payload, FrozenJsonObject):
            raise TypeError("event_payload must be a FrozenJsonObject")
        if self.disposition == DriverExecutionDisposition.COMPLETED:
            _require_code("terminal_reason", self.terminal_reason)
            if self.failure_code is not None:
                raise ValueError("completed execution cannot include failure_code")
        elif self.disposition == DriverExecutionDisposition.FAILED_CONFIRMED:
            _require_code("terminal_reason", self.terminal_reason)
            _require_code("failure_code", self.failure_code)
        elif self.terminal_reason is not None or self.failure_code is not None:
            raise ValueError("nonterminal execution cannot include terminal facts")


@dataclass(frozen=True, slots=True)
class LocalQuiesceResult:
    disposition: LocalQuiesceDisposition

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, LocalQuiesceDisposition):
            raise TypeError("disposition must be a LocalQuiesceDisposition")


class DriverFenceGate(Protocol):
    """Linear DB gate for every model, tool, artifact, sandbox and checkpoint I/O.

    A successful authorization applies to exactly one immediately following
    external operation and must never be positively cached.
    """

    @property
    def revoked(self) -> bool: ...

    async def authorize_execution(self) -> None: ...


class DriverCheckpointSink(Protocol):
    async def register(
        self,
        fence: DriverFence,
        checkpoint: PersistedDriverCheckpoint,
    ) -> None:
        """Register one durable ref or raise DriverFenceRevoked; False is not valid."""
        ...


class RunExecutionDriver(Protocol):
    """Dormant execution boundary; local quiesce must never perform remote I/O."""

    @property
    def ready(self) -> bool: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def execute(
        self,
        request: DriverExecutionRequest,
        *,
        gate: DriverFenceGate,
        checkpoints: DriverCheckpointSink,
    ) -> DriverExecutionResult: ...

    async def quiesce_locally(
        self,
        fence: DriverFence,
    ) -> LocalQuiesceResult:
        """Stop local work only and never assert a durable cancellation outcome."""
        ...


def _require_code(name: str, value: str | None) -> None:
    if value is None or not value or len(value) > 64:
        raise ValueError(f"{name} must be a stable uppercase code")
    if not value[0].isalpha() or value[0] != value[0].upper():
        raise ValueError(f"{name} must be a stable uppercase code")
    if any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for character in value):
        raise ValueError(f"{name} must be a stable uppercase code")


def _require_uuid(name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{name} must be a UUID")
    if value.int == 0:
        raise ValueError(f"{name} must not be the nil UUID")


def _require_positive(name: str, value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value < 1 or value > 2**63 - 1:
        raise ValueError(f"{name} is outside its allowed range")


def _require_hash(name: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _require_text(
    name: str,
    value: object,
    *,
    maximum: int,
    allow_empty: bool = False,
) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if len(value) > maximum or (not allow_empty and not value.strip()):
        raise ValueError(f"{name} is outside its allowed range")

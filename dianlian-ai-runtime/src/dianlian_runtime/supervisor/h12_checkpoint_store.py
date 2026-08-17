from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from typing import Protocol
from uuid import UUID, uuid5

from dianlian_runtime.supervisor.contracts import (
    FrozenJsonObject,
    LoadRuntimeH12CheckpointRequest,
    PrimitiveOutcome,
    PrimitiveResult,
    RuntimeH12CheckpointFact,
    SaveRuntimeH12CheckpointRequest,
)
from dianlian_runtime.supervisor.driver import DriverFence


_CHECKPOINT_NAMESPACE = UUID("4cd52df4-b86a-5dde-951a-b0f0f58d73d9")


class RuntimeH12CheckpointRejected(RuntimeError):
    """The current Run fence or the expected checkpoint CAS was not applied."""


class RuntimeH12CheckpointContractViolation(RuntimeError):
    """The restricted repository returned evidence outside the frozen contract."""


class RuntimeH12CheckpointRepository(Protocol):
    def check_h12_checkpoint_capability(self) -> PrimitiveResult[bool]: ...

    def load_h12_checkpoint(
        self,
        request: LoadRuntimeH12CheckpointRequest,
    ) -> PrimitiveResult[RuntimeH12CheckpointFact]: ...

    def save_h12_checkpoint(
        self,
        request: SaveRuntimeH12CheckpointRequest,
    ) -> PrimitiveResult[RuntimeH12CheckpointFact]: ...


@dataclass(frozen=True, slots=True)
class RuntimeH12SlotsState:
    initial_model: FrozenJsonObject | None = None
    tool: FrozenJsonObject | None = None
    after_tool_model: FrozenJsonObject | None = None

    def __post_init__(self) -> None:
        for name in ("initial_model", "tool", "after_tool_model"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, FrozenJsonObject):
                raise TypeError(f"{name} must be a FrozenJsonObject or null")

    def to_document(
        self,
        fence: DriverFence,
        state_version: int,
    ) -> FrozenJsonObject:
        if not isinstance(fence, DriverFence):
            raise TypeError("fence must be a DriverFence")
        if isinstance(state_version, bool) or not isinstance(state_version, int):
            raise TypeError("state_version must be an integer")
        if state_version < 1 or state_version > 2**63 - 1:
            raise ValueError("state_version is outside its allowed range")
        return FrozenJsonObject(
            {
                "schemaVersion": "governed-h12-state-v1",
                "stateVersion": state_version,
                "tenantId": str(fence.tenant_id),
                "runtimeRunId": str(fence.runtime_run_id),
                "taskExecutionGeneration": fence.task_execution_generation,
                "initialModel": _optional_builtin(self.initial_model),
                "tool": _optional_builtin(self.tool),
                "afterToolModel": _optional_builtin(self.after_tool_model),
            }
        )

    @classmethod
    def from_fact(cls, fact: RuntimeH12CheckpointFact) -> RuntimeH12SlotsState:
        if not isinstance(fact, RuntimeH12CheckpointFact):
            raise TypeError("fact must be a RuntimeH12CheckpointFact")
        document = fact.state.to_builtin()
        return cls(
            initial_model=_optional_json_object(document["initialModel"]),
            tool=_optional_json_object(document["tool"]),
            after_tool_model=_optional_json_object(document["afterToolModel"]),
        )


class PostgresH12CheckpointStore:
    """Async CAS facade over the restricted PostgreSQL H12 checkpoint primitives."""

    def __init__(self, repository: RuntimeH12CheckpointRepository) -> None:
        if (
            not callable(getattr(repository, "check_h12_checkpoint_capability", None))
            or not callable(getattr(repository, "load_h12_checkpoint", None))
            or not callable(getattr(repository, "save_h12_checkpoint", None))
        ):
            raise TypeError("repository must expose the H12 checkpoint primitives")
        self._repository = repository

    async def verify_capability(self) -> None:
        result = await asyncio.to_thread(
            self._repository.check_h12_checkpoint_capability
        )
        if (
            not isinstance(result, PrimitiveResult)
            or result.outcome != PrimitiveOutcome.FACT_RETURNED
            or result.fact is not True
        ):
            raise RuntimeH12CheckpointContractViolation(
                "H12 checkpoint database capability is not ready"
            )

    async def load(
        self,
        fence: DriverFence,
    ) -> RuntimeH12CheckpointFact | None:
        request = _load_request(fence)
        result = await asyncio.to_thread(self._repository.load_h12_checkpoint, request)
        if not isinstance(result, PrimitiveResult):
            raise RuntimeH12CheckpointContractViolation(
                "H12 checkpoint load returned an invalid primitive result"
            )
        if result.outcome == PrimitiveOutcome.NOT_APPLIED:
            return None
        fact = _require_fact(result)
        _verify_loaded_fact(fact, fence)
        return fact

    async def save(
        self,
        fence: DriverFence,
        *,
        expected: RuntimeH12CheckpointFact | None,
        transition_code: str,
        state: RuntimeH12SlotsState,
    ) -> RuntimeH12CheckpointFact:
        if not isinstance(fence, DriverFence):
            raise TypeError("fence must be a DriverFence")
        if expected is not None:
            _verify_loaded_fact(expected, fence)
        if not isinstance(state, RuntimeH12SlotsState):
            raise TypeError("state must be a RuntimeH12SlotsState")
        expected_state_version = expected.state_version if expected is not None else 0
        expected_checkpoint_id = expected.checkpoint_id if expected is not None else None
        document = state.to_document(fence, expected_state_version + 1)
        event_id = _stable_event_id(
            fence,
            state_version=expected_state_version + 1,
            transition_code=transition_code,
            document=document,
        )
        checkpoint_id = f"h12-{expected_state_version + 1}-{event_id}"
        request = SaveRuntimeH12CheckpointRequest(
            tenant_id=fence.tenant_id,
            runtime_run_id=fence.runtime_run_id,
            task_execution_generation=fence.task_execution_generation,
            lease_owner=fence.lease_owner,
            lease_epoch=fence.lease_epoch,
            expected_checkpoint_id=expected_checkpoint_id,
            expected_state_version=expected_state_version,
            event_id=event_id,
            checkpoint_id=checkpoint_id,
            transition_code=transition_code,
            state=document,
        )
        result = await asyncio.to_thread(self._repository.save_h12_checkpoint, request)
        if not isinstance(result, PrimitiveResult):
            raise RuntimeH12CheckpointContractViolation(
                "H12 checkpoint save returned an invalid primitive result"
            )
        if result.outcome == PrimitiveOutcome.NOT_APPLIED:
            raise RuntimeH12CheckpointRejected(
                "current Run fence or expected H12 checkpoint was not applied"
            )
        fact = _require_fact(result)
        _verify_saved_fact(fact, request)
        return fact


def _load_request(fence: DriverFence) -> LoadRuntimeH12CheckpointRequest:
    if not isinstance(fence, DriverFence):
        raise TypeError("fence must be a DriverFence")
    return LoadRuntimeH12CheckpointRequest(
        tenant_id=fence.tenant_id,
        runtime_run_id=fence.runtime_run_id,
        task_execution_generation=fence.task_execution_generation,
        lease_owner=fence.lease_owner,
        lease_epoch=fence.lease_epoch,
    )


def _stable_event_id(
    fence: DriverFence,
    *,
    state_version: int,
    transition_code: str,
    document: FrozenJsonObject,
) -> UUID:
    state_digest = hashlib.sha256(document.canonical.encode("utf-8")).hexdigest()
    name = json.dumps(
        [
            "governed-h12-checkpoint-v1",
            str(fence.tenant_id),
            str(fence.runtime_run_id),
            str(fence.task_execution_generation),
            fence.lease_owner,
            str(fence.lease_epoch),
            str(state_version),
            transition_code,
            state_digest,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return uuid5(_CHECKPOINT_NAMESPACE, name)


def _require_fact(
    result: PrimitiveResult[RuntimeH12CheckpointFact],
) -> RuntimeH12CheckpointFact:
    if not isinstance(result.fact, RuntimeH12CheckpointFact):
        raise RuntimeH12CheckpointContractViolation(
            "H12 checkpoint primitive returned an invalid fact"
        )
    return result.fact


def _verify_loaded_fact(fact: RuntimeH12CheckpointFact, fence: DriverFence) -> None:
    if (
        fact.tenant_id != fence.tenant_id
        or fact.runtime_run_id != fence.runtime_run_id
        or fact.task_execution_generation != fence.task_execution_generation
    ):
        raise RuntimeH12CheckpointContractViolation(
            "H12 checkpoint fact does not match the requested Run identity"
        )


def _verify_saved_fact(
    fact: RuntimeH12CheckpointFact,
    request: SaveRuntimeH12CheckpointRequest,
) -> None:
    if (
        fact.tenant_id != request.tenant_id
        or fact.runtime_run_id != request.runtime_run_id
        or fact.task_execution_generation != request.task_execution_generation
        or fact.checkpoint_id != request.checkpoint_id
        or fact.previous_checkpoint_id != request.expected_checkpoint_id
        or fact.state_version != request.expected_state_version + 1
        or fact.state != request.state
        or fact.transition_code != request.transition_code
        or fact.event_id != request.event_id
        or fact.created_by != request.lease_owner
        or fact.lease_epoch != request.lease_epoch
    ):
        raise RuntimeH12CheckpointContractViolation(
            "H12 checkpoint save evidence does not match the exact command"
        )


def _optional_builtin(value: FrozenJsonObject | None) -> dict[str, object] | None:
    return value.to_builtin() if value is not None else None


def _optional_json_object(value: object) -> FrozenJsonObject | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RuntimeH12CheckpointContractViolation(
            "H12 checkpoint slot must be a JSON object or null"
        )
    return FrozenJsonObject(value)

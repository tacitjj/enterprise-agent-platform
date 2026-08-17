from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from dianlian_runtime.supervisor.contracts import (
    FrozenJsonObject,
    PrimitiveOutcome,
    PrimitiveResult,
    RuntimeH12CheckpointFact,
)
from dianlian_runtime.supervisor.driver import DriverFence
from dianlian_runtime.supervisor.h12_checkpoint_store import (
    PostgresH12CheckpointStore,
    RuntimeH12CheckpointContractViolation,
    RuntimeH12CheckpointRejected,
    RuntimeH12SlotsState,
)


TENANT_ID = UUID("73000000-0000-4000-8000-000000000001")
RUN_ID = UUID("73000000-0000-4000-8000-000000000002")
ADMISSION_ID = UUID("73000000-0000-4000-8000-000000000003")
HASH = "a" * 64
NOW = datetime(2026, 8, 14, tzinfo=timezone.utc)


def _fence() -> DriverFence:
    return DriverFence(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        task_execution_generation=3,
        lease_owner="worker-1",
        lease_epoch=2,
        admission_contract_version="2.2",
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=HASH,
    )


def _state() -> RuntimeH12SlotsState:
    return RuntimeH12SlotsState(
        initial_model=FrozenJsonObject(
            {"localState": "PREPARED", "modelCallId": str(RUN_ID)}
        )
    )


class RecordingRepository:
    def __init__(self) -> None:
        self.capability_result = PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            True,
        )
        self.load_result = PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None)
        self.save_result: PrimitiveResult[RuntimeH12CheckpointFact] | None = None
        self.load_requests = []
        self.save_requests = []

    def check_h12_checkpoint_capability(self):
        return self.capability_result

    def load_h12_checkpoint(self, request):
        self.load_requests.append(request)
        return self.load_result

    def save_h12_checkpoint(self, request):
        self.save_requests.append(request)
        if self.save_result is None:
            self.save_result = PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                RuntimeH12CheckpointFact(
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
                ),
            )
        return self.save_result


def test_save_builds_one_exact_deterministic_checkpoint_command() -> None:
    repository = RecordingRepository()
    store = PostgresH12CheckpointStore(repository)

    first = asyncio.run(
        store.save(
            _fence(),
            expected=None,
            transition_code="INITIAL_PREPARED",
            state=_state(),
        )
    )
    repository.save_result = None
    replay = asyncio.run(
        store.save(
            _fence(),
            expected=None,
            transition_code="INITIAL_PREPARED",
            state=_state(),
        )
    )

    assert first.checkpoint_id == replay.checkpoint_id
    assert first.event_id == replay.event_id
    assert repository.save_requests[0] == repository.save_requests[1]
    assert repository.save_requests[0].state.to_builtin()["stateVersion"] == 1


def test_capability_probe_fails_closed_before_worker_start() -> None:
    repository = RecordingRepository()
    repository.capability_result = PrimitiveResult(
        PrimitiveOutcome.FACT_RETURNED,
        False,
    )
    store = PostgresH12CheckpointStore(repository)

    with pytest.raises(
        RuntimeH12CheckpointContractViolation,
        match="capability is not ready",
    ):
        asyncio.run(store.verify_capability())


def test_load_returns_only_a_matching_typed_checkpoint() -> None:
    repository = RecordingRepository()
    store = PostgresH12CheckpointStore(repository)
    saved = asyncio.run(
        store.save(
            _fence(),
            expected=None,
            transition_code="INITIAL_PREPARED",
            state=_state(),
        )
    )
    repository.load_result = PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, saved)

    loaded = asyncio.run(store.load(_fence()))

    assert loaded == saved
    assert RuntimeH12SlotsState.from_fact(loaded) == _state()


def test_save_rejects_zero_row_cas_without_claiming_success() -> None:
    repository = RecordingRepository()
    repository.save_result = PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None)
    store = PostgresH12CheckpointStore(repository)

    with pytest.raises(RuntimeH12CheckpointRejected):
        asyncio.run(
            store.save(
                _fence(),
                expected=None,
                transition_code="INITIAL_PREPARED",
                state=_state(),
            )
        )


def test_save_fails_closed_when_database_evidence_drifts() -> None:
    repository = RecordingRepository()
    store = PostgresH12CheckpointStore(repository)
    valid = asyncio.run(
        store.save(
            _fence(),
            expected=None,
            transition_code="INITIAL_PREPARED",
            state=_state(),
        )
    )
    repository.save_result = PrimitiveResult(
        PrimitiveOutcome.FACT_RETURNED,
        replace(valid, created_by="other-worker"),
    )

    with pytest.raises(RuntimeH12CheckpointContractViolation):
        asyncio.run(
            store.save(
                _fence(),
                expected=None,
                transition_code="INITIAL_PREPARED",
                state=_state(),
            )
        )

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import threading
from typing import Any
from uuid import UUID

import pytest

from dianlian_runtime.supervisor.contracts import (
    FrozenJsonObject,
    LoadRuntimeExecutionAuthorityRequest,
    MultitaskStrategy,
    OperationKind,
    PrimitiveOutcome,
    PrimitiveResult,
    RuntimeExecutionAuthorityFact,
    RuntimeRunCandidateFact,
    RuntimeRunFact,
    RuntimeStatus,
    SupervisorErrorCode,
    SupervisorOutcomeUnknown,
    SupervisorPrimitive,
    SupervisorUnavailable,
)
from dianlian_runtime.supervisor.driver import (
    DriverExecutionDisposition,
    DriverExecutionRequest,
    DriverExecutionResult,
    DriverFence,
    DriverFenceRevoked,
    LocalQuiesceDisposition,
    LocalQuiesceResult,
    PersistedDriverCheckpoint,
)
from dianlian_runtime.supervisor.service import (
    DormantRunSupervisorWorker,
    SupervisorWorkerState,
)


TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
RUN_ID = UUID("10000000-0000-4000-8000-000000000002")
THREAD_ID = UUID("10000000-0000-4000-8000-000000000003")
STEP_ID = UUID("10000000-0000-4000-8000-000000000004")
FIXED_UUID = UUID("10000000-0000-4000-8000-000000000005")
CLAIM_EVENT_ID = UUID("10000000-0000-4000-8000-000000000006")
TERMINAL_EVENT_ID = UUID("10000000-0000-4000-8000-000000000007")
TASK_ID = UUID("10000000-0000-4000-8000-000000000008")
AGENT_INSTANCE_ID = UUID("10000000-0000-4000-8000-000000000009")
USER_ID = UUID("10000000-0000-4000-8000-00000000000a")
CONVERSATION_ID = UUID("10000000-0000-4000-8000-00000000000b")
CAPABILITY_VERSION_ID = UUID("10000000-0000-4000-8000-00000000000c")
PROMPT_VERSION_ID = UUID("10000000-0000-4000-8000-00000000000d")
MODEL_POLICY_ID = UUID("10000000-0000-4000-8000-00000000000e")
BUDGET_RESERVATION_ID = UUID("10000000-0000-4000-8000-00000000000f")
ADMISSION_SNAPSHOT_ID = UUID("10000000-0000-4000-8000-000000000010")
OTHER_ADMISSION_SNAPSHOT_ID = UUID("10000000-0000-4000-8000-000000000011")
NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


def _execution_authority_fact(
    *,
    lease_owner: str = f"dianlian-agent-worker:{FIXED_UUID}",
) -> RuntimeExecutionAuthorityFact:
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
        source_message_id=None,
        runtime_thread_revision=1,
        runtime_type="DEERFLOW",
        runtime_agent_name="runtime-agent",
        capability_version_id=CAPABILITY_VERSION_ID,
        prompt_version_id=PROMPT_VERSION_ID,
        model_policy_id=MODEL_POLICY_ID,
        budget_reservation_id=BUDGET_RESERVATION_ID,
        operation_kind=OperationKind.START,
        multitask_strategy=MultitaskStrategy.REJECT,
        request_hash="a" * 64,
        idempotency_key="intent-1",
        predecessor_runtime_run_id=None,
        expected_checkpoint_id=None,
        runtime_version="runtime-v1",
        agent_name="agent-v1",
        admission_contract_version="2.2",
        lease_owner=lease_owner,
        lease_epoch=1,
        admission_snapshot_id=ADMISSION_SNAPSHOT_ID,
        admission_snapshot_hash="b" * 64,
    )


def _fence(
    authority: RuntimeExecutionAuthorityFact | None = None,
) -> DriverFence:
    authority = authority or _execution_authority_fact(
        lease_owner="dianlian-agent-worker:test"
    )
    return DriverFence(
        tenant_id=authority.tenant_id,
        runtime_run_id=authority.runtime_run_id,
        task_execution_generation=authority.task_execution_generation,
        lease_owner=authority.lease_owner,
        lease_epoch=authority.lease_epoch,
        admission_contract_version=authority.admission_contract_version,
        admission_snapshot_id=authority.admission_snapshot_id,
        admission_snapshot_hash=authority.admission_snapshot_hash,
    )


def test_driver_contracts_are_frozen_and_reject_weak_identities() -> None:
    authority = _execution_authority_fact(
        lease_owner="dianlian-agent-worker:test"
    )
    fence = _fence(authority)
    request = DriverExecutionRequest(
        authority=authority,
        fence=fence,
    )
    checkpoint = PersistedDriverCheckpoint(
        checkpoint_id="checkpoint-1",
        checkpoint_namespace="",
        checkpoint_schema_version="v1",
        event_payload=FrozenJsonObject({"kind": "checkpoint"}),
    )

    assert request.fence == fence
    assert request.authority == authority
    assert DriverExecutionRequest.__slots__ == ("authority", "fence")
    assert checkpoint.event_payload.to_builtin() == {"kind": "checkpoint"}
    with pytest.raises(TypeError, match="lease_epoch must be an integer"):
        replace(fence, lease_epoch=True)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="authority must be"):
        DriverExecutionRequest(  # type: ignore[arg-type]
            authority="not-an-authority",
            fence=fence,
        )
    with pytest.raises(ValueError, match="admission_contract_version must be 2.2"):
        replace(fence, admission_contract_version="2.1")
    for mismatched_fence in (
        replace(fence, task_execution_generation=2),
        replace(fence, admission_snapshot_id=OTHER_ADMISSION_SNAPSHOT_ID),
        replace(fence, admission_snapshot_hash="c" * 64),
    ):
        with pytest.raises(ValueError, match="authority and fence do not match"):
            DriverExecutionRequest(authority, mismatched_fence)


def test_driver_results_cannot_forge_terminal_or_cancellation_facts() -> None:
    completed = DriverExecutionResult(
        DriverExecutionDisposition.COMPLETED,
        "RUN_FINISHED",
        None,
        FrozenJsonObject({}),
    )
    failed = DriverExecutionResult(
        DriverExecutionDisposition.FAILED_CONFIRMED,
        "RUN_FAILED",
        "DRIVER_FAILED",
        FrozenJsonObject({}),
    )
    quiesced = LocalQuiesceResult(LocalQuiesceDisposition.QUIESCED)

    assert completed.failure_code is None
    assert failed.failure_code == "DRIVER_FAILED"
    assert quiesced.disposition == LocalQuiesceDisposition.QUIESCED
    with pytest.raises(ValueError, match="fenced execution cannot include terminal facts"):
        DriverExecutionResult(
            DriverExecutionDisposition.FENCED,
            "RUN_FAILED",
            None,
            FrozenJsonObject({}),
        )
    assert not hasattr(quiesced, "terminal_reason")
    assert not hasattr(quiesced, "event_payload")


def _run_fact(
    *,
    status: RuntimeStatus = RuntimeStatus.RUNNING,
    lease_owner: str = f"dianlian-agent-worker:{FIXED_UUID}",
) -> RuntimeRunFact:
    return RuntimeRunFact(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        runtime_thread_id=THREAD_ID,
        task_step_id=STEP_ID,
        task_execution_generation=1,
        status=status,
        operation_kind=OperationKind.START,
        multitask_strategy=MultitaskStrategy.REJECT,
        request_hash="a" * 64,
        idempotency_key="intent-1",
        predecessor_runtime_run_id=None,
        expected_checkpoint_id=None,
        current_checkpoint_id=None,
        current_checkpoint_sequence_no=None,
        next_event_sequence_no=3,
        event_retention_floor_sequence=1,
        run_version=2,
        terminal_reason=None,
        terminal_event_id=None,
        lease_owner=lease_owner,
        lease_until=NOW + timedelta(seconds=30),
        lease_epoch=1,
        heartbeat_at=NOW,
        attempt=1,
        runtime_version="runtime-v1",
        agent_name="agent-v1",
        failure_code=None,
        cancel_requested_at=None,
        started_at=NOW,
        terminal_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeRepository:
    def __init__(self) -> None:
        self.candidate_results: list[Any] = []
        self.claim_results: list[Any] = []
        self.execution_authority_results: list[Any] = [
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                _execution_authority_fact(),
            )
        ]
        self.renew_results: list[Any] = []
        self.authorize_results: list[Any] = []
        self.complete_results: list[Any] = []
        self.fail_results: list[Any] = []
        self.checkpoint_results: list[Any] = []
        self.calls: list[tuple[str, object]] = []
        self.claim_entered: asyncio.Event | None = None
        self.release_claim: asyncio.Event | None = None

    def _next(self, name: str, request: object, values: list[Any]) -> Any:
        self.calls.append((name, request))
        if not values:
            raise AssertionError(f"unexpected {name} call")
        value = values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def select_next_candidate(self, request: object) -> Any:
        return self._next("candidate", request, self.candidate_results)

    async def _async_claim(self, request: object) -> Any:
        if self.claim_entered is not None:
            self.claim_entered.set()
        if self.release_claim is not None:
            await self.release_claim.wait()
        return self._next("claim", request, self.claim_results)

    def claim(self, request: object) -> Any:
        return self._next("claim", request, self.claim_results)

    def load_execution_authority(self, request: object) -> Any:
        return self._next(
            "load_execution_authority",
            request,
            self.execution_authority_results,
        )

    def renew_lease(self, request: object) -> Any:
        return self._next("renew", request, self.renew_results)

    def authorize(self, request: object) -> Any:
        return self._next("authorize", request, self.authorize_results)

    def record_checkpoint(self, request: object) -> Any:
        return self._next("checkpoint", request, self.checkpoint_results)

    def complete(self, request: object) -> Any:
        return self._next("complete", request, self.complete_results)

    def fail(self, request: object) -> Any:
        return self._next("fail", request, self.fail_results)


class FakeDriver:
    def __init__(self) -> None:
        self.ready = False
        self.start_count = 0
        self.close_count = 0
        self.execute_count = 0
        self.execution_requests: list[DriverExecutionRequest] = []
        self.quiesce_count = 0
        self.result = DriverExecutionResult(
            DriverExecutionDisposition.COMPLETED,
            "RUN_FINISHED",
            None,
            FrozenJsonObject({"result": "ok"}),
        )
        self.release_execute = asyncio.Event()
        self.authorize_twice = False
        self.checkpoint: PersistedDriverCheckpoint | None = None
        self.execute_exception: BaseException | None = None
        self.close_entered = asyncio.Event()
        self.release_close = asyncio.Event()
        self.block_close = False

    async def start(self) -> None:
        self.start_count += 1
        self.ready = True

    async def close(self) -> None:
        self.close_count += 1
        self.close_entered.set()
        if self.block_close:
            await self.release_close.wait()
        self.ready = False

    async def execute(self, request: object, **kwargs: object) -> DriverExecutionResult:
        gate = kwargs["gate"]
        checkpoints = kwargs["checkpoints"]
        self.execute_count += 1
        assert isinstance(request, DriverExecutionRequest)
        self.execution_requests.append(request)
        if self.authorize_twice:
            await getattr(gate, "authorize_execution")()
            await getattr(gate, "authorize_execution")()
        if self.checkpoint is not None:
            await getattr(checkpoints, "register")(
                getattr(request, "fence"),
                self.checkpoint,
            )
        await self.release_execute.wait()
        if self.execute_exception is not None:
            raise self.execute_exception
        return self.result

    async def quiesce_locally(self, fence: object) -> LocalQuiesceResult:
        del fence
        self.quiesce_count += 1
        return LocalQuiesceResult(LocalQuiesceDisposition.QUIESCED)


async def _immediate_offload(operation: Any) -> object:
    return operation()


async def _wait_until(predicate: Any) -> None:
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not become true")


def _uuid_sequence(*values: UUID) -> Any:
    remaining = iter(values)
    return lambda: next(remaining)


def _worker(repository: FakeRepository, driver: FakeDriver) -> DormantRunSupervisorWorker:
    return DormantRunSupervisorWorker(
        repository,  # type: ignore[arg-type]
        driver,  # type: ignore[arg-type]
        runtime_version="runtime-v1",
        agent_name="agent-v1",
        admission_contract_version="2.2",
        lease_seconds=30,
        sleep=asyncio.sleep,
        offload=_immediate_offload,
        uuid_factory=_uuid_sequence(FIXED_UUID, CLAIM_EVENT_ID, TERMINAL_EVENT_ID),
        jitter=lambda _: 0.001,
    )


def test_empty_candidate_probe_controls_readiness_and_close_is_idempotent() -> None:
    async def verify() -> None:
        repository = FakeRepository()
        repository.candidate_results.extend(
            [
                PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None),
                PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None),
            ]
        )
        driver = FakeDriver()
        worker = _worker(repository, driver)

        await worker.start()
        await _wait_until(lambda: worker.ready)
        worker_id = worker.worker_id
        await worker.close()
        await worker.close()

        assert worker.state == SupervisorWorkerState.STOPPED
        assert worker.ready is False
        assert worker_id == f"dianlian-agent-worker:{FIXED_UUID}"
        assert driver.start_count == 1
        assert driver.close_count == 1
        candidate_request = repository.calls[0][1]
        assert getattr(candidate_request, "admission_contract_version") == "2.2"
        with pytest.raises(RuntimeError, match="cannot be started twice"):
            await worker.start()

    asyncio.run(verify())


def test_worker_rejects_non_22_admission_contract() -> None:
    with pytest.raises(ValueError, match="admission_contract_version must be 2.2"):
        DormantRunSupervisorWorker(
            FakeRepository(),  # type: ignore[arg-type]
            FakeDriver(),  # type: ignore[arg-type]
            runtime_version="runtime-v1",
            agent_name="agent-v1",
            admission_contract_version="2.1",
        )


def test_claim_outcome_unknown_fails_stopped_before_driver_and_next_poll() -> None:
    async def verify() -> None:
        repository = FakeRepository()
        repository.candidate_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
            )
        )
        repository.claim_results.append(
            SupervisorOutcomeUnknown(
                SupervisorErrorCode.OUTCOME_UNKNOWN,
                SupervisorPrimitive.CLAIM,
                "08006",
                "claim commit outcome unknown",
            )
        )
        driver = FakeDriver()
        worker = _worker(repository, driver)

        await worker.start()
        await _wait_until(lambda: worker.state == SupervisorWorkerState.FATAL)

        assert worker.ready is False
        assert driver.execute_count == 0
        assert [name for name, _ in repository.calls] == ["candidate", "claim"]
        claim_request = repository.calls[1][1]
        assert getattr(claim_request, "started_event_id") == CLAIM_EVENT_ID
        await worker.close()

    asyncio.run(verify())


def test_completed_driver_result_is_committed_only_after_final_renew() -> None:
    async def verify() -> None:
        repository = FakeRepository()
        repository.candidate_results.extend(
            [
                PrimitiveResult(
                    PrimitiveOutcome.FACT_RETURNED,
                    RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
                ),
                PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None),
            ]
        )
        run = _run_fact()
        repository.claim_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, run)
        )
        repository.renew_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, replace(run, updated_at=NOW))
        )
        repository.complete_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                replace(
                    run,
                    status=RuntimeStatus.COMPLETED,
                    terminal_reason="RUN_FINISHED",
                    terminal_event_id=TERMINAL_EVENT_ID,
                    terminal_at=NOW,
                    lease_owner=None,
                    lease_until=None,
                    heartbeat_at=None,
                ),
            )
        )
        driver = FakeDriver()
        worker = _worker(repository, driver)

        await worker.start()
        await _wait_until(lambda: driver.execute_count == 1)
        driver.release_execute.set()
        await _wait_until(lambda: any(name == "complete" for name, _ in repository.calls))
        await worker.close()

        names = [name for name, _ in repository.calls]
        assert names[:5] == [
            "candidate",
            "claim",
            "load_execution_authority",
            "renew",
            "complete",
        ]
        request = driver.execution_requests[0]
        assert request.authority == _execution_authority_fact()
        assert (
            request.fence.tenant_id,
            request.fence.runtime_run_id,
            request.fence.task_execution_generation,
            request.fence.lease_owner,
            request.fence.lease_epoch,
            request.fence.admission_contract_version,
            request.fence.admission_snapshot_id,
            request.fence.admission_snapshot_hash,
        ) == (
            request.authority.tenant_id,
            request.authority.runtime_run_id,
            request.authority.task_execution_generation,
            request.authority.lease_owner,
            request.authority.lease_epoch,
            request.authority.admission_contract_version,
            request.authority.admission_snapshot_id,
            request.authority.admission_snapshot_hash,
        )
        load_request = repository.calls[2][1]
        assert isinstance(load_request, LoadRuntimeExecutionAuthorityRequest)
        assert load_request.tenant_id == TENANT_ID
        assert load_request.runtime_run_id == RUN_ID
        assert load_request.lease_owner == f"dianlian-agent-worker:{FIXED_UUID}"
        assert load_request.lease_epoch == 1
        assert driver.quiesce_count == 0

    asyncio.run(verify())


@pytest.mark.parametrize(
    "authority_result",
    [
        PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None),
        SupervisorUnavailable(
            SupervisorErrorCode.UNAVAILABLE,
            SupervisorPrimitive.LOAD_EXECUTION_AUTHORITY,
            "08006",
            "authority store unavailable",
        ),
        PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, object()),
    ],
    ids=["not-applied", "repository-error", "malformed-fact"],
)
def test_execution_authority_load_failure_never_starts_driver(
    authority_result: object,
) -> None:
    async def verify() -> None:
        repository = FakeRepository()
        repository.candidate_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
            )
        )
        repository.claim_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, _run_fact())
        )
        repository.execution_authority_results[:] = [authority_result]
        driver = FakeDriver()
        worker = _worker(repository, driver)

        await worker.start()
        await _wait_until(lambda: worker.state == SupervisorWorkerState.FATAL)

        assert driver.execute_count == 0
        assert [name for name, _ in repository.calls] == [
            "candidate",
            "claim",
            "load_execution_authority",
        ]
        await worker.close()

    asyncio.run(verify())


@pytest.mark.parametrize(
    "authority",
    [
        replace(_execution_authority_fact(), tenant_id=TASK_ID),
        replace(_execution_authority_fact(), runtime_run_id=TASK_ID),
        replace(_execution_authority_fact(), runtime_thread_id=TASK_ID),
        replace(_execution_authority_fact(), task_step_id=TASK_ID),
        replace(_execution_authority_fact(), task_execution_generation=2),
        replace(
            _execution_authority_fact(),
            operation_kind=OperationKind.CONTINUE,
            predecessor_runtime_run_id=OTHER_ADMISSION_SNAPSHOT_ID,
        ),
        replace(
            _execution_authority_fact(),
            multitask_strategy=MultitaskStrategy.SAFE_QUEUE,
        ),
        replace(_execution_authority_fact(), request_hash="c" * 64),
        replace(_execution_authority_fact(), idempotency_key="intent-2"),
        replace(
            _execution_authority_fact(),
            expected_checkpoint_id="checkpoint-2",
        ),
        replace(_execution_authority_fact(), runtime_version="runtime-v2"),
        replace(_execution_authority_fact(), agent_name="agent-v2"),
        replace(_execution_authority_fact(), lease_owner="other-worker"),
        replace(_execution_authority_fact(), lease_epoch=2),
    ],
    ids=[
        "tenant",
        "run",
        "thread",
        "step",
        "generation",
        "operation-and-predecessor",
        "multitask-strategy",
        "request-hash",
        "idempotency-key",
        "expected-checkpoint",
        "runtime-version",
        "agent-name",
        "owner",
        "epoch",
    ],
)
def test_execution_authority_must_match_claimed_run(
    authority: RuntimeExecutionAuthorityFact,
) -> None:
    async def verify() -> None:
        repository = FakeRepository()
        repository.candidate_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
            )
        )
        repository.claim_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, _run_fact())
        )
        repository.execution_authority_results[:] = [
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, authority)
        ]
        driver = FakeDriver()
        worker = _worker(repository, driver)

        await worker.start()
        await _wait_until(lambda: worker.state == SupervisorWorkerState.FATAL)

        assert driver.execute_count == 0
        assert not any(
            name in {"renew", "authorize", "checkpoint", "complete", "fail"}
            for name, _ in repository.calls
        )
        await worker.close()

    asyncio.run(verify())


def test_close_waits_for_inflight_to_thread_authority_load() -> None:
    async def verify() -> None:
        class BlockingAuthorityRepository(FakeRepository):
            def __init__(self) -> None:
                super().__init__()
                self.load_entered = threading.Event()
                self.release_load = threading.Event()

            def load_execution_authority(self, request: object) -> Any:
                self.load_entered.set()
                if not self.release_load.wait(timeout=2):
                    raise AssertionError("authority load was not released")
                return self._next(
                    "load_execution_authority",
                    request,
                    self.execution_authority_results,
                )

        repository = BlockingAuthorityRepository()
        repository.candidate_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
            )
        )
        repository.claim_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, _run_fact())
        )
        driver = FakeDriver()
        worker = DormantRunSupervisorWorker(
            repository,  # type: ignore[arg-type]
            driver,  # type: ignore[arg-type]
            runtime_version="runtime-v1",
            agent_name="agent-v1",
            admission_contract_version="2.2",
            drain_timeout_seconds=0.001,
            uuid_factory=_uuid_sequence(FIXED_UUID, CLAIM_EVENT_ID),
            jitter=lambda _: 0.001,
        )

        await worker.start()
        await _wait_until(repository.load_entered.is_set)
        close_task = asyncio.create_task(worker.close())
        await asyncio.sleep(0.01)
        assert close_task.done() is False
        repository.release_load.set()
        await close_task

        assert driver.execute_count == 0
        assert worker.state == SupervisorWorkerState.STOPPED
        assert worker.fatal_error is None
        assert [name for name, _ in repository.calls] == [
            "candidate",
            "claim",
            "load_execution_authority",
        ]

    asyncio.run(verify())


def test_final_renew_not_applied_revokes_execution_without_terminal_write() -> None:
    async def verify() -> None:
        repository = FakeRepository()
        repository.candidate_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
            )
        )
        repository.claim_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, _run_fact())
        )
        repository.renew_results.append(
            PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None)
        )
        driver = FakeDriver()
        worker = _worker(repository, driver)

        await worker.start()
        await _wait_until(lambda: driver.execute_count == 1)
        driver.release_execute.set()
        await _wait_until(lambda: worker.state == SupervisorWorkerState.FATAL)

        assert [name for name, _ in repository.calls] == [
            "candidate",
            "claim",
            "load_execution_authority",
            "renew",
        ]
        await worker.close()

    asyncio.run(verify())


def test_terminal_not_applied_does_not_extend_lease_or_fallback() -> None:
    async def verify() -> None:
        repository = FakeRepository()
        repository.candidate_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
            )
        )
        run = _run_fact()
        repository.claim_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, run)
        )
        repository.renew_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, run)
        )
        repository.complete_results.append(
            PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None)
        )
        driver = FakeDriver()
        worker = _worker(repository, driver)

        await worker.start()
        await _wait_until(lambda: driver.execute_count == 1)
        driver.release_execute.set()
        await _wait_until(lambda: worker.state == SupervisorWorkerState.FATAL)

        assert [name for name, _ in repository.calls] == [
            "candidate",
            "claim",
            "load_execution_authority",
            "renew",
            "complete",
        ]
        await worker.close()

    asyncio.run(verify())


def test_cancel_request_from_renew_only_quiesces_locally_and_writes_no_cancel_fact() -> None:
    async def verify() -> None:
        repository = FakeRepository()
        repository.candidate_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
            )
        )
        run = _run_fact()
        repository.claim_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, run)
        )
        repository.renew_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                replace(
                    run,
                    status=RuntimeStatus.CANCEL_REQUESTED,
                    cancel_requested_at=NOW,
                ),
            )
        )
        driver = FakeDriver()

        async def immediate_sleep(_: float) -> None:
            await asyncio.sleep(0)

        worker = DormantRunSupervisorWorker(
            repository,  # type: ignore[arg-type]
            driver,  # type: ignore[arg-type]
            runtime_version="runtime-v1",
            agent_name="agent-v1",
            admission_contract_version="2.2",
            lease_seconds=5,
            sleep=immediate_sleep,
            offload=_immediate_offload,
            uuid_factory=_uuid_sequence(FIXED_UUID, CLAIM_EVENT_ID),
            jitter=lambda _: 0.0,
        )

        await worker.start()
        await _wait_until(lambda: worker.state == SupervisorWorkerState.FATAL)

        assert driver.quiesce_count == 1
        assert [name for name, _ in repository.calls] == [
            "candidate",
            "claim",
            "load_execution_authority",
            "renew",
        ]
        await worker.close()

    asyncio.run(verify())


def test_close_waits_for_inflight_claim_and_never_starts_driver_execution() -> None:
    async def verify() -> None:
        class BlockingClaimRepository(FakeRepository):
            async def claim_async(self, request: object) -> Any:
                assert self.claim_entered is not None
                assert self.release_claim is not None
                self.claim_entered.set()
                await self.release_claim.wait()
                return self._next("claim", request, self.claim_results)

        repository = BlockingClaimRepository()
        repository.claim_entered = asyncio.Event()
        repository.release_claim = asyncio.Event()
        repository.candidate_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
            )
        )
        repository.claim_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, _run_fact())
        )
        driver = FakeDriver()

        async def custom_offload(operation: Any) -> object:
            closure = getattr(operation, "__closure__", None)
            request = None if not closure else next(
                (cell.cell_contents for cell in closure if hasattr(cell.cell_contents, "started_event_id")),
                None,
            )
            if request is not None:
                return await repository.claim_async(request)
            return operation()

        worker = DormantRunSupervisorWorker(
            repository,  # type: ignore[arg-type]
            driver,  # type: ignore[arg-type]
            runtime_version="runtime-v1",
            agent_name="agent-v1",
            admission_contract_version="2.2",
            offload=custom_offload,
            uuid_factory=_uuid_sequence(FIXED_UUID, CLAIM_EVENT_ID),
            jitter=lambda _: 0.001,
        )

        await worker.start()
        await repository.claim_entered.wait()
        close_task = asyncio.create_task(worker.close())
        await asyncio.sleep(0)
        assert close_task.done() is False
        repository.release_claim.set()
        await close_task

        assert driver.execute_count == 0
        assert worker.state == SupervisorWorkerState.STOPPED

    asyncio.run(verify())


def test_gate_authorizes_each_external_operation_without_positive_cache() -> None:
    async def verify() -> None:
        repository = FakeRepository()
        run = _run_fact()
        repository.candidate_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
            )
        )
        repository.claim_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, run)
        )
        repository.authorize_results.extend(
            [
                PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, run),
                PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, run),
            ]
        )
        repository.renew_results.append(
            PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None)
        )
        driver = FakeDriver()
        driver.authorize_twice = True
        worker = _worker(repository, driver)

        await worker.start()
        await _wait_until(lambda: driver.execute_count == 1)
        driver.release_execute.set()
        await _wait_until(lambda: worker.state == SupervisorWorkerState.FATAL)

        assert [name for name, _ in repository.calls].count("authorize") == 2
        await worker.close()

    asyncio.run(verify())


def test_checkpoint_not_applied_revokes_gate_and_prevents_terminal_write() -> None:
    async def verify() -> None:
        repository = FakeRepository()
        repository.candidate_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
            )
        )
        repository.claim_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, _run_fact())
        )
        repository.checkpoint_results.append(
            PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None)
        )
        driver = FakeDriver()
        driver.checkpoint = PersistedDriverCheckpoint(
            "checkpoint-1",
            "",
            "v1",
            FrozenJsonObject({"kind": "checkpoint"}),
        )
        worker = _worker(repository, driver)

        await worker.start()
        await _wait_until(lambda: worker.state == SupervisorWorkerState.FATAL)

        assert any(name == "checkpoint" for name, _ in repository.calls)
        assert not any(name in {"complete", "fail"} for name, _ in repository.calls)
        assert isinstance(worker.fatal_error, RuntimeError)
        await worker.close()

    asyncio.run(verify())


def test_confirmed_driver_failure_maps_to_exact_failed_terminal_fact() -> None:
    async def verify() -> None:
        repository = FakeRepository()
        run = _run_fact()
        repository.candidate_results.extend(
            [
                PrimitiveResult(
                    PrimitiveOutcome.FACT_RETURNED,
                    RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
                ),
                PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None),
            ]
        )
        repository.claim_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, run)
        )
        repository.renew_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, run)
        )
        repository.fail_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                replace(
                    run,
                    status=RuntimeStatus.FAILED,
                    terminal_reason="DRIVER_FAILED",
                    failure_code="PROVIDER_FAILED",
                    terminal_event_id=TERMINAL_EVENT_ID,
                    terminal_at=NOW,
                    lease_owner=None,
                    lease_until=None,
                    heartbeat_at=None,
                ),
            )
        )
        driver = FakeDriver()
        driver.result = DriverExecutionResult(
            DriverExecutionDisposition.FAILED_CONFIRMED,
            "DRIVER_FAILED",
            "PROVIDER_FAILED",
            FrozenJsonObject({"result": "failed"}),
        )
        worker = _worker(repository, driver)

        await worker.start()
        await _wait_until(lambda: driver.execute_count == 1)
        driver.release_execute.set()
        await _wait_until(lambda: any(name == "fail" for name, _ in repository.calls))
        await worker.close()

        assert [name for name, _ in repository.calls][:5] == [
            "candidate",
            "claim",
            "load_execution_authority",
            "renew",
            "fail",
        ]
        assert not any(name == "complete" for name, _ in repository.calls)

    asyncio.run(verify())


def test_driver_cancelled_error_never_becomes_a_business_failure() -> None:
    async def verify() -> None:
        repository = FakeRepository()
        repository.candidate_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
            )
        )
        repository.claim_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, _run_fact())
        )
        driver = FakeDriver()
        driver.execute_exception = asyncio.CancelledError()
        worker = _worker(repository, driver)

        await worker.start()
        await _wait_until(lambda: driver.execute_count == 1)
        driver.release_execute.set()
        await _wait_until(lambda: worker.state == SupervisorWorkerState.FATAL)

        assert not any(name in {"complete", "fail"} for name, _ in repository.calls)
        await worker.close()

    asyncio.run(verify())


def test_cancelling_close_waits_for_internal_cleanup_before_propagating() -> None:
    async def verify() -> None:
        repository = FakeRepository()
        repository.candidate_results.append(
            PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None)
        )
        driver = FakeDriver()
        driver.block_close = True
        worker = _worker(repository, driver)

        await worker.start()
        await _wait_until(lambda: worker.ready)
        close_task = asyncio.create_task(worker.close())
        await driver.close_entered.wait()
        close_task.cancel()
        await asyncio.sleep(0)
        assert close_task.done() is False
        driver.release_close.set()
        with pytest.raises(asyncio.CancelledError):
            await close_task

        assert driver.close_count == 1
        assert worker.state == SupervisorWorkerState.STOPPED
        assert worker.ready is False

    asyncio.run(verify())


def test_drain_timeout_revokes_local_execution_without_business_terminal() -> None:
    async def verify() -> None:
        repository = FakeRepository()
        repository.candidate_results.append(
            PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                RuntimeRunCandidateFact(TENANT_ID, RUN_ID),
            )
        )
        repository.claim_results.append(
            PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, _run_fact())
        )
        driver = FakeDriver()
        worker = DormantRunSupervisorWorker(
            repository,  # type: ignore[arg-type]
            driver,  # type: ignore[arg-type]
            runtime_version="runtime-v1",
            agent_name="agent-v1",
            admission_contract_version="2.2",
            drain_timeout_seconds=0.001,
            offload=_immediate_offload,
            uuid_factory=_uuid_sequence(FIXED_UUID, CLAIM_EVENT_ID),
            jitter=lambda _: 0.001,
        )

        await worker.start()
        await _wait_until(lambda: driver.execute_count == 1)
        await worker.close()

        assert worker.state == SupervisorWorkerState.STOPPED
        assert not any(name in {"complete", "fail"} for name, _ in repository.calls)
        assert driver.close_count == 1

    asyncio.run(verify())

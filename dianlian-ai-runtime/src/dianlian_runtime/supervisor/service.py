from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum
import random
from typing import Protocol, TypeVar, cast
from uuid import UUID, uuid4

from dianlian_runtime.supervisor.contracts import (
    AuthorizeRuntimeRunRequest,
    ClaimRuntimeRunRequest,
    CompleteRuntimeRunRequest,
    FailRuntimeRunRequest,
    FrozenJsonObject,
    LoadRuntimeExecutionAuthorityRequest,
    PrimitiveOutcome,
    PrimitiveResult,
    RecordRuntimeCheckpointRequest,
    RenewRuntimeRunLeaseRequest,
    RuntimeCheckpointFact,
    RuntimeExecutionAuthorityFact,
    RuntimeRunCandidateFact,
    RuntimeRunFact,
    RuntimeStatus,
    SelectNextRuntimeRunCandidateRequest,
    SupervisorOutcomeUnknown,
    SupervisorRepositoryError,
    SupervisorUnavailable,
)
from dianlian_runtime.supervisor.driver import (
    DriverCheckpointSink,
    DriverExecutionDisposition,
    DriverExecutionRequest,
    DriverFence,
    DriverFenceGate,
    DriverFenceRevoked,
    LocalQuiesceResult,
    PersistedDriverCheckpoint,
    RunExecutionDriver,
)


class RunSupervisor(Protocol):
    """Point-owned lifecycle boundary for the durable Run Supervisor."""

    @property
    def ready(self) -> bool: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...


class SupervisorWorkerState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DRAINING = "DRAINING"
    FATAL = "FATAL"


class RunSupervisorWorkerRepository(Protocol):
    def select_next_candidate(
        self,
        request: SelectNextRuntimeRunCandidateRequest,
    ) -> PrimitiveResult[RuntimeRunCandidateFact]: ...

    def claim(
        self,
        request: ClaimRuntimeRunRequest,
    ) -> PrimitiveResult[RuntimeRunFact]: ...

    def load_execution_authority(
        self,
        request: LoadRuntimeExecutionAuthorityRequest,
    ) -> PrimitiveResult[RuntimeExecutionAuthorityFact]: ...

    def renew_lease(
        self,
        request: RenewRuntimeRunLeaseRequest,
    ) -> PrimitiveResult[RuntimeRunFact]: ...

    def authorize(
        self,
        request: AuthorizeRuntimeRunRequest,
    ) -> PrimitiveResult[RuntimeRunFact]: ...

    def record_checkpoint(
        self,
        request: RecordRuntimeCheckpointRequest,
    ) -> PrimitiveResult[RuntimeCheckpointFact]: ...

    def complete(
        self,
        request: CompleteRuntimeRunRequest,
    ) -> PrimitiveResult[RuntimeRunFact]: ...

    def fail(
        self,
        request: FailRuntimeRunRequest,
    ) -> PrimitiveResult[RuntimeRunFact]: ...


class _RunOutcome(StrEnum):
    TERMINAL_COMMITTED = "TERMINAL_COMMITTED"
    STOPPED = "STOPPED"
    FATAL = "FATAL"


class _HeartbeatOutcome(StrEnum):
    STOPPED = "STOPPED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    FENCE_LOST = "FENCE_LOST"


FactT = TypeVar("FactT")
Offload = Callable[[Callable[[], object]], Awaitable[object]]
Sleeper = Callable[[float], Awaitable[None]]
UuidFactory = Callable[[], UUID]
Jitter = Callable[[float], float]


class DormantRunSupervisorWorker:
    """Single-Run S0 worker; deliberately absent from production composition."""

    def __init__(
        self,
        repository: RunSupervisorWorkerRepository,
        driver: RunExecutionDriver,
        *,
        runtime_version: str,
        agent_name: str,
        admission_contract_version: str,
        lease_seconds: int = 30,
        drain_timeout_seconds: float = 30.0,
        sleep: Sleeper = asyncio.sleep,
        offload: Offload | None = None,
        uuid_factory: UuidFactory = uuid4,
        jitter: Jitter | None = None,
    ) -> None:
        if not runtime_version.strip() or len(runtime_version) > 128:
            raise ValueError("runtime_version is outside its allowed range")
        if not agent_name.strip() or len(agent_name) > 128:
            raise ValueError("agent_name is outside its allowed range")
        if admission_contract_version != "2.2":
            raise ValueError("admission_contract_version must be 2.2")
        if isinstance(lease_seconds, bool) or not 5 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds is outside its allowed range")
        if drain_timeout_seconds <= 0:
            raise ValueError("drain_timeout_seconds must be positive")
        if not callable(uuid_factory):
            raise TypeError("uuid_factory must be callable")

        self._repository = repository
        self._driver = driver
        self._runtime_version = runtime_version
        self._agent_name = agent_name
        self._admission_contract_version = admission_contract_version
        self._lease_seconds = lease_seconds
        self._drain_timeout_seconds = drain_timeout_seconds
        self._sleep = sleep
        self._offload = offload or _offload_to_thread
        self._uuid_factory = uuid_factory
        self._jitter = jitter or (lambda ceiling: random.uniform(0.0, ceiling))

        self._state = SupervisorWorkerState.STOPPED
        self._started_once = False
        self._driver_start_attempted = False
        self._candidate_probe_healthy = False
        self._worker_id: str | None = None
        self._stop_event = asyncio.Event()
        self._main_task: asyncio.Task[None] | None = None
        self._active_gate: _RepositoryDriverGate | None = None
        self._active_driver_task: asyncio.Task[object] | None = None
        self._offloads: set[asyncio.Task[object]] = set()
        self._fatal_error: BaseException | None = None
        self._lifecycle_lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        task = self._main_task
        return (
            self._state == SupervisorWorkerState.RUNNING
            and self._candidate_probe_healthy
            and self._driver.ready
            and task is not None
            and not task.done()
        )

    @property
    def state(self) -> SupervisorWorkerState:
        return self._state

    @property
    def worker_id(self) -> str | None:
        return self._worker_id

    @property
    def fatal_error(self) -> BaseException | None:
        return self._fatal_error

    async def start(self) -> None:
        async with self._lifecycle_lock:
            await self._start_locked()

    async def _start_locked(self) -> None:
        if self._started_once:
            raise RuntimeError("Run Supervisor worker cannot be started twice")
        self._started_once = True
        self._state = SupervisorWorkerState.STARTING
        worker_incarnation = self._uuid_factory()
        if not isinstance(worker_incarnation, UUID) or worker_incarnation.int == 0:
            raise ValueError("uuid_factory returned an invalid worker incarnation")
        self._worker_id = f"dianlian-agent-worker:{worker_incarnation}"
        self._stop_event = asyncio.Event()
        self._driver_start_attempted = True
        try:
            await self._driver.start()
            if not self._driver.ready:
                raise RuntimeError("Run execution driver did not become ready")
        except BaseException as exception:
            self._enter_fatal(exception)
            raise

        self._state = SupervisorWorkerState.RUNNING
        self._main_task = asyncio.create_task(
            self._run_loop(),
            name="dianlian-run-supervisor",
        )

    async def close(self) -> None:
        cleanup_task = asyncio.create_task(self._close_serialized())
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            await asyncio.shield(cleanup_task)
            raise

    async def _close_serialized(self) -> None:
        async with self._lifecycle_lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        if self._state == SupervisorWorkerState.STOPPED and not self._started_once:
            return
        if self._state == SupervisorWorkerState.STOPPED:
            return

        self._state = SupervisorWorkerState.DRAINING
        self._candidate_probe_healthy = False
        self._stop_event.set()
        main_task = self._main_task
        if main_task is not None and not main_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(main_task),
                    timeout=self._drain_timeout_seconds,
                )
            except TimeoutError:
                if self._active_gate is not None:
                    self._active_gate.revoke()
                if self._active_driver_task is not None:
                    self._active_driver_task.cancel()
                main_task.cancel()
                await _await_cancelled(main_task)
            except asyncio.CancelledError:
                raise

        await self._wait_for_offloads()
        try:
            if self._driver_start_attempted:
                await self._driver.close()
        finally:
            self._state = SupervisorWorkerState.STOPPED
            self._main_task = None
            self._active_gate = None
            self._active_driver_task = None

    async def _run_loop(self) -> None:
        empty_backoff = 0.25
        unavailable_backoff = 0.5
        try:
            while not self._stop_event.is_set():
                if not self._driver.ready:
                    self._enter_fatal(RuntimeError("Run execution driver lost readiness"))
                    return
                try:
                    candidate = await self._call_repository(
                        self._repository.select_next_candidate,
                        SelectNextRuntimeRunCandidateRequest(
                            runtime_version=self._runtime_version,
                            agent_name=self._agent_name,
                            admission_contract_version=(
                                self._admission_contract_version
                            ),
                        ),
                    )
                except SupervisorUnavailable:
                    self._candidate_probe_healthy = False
                    if await self._sleep_until_stopped(
                        self._jitter(unavailable_backoff),
                    ):
                        return
                    unavailable_backoff = min(unavailable_backoff * 2, 5.0)
                    continue
                except BaseException as exception:
                    if isinstance(exception, asyncio.CancelledError):
                        raise
                    self._enter_fatal(exception)
                    return

                self._candidate_probe_healthy = True
                unavailable_backoff = 0.5
                if self._stop_event.is_set():
                    return
                if candidate.outcome == PrimitiveOutcome.NOT_APPLIED:
                    if await self._sleep_until_stopped(self._jitter(empty_backoff)):
                        return
                    empty_backoff = min(empty_backoff * 2, 2.0)
                    continue

                fact = candidate.fact
                if fact is None:
                    self._enter_fatal(RuntimeError("candidate fact is missing"))
                    return
                if not self._driver.ready:
                    self._enter_fatal(RuntimeError("Run execution driver lost readiness"))
                    return
                claim_request = ClaimRuntimeRunRequest(
                    fact.tenant_id,
                    fact.runtime_run_id,
                    self._require_worker_id(),
                    self._lease_seconds,
                    self._uuid_factory(),
                    FrozenJsonObject(
                        {
                            "schemaVersion": "runtime-supervisor-claim-v1",
                            "workerId": self._require_worker_id(),
                        }
                    ),
                )
                try:
                    claimed = await self._call_repository(
                        self._repository.claim,
                        claim_request,
                    )
                except SupervisorOutcomeUnknown as exception:
                    # A future reconcile path may replay this exact request. This
                    # dormant worker stops instead of guessing whether claim committed.
                    self._enter_fatal(exception)
                    return
                except BaseException as exception:
                    if isinstance(exception, asyncio.CancelledError):
                        raise
                    self._enter_fatal(exception)
                    return
                if claimed.outcome == PrimitiveOutcome.NOT_APPLIED:
                    if await self._sleep_until_stopped(self._jitter(empty_backoff)):
                        return
                    empty_backoff = min(empty_backoff * 2, 2.0)
                    continue
                claimed_fact = claimed.fact
                if claimed_fact is None:
                    self._enter_fatal(RuntimeError("claimed Run fact is missing"))
                    return
                self._validate_claimed_fact(fact, claimed_fact)
                empty_backoff = 0.25
                if self._stop_event.is_set():
                    # close arrived while a non-cancellable sync claim was in flight.
                    # Do not start execution; the bounded lease expires naturally.
                    return
                if not self._driver.ready:
                    self._enter_fatal(RuntimeError("Run execution driver lost readiness"))
                    return

                outcome = await self._run_claimed(claimed_fact)
                if outcome != _RunOutcome.TERMINAL_COMMITTED:
                    if outcome == _RunOutcome.FATAL and self._state != SupervisorWorkerState.FATAL:
                        self._enter_fatal(RuntimeError("claimed Run lost its safe fence"))
                    return
        except asyncio.CancelledError:
            if self._state not in (
                SupervisorWorkerState.DRAINING,
                SupervisorWorkerState.FATAL,
            ):
                self._enter_fatal(RuntimeError("Run Supervisor loop was cancelled"))
            raise
        except BaseException as exception:
            self._enter_fatal(exception)

    async def _run_claimed(self, run: RuntimeRunFact) -> _RunOutcome:
        authority = await self._load_execution_authority(run)
        if self._stop_event.is_set():
            return _RunOutcome.STOPPED
        if authority is None or not self._driver.ready:
            return _RunOutcome.FATAL
        try:
            fence = DriverFence(
                tenant_id=authority.tenant_id,
                runtime_run_id=authority.runtime_run_id,
                task_execution_generation=(
                    authority.task_execution_generation
                ),
                lease_owner=authority.lease_owner,
                lease_epoch=authority.lease_epoch,
                admission_contract_version=(
                    authority.admission_contract_version
                ),
                admission_snapshot_id=authority.admission_snapshot_id,
                admission_snapshot_hash=authority.admission_snapshot_hash,
            )
            execution_request = DriverExecutionRequest(
                authority=authority,
                fence=fence,
            )
        except (TypeError, ValueError):
            return _RunOutcome.FATAL

        gate = _RepositoryDriverGate(self, fence)
        checkpoints = _RepositoryCheckpointSink(self, gate)
        self._active_gate = gate
        driver_task = asyncio.create_task(
            self._driver.execute(
                execution_request,
                gate=gate,
                checkpoints=checkpoints,
            ),
            name=f"dianlian-run-{run.runtime_run_id}",
        )
        heartbeat_stop = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat(fence, gate, heartbeat_stop),
            name=f"dianlian-run-heartbeat-{run.runtime_run_id}",
        )
        self._active_driver_task = cast(asyncio.Task[object], driver_task)
        try:
            done, _ = await asyncio.wait(
                {driver_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                gate.revoke()
                try:
                    heartbeat_outcome = await heartbeat_task
                except BaseException:
                    driver_task.cancel()
                    await _await_cancelled(driver_task)
                    return _RunOutcome.FATAL
                if heartbeat_outcome == _HeartbeatOutcome.CANCEL_REQUESTED:
                    await self._stop_driver_locally(fence, driver_task)
                else:
                    driver_task.cancel()
                    await _await_cancelled(driver_task)
                return _RunOutcome.FATAL

            try:
                driver_result = await driver_task
            except (DriverFenceRevoked, asyncio.CancelledError) as exception:
                gate.revoke()
                if isinstance(exception, asyncio.CancelledError):
                    raise
                return _RunOutcome.FATAL
            except BaseException:
                gate.revoke()
                return _RunOutcome.FATAL

            heartbeat_stop.set()
            try:
                heartbeat_outcome = await heartbeat_task
            except BaseException:
                gate.revoke()
                return _RunOutcome.FATAL
            if heartbeat_outcome != _HeartbeatOutcome.STOPPED:
                gate.revoke()
                if heartbeat_outcome == _HeartbeatOutcome.CANCEL_REQUESTED:
                    await self._driver.quiesce_locally(fence)
                return _RunOutcome.FATAL

            if driver_result.disposition == DriverExecutionDisposition.FENCED:
                gate.revoke()
                return _RunOutcome.FATAL
            final_renew = await self._renew(fence)
            if final_renew is None:
                gate.revoke()
                return _RunOutcome.FATAL
            if final_renew.status in (
                RuntimeStatus.CANCEL_REQUESTED,
                RuntimeStatus.CANCELLING,
            ):
                gate.revoke()
                await self._driver.quiesce_locally(fence)
                return _RunOutcome.FATAL
            if final_renew.status != RuntimeStatus.RUNNING:
                gate.revoke()
                return _RunOutcome.FATAL

            terminal_event_id = self._uuid_factory()
            try:
                if driver_result.disposition == DriverExecutionDisposition.COMPLETED:
                    terminal = await self._call_repository(
                        self._repository.complete,
                        CompleteRuntimeRunRequest(
                            fence.tenant_id,
                            fence.runtime_run_id,
                            fence.lease_owner,
                            fence.lease_epoch,
                            terminal_event_id,
                            cast(str, driver_result.terminal_reason),
                            driver_result.event_payload,
                        ),
                    )
                else:
                    terminal = await self._call_repository(
                        self._repository.fail,
                        FailRuntimeRunRequest(
                            fence.tenant_id,
                            fence.runtime_run_id,
                            fence.lease_owner,
                            fence.lease_epoch,
                            terminal_event_id,
                            cast(str, driver_result.terminal_reason),
                            cast(str, driver_result.failure_code),
                            driver_result.event_payload,
                        ),
                    )
            except BaseException as exception:
                if isinstance(exception, asyncio.CancelledError):
                    raise
                gate.revoke()
                return _RunOutcome.FATAL

            if terminal.outcome == PrimitiveOutcome.FACT_RETURNED:
                terminal_fact = terminal.fact
                expected_status = (
                    RuntimeStatus.COMPLETED
                    if driver_result.disposition == DriverExecutionDisposition.COMPLETED
                    else RuntimeStatus.FAILED
                )
                if (
                    terminal_fact is None
                    or terminal_fact.tenant_id != fence.tenant_id
                    or terminal_fact.runtime_run_id != fence.runtime_run_id
                    or terminal_fact.status != expected_status
                    or terminal_fact.terminal_event_id != terminal_event_id
                    or terminal_fact.terminal_reason != driver_result.terminal_reason
                    or terminal_fact.lease_epoch != fence.lease_epoch
                    or terminal_fact.lease_owner is not None
                    or terminal_fact.lease_until is not None
                    or terminal_fact.heartbeat_at is not None
                    or terminal_fact.terminal_at is None
                    or (
                        expected_status == RuntimeStatus.COMPLETED
                        and terminal_fact.failure_code is not None
                    )
                    or (
                        expected_status == RuntimeStatus.FAILED
                        and terminal_fact.failure_code != driver_result.failure_code
                    )
                ):
                    gate.revoke()
                    return _RunOutcome.FATAL
                gate.revoke()
                return _RunOutcome.TERMINAL_COMMITTED

            gate.revoke()
            return _RunOutcome.FATAL
        except asyncio.CancelledError:
            gate.revoke()
            driver_task.cancel()
            heartbeat_task.cancel()
            await _await_cancelled(driver_task)
            await _await_cancelled(heartbeat_task)
            raise
        finally:
            gate.revoke()
            heartbeat_stop.set()
            if not driver_task.done():
                driver_task.cancel()
                await _await_cancelled(driver_task)
            if not heartbeat_task.done():
                heartbeat_task.cancel()
                await _await_cancelled(heartbeat_task)
            self._active_driver_task = None
            self._active_gate = None

    async def _heartbeat(
        self,
        fence: DriverFence,
        gate: _RepositoryDriverGate,
        stop: asyncio.Event,
    ) -> _HeartbeatOutcome:
        cadence = min(5.0, self._lease_seconds / 3.0)
        while not gate.revoked:
            if await self._wait_for_event(stop, cadence):
                return _HeartbeatOutcome.STOPPED
            if gate.revoked:
                return _HeartbeatOutcome.FENCE_LOST
            renewed = await self._renew(fence)
            if renewed is None:
                gate.revoke()
                return _HeartbeatOutcome.FENCE_LOST
            if renewed.status in (
                RuntimeStatus.CANCEL_REQUESTED,
                RuntimeStatus.CANCELLING,
            ):
                gate.revoke()
                return _HeartbeatOutcome.CANCEL_REQUESTED
            if renewed.status != RuntimeStatus.RUNNING:
                gate.revoke()
                return _HeartbeatOutcome.FENCE_LOST
            if stop.is_set():
                return _HeartbeatOutcome.STOPPED
        return _HeartbeatOutcome.FENCE_LOST

    async def _load_execution_authority(
        self,
        run: RuntimeRunFact,
    ) -> RuntimeExecutionAuthorityFact | None:
        try:
            result = await self._call_repository(
                self._repository.load_execution_authority,
                LoadRuntimeExecutionAuthorityRequest(
                    tenant_id=run.tenant_id,
                    runtime_run_id=run.runtime_run_id,
                    lease_owner=self._require_worker_id(),
                    lease_epoch=run.lease_epoch,
                ),
            )
            if (
                result.outcome != PrimitiveOutcome.FACT_RETURNED
                or result.fact is None
                or not isinstance(result.fact, RuntimeExecutionAuthorityFact)
            ):
                return None
            authority = result.fact
            authority.__post_init__()
            if (
                authority.tenant_id != run.tenant_id
                or authority.runtime_run_id != run.runtime_run_id
                or authority.runtime_thread_id != run.runtime_thread_id
                or authority.task_step_id != run.task_step_id
                or authority.task_execution_generation
                != run.task_execution_generation
                or authority.operation_kind != run.operation_kind
                or authority.multitask_strategy != run.multitask_strategy
                or authority.request_hash != run.request_hash
                or authority.idempotency_key != run.idempotency_key
                or authority.predecessor_runtime_run_id
                != run.predecessor_runtime_run_id
                or authority.expected_checkpoint_id
                != run.expected_checkpoint_id
                or authority.runtime_version != run.runtime_version
                or authority.agent_name != run.agent_name
                or authority.lease_owner != run.lease_owner
                or authority.lease_owner != self._require_worker_id()
                or authority.lease_epoch != run.lease_epoch
                or authority.admission_contract_version
                != self._admission_contract_version
            ):
                return None
            return authority
        except asyncio.CancelledError:
            raise
        except BaseException:
            return None

    async def _renew(self, fence: DriverFence) -> RuntimeRunFact | None:
        try:
            result = await self._call_repository(
                self._repository.renew_lease,
                RenewRuntimeRunLeaseRequest(
                    fence.tenant_id,
                    fence.runtime_run_id,
                    fence.lease_owner,
                    fence.lease_epoch,
                    self._lease_seconds,
                ),
            )
        except asyncio.CancelledError:
            raise
        except SupervisorRepositoryError:
            return None
        if result.outcome == PrimitiveOutcome.NOT_APPLIED or result.fact is None:
            return None
        fact = result.fact
        if (
            fact.tenant_id != fence.tenant_id
            or fact.runtime_run_id != fence.runtime_run_id
            or fact.lease_owner != fence.lease_owner
            or fact.lease_epoch != fence.lease_epoch
        ):
            return None
        return fact

    async def _stop_driver_locally(
        self,
        fence: DriverFence,
        driver_task: asyncio.Task[object],
    ) -> LocalQuiesceResult | None:
        driver_task.cancel()
        await _await_cancelled(driver_task)
        try:
            return await self._driver.quiesce_locally(fence)
        except asyncio.CancelledError:
            raise
        except BaseException:
            return None

    async def _sleep_until_stopped(self, delay: float) -> bool:
        return await self._wait_for_event(self._stop_event, delay)

    async def _wait_for_event(
        self,
        event: asyncio.Event,
        delay: float,
    ) -> bool:
        if event.is_set():
            return True
        sleep_task = asyncio.create_task(self._sleep(max(0.0, delay)))
        stop_task = asyncio.create_task(event.wait())
        try:
            done, _ = await asyncio.wait(
                {sleep_task, stop_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                await task
            return event.is_set()
        finally:
            for task in (sleep_task, stop_task):
                if not task.done():
                    task.cancel()
                await _await_cancelled(task)

    async def _call_repository(
        self,
        method: Callable[[object], PrimitiveResult[FactT]],
        request: object,
    ) -> PrimitiveResult[FactT]:
        offload_task = asyncio.create_task(
            self._offload(lambda: method(request)),
        )
        tracked = cast(asyncio.Task[object], offload_task)
        self._offloads.add(tracked)
        tracked.add_done_callback(self._offloads.discard)
        try:
            return cast(PrimitiveResult[FactT], await asyncio.shield(offload_task))
        except asyncio.CancelledError:
            # asyncio.to_thread cannot cancel the underlying DB call. The task
            # remains tracked and close waits for its transaction to linearize.
            raise

    async def _wait_for_offloads(self) -> None:
        while self._offloads:
            pending = tuple(self._offloads)
            await asyncio.gather(*pending, return_exceptions=True)

    async def _driver_authorize(self, fence: DriverFence) -> RuntimeRunFact:
        try:
            result = await self._call_repository(
                self._repository.authorize,
                AuthorizeRuntimeRunRequest(
                    fence.tenant_id,
                    fence.runtime_run_id,
                    fence.lease_owner,
                    fence.lease_epoch,
                ),
            )
        except BaseException as exception:
            if isinstance(exception, asyncio.CancelledError):
                raise
            raise DriverFenceRevoked("runtime execution authorization failed") from exception
        if result.outcome != PrimitiveOutcome.FACT_RETURNED or result.fact is None:
            raise DriverFenceRevoked("runtime execution authorization was revoked")
        fact = result.fact
        if (
            fact.status != RuntimeStatus.RUNNING
            or fact.tenant_id != fence.tenant_id
            or fact.runtime_run_id != fence.runtime_run_id
            or fact.lease_owner != fence.lease_owner
            or fact.lease_epoch != fence.lease_epoch
        ):
            raise DriverFenceRevoked("runtime execution authorization mismatched")
        return fact

    async def _record_driver_checkpoint(
        self,
        fence: DriverFence,
        checkpoint: PersistedDriverCheckpoint,
    ) -> RuntimeCheckpointFact:
        event_id = self._uuid_factory()
        try:
            result = await self._call_repository(
                self._repository.record_checkpoint,
                RecordRuntimeCheckpointRequest(
                    fence.tenant_id,
                    fence.runtime_run_id,
                    fence.lease_owner,
                    fence.lease_epoch,
                    event_id,
                    checkpoint.checkpoint_id,
                    checkpoint.checkpoint_namespace,
                    checkpoint.checkpoint_schema_version,
                    checkpoint.event_payload,
                ),
            )
        except BaseException as exception:
            if isinstance(exception, asyncio.CancelledError):
                raise
            raise DriverFenceRevoked("runtime checkpoint registration failed") from exception
        if result.outcome != PrimitiveOutcome.FACT_RETURNED or result.fact is None:
            raise DriverFenceRevoked("runtime checkpoint registration was fenced")
        fact = result.fact
        if (
            fact.tenant_id != fence.tenant_id
            or fact.runtime_run_id != fence.runtime_run_id
            or fact.event_id != event_id
            or fact.checkpoint_id != checkpoint.checkpoint_id
            or fact.checkpoint_namespace != checkpoint.checkpoint_namespace
            or fact.checkpoint_schema_version != checkpoint.checkpoint_schema_version
            or fact.lease_epoch != fence.lease_epoch
        ):
            raise DriverFenceRevoked("runtime checkpoint registration mismatched")
        return fact

    def _validate_claimed_fact(
        self,
        candidate: RuntimeRunCandidateFact,
        run: RuntimeRunFact,
    ) -> None:
        if (
            run.tenant_id != candidate.tenant_id
            or run.runtime_run_id != candidate.runtime_run_id
            or run.status != RuntimeStatus.RUNNING
            or run.lease_owner != self._require_worker_id()
            or run.lease_epoch < 1
            or run.runtime_version != self._runtime_version
            or run.agent_name != self._agent_name
        ):
            raise RuntimeError("claimed Run fact violates the worker contract")

    def _require_worker_id(self) -> str:
        if self._worker_id is None:
            raise RuntimeError("Run Supervisor worker has not started")
        return self._worker_id

    def _enter_fatal(self, exception: BaseException) -> None:
        self._fatal_error = exception
        self._candidate_probe_healthy = False
        self._state = SupervisorWorkerState.FATAL
        self._stop_event.set()
        if self._active_gate is not None:
            self._active_gate.revoke()


class _RepositoryDriverGate(DriverFenceGate):
    def __init__(
        self,
        worker: DormantRunSupervisorWorker,
        fence: DriverFence,
    ) -> None:
        self._worker = worker
        self._fence = fence
        self._revoked = False
        self._authorization_lock = asyncio.Lock()

    @property
    def revoked(self) -> bool:
        return self._revoked

    def revoke(self) -> None:
        self._revoked = True

    async def authorize_execution(self) -> None:
        # Every model, tool, artifact, sandbox, and checkpoint external write
        # must call this method immediately before I/O. Success is never cached.
        async with self._authorization_lock:
            if self._revoked:
                raise DriverFenceRevoked("runtime execution fence is revoked")
            try:
                await self._worker._driver_authorize(self._fence)
            except BaseException:
                self.revoke()
                raise
            if self._revoked:
                raise DriverFenceRevoked("runtime execution fence was revoked")


class _RepositoryCheckpointSink(DriverCheckpointSink):
    def __init__(
        self,
        worker: DormantRunSupervisorWorker,
        gate: _RepositoryDriverGate,
    ) -> None:
        self._worker = worker
        self._gate = gate

    async def register(
        self,
        fence: DriverFence,
        checkpoint: PersistedDriverCheckpoint,
    ) -> None:
        if fence != self._gate._fence or self._gate.revoked:
            self._gate.revoke()
            raise DriverFenceRevoked("runtime checkpoint fence is revoked")
        try:
            await self._worker._record_driver_checkpoint(fence, checkpoint)
        except BaseException:
            self._gate.revoke()
            raise
        if self._gate.revoked:
            raise DriverFenceRevoked("runtime checkpoint fence was revoked")


async def _offload_to_thread(operation: Callable[[], object]) -> object:
    return await asyncio.to_thread(operation)


async def _await_cancelled(task: asyncio.Task[object]) -> None:
    try:
        await task
    except asyncio.CancelledError:
        pass
    except BaseException:
        pass

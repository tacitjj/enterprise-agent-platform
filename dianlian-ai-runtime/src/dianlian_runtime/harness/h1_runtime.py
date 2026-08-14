from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from datetime import UTC, datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, TypedDict
from uuid import UUID

import aiosqlite
from langchain_core.messages import HumanMessage, SystemMessage

from dianlian_runtime.harness.h1_contracts import (
    CreateH1ExecutionRequest,
    H1ExecutionEvent,
    H1ExecutionSnapshot,
    H1_RUNTIME_PROFILE,
)
from dianlian_runtime.harness.h12_contracts import CreateH12ExecutionRequest
from dianlian_runtime.harness.h12_durable import (
    DurableIntent,
    H12DurableSlots,
    LocalIntentState,
    ModelOutcome,
    ModelPhase,
    RecoveryAction,
    stable_model_call_id,
    stable_tool_call_id,
)
from dianlian_runtime.harness.h12_gateway import (
    H12GatewayFailedSafe,
    H12GatewayOutcomeUnknown,
    JavaH12GatewayClient,
    JavaModelCall11Request,
    JavaToolCall11Request,
)
from dianlian_runtime.harness.model_gateway import (
    JavaModelCallRequest,
    JavaModelCallResponse,
    JavaModelGatewayChatModel,
    ModelGatewayFailure,
    assert_safe_h1_payload,
    build_model_call_request,
)
from dianlian_runtime.harness.upstream import load_pinned_deerflow


class H1IdempotencyConflict(RuntimeError):
    pass


class _H1GraphState(TypedDict, total=False):
    execution_id: UUID
    model_call: JavaModelCallRequest
    output: str


class _H12GraphState(TypedDict, total=False):
    admission: CreateH12ExecutionRequest
    output: str
    failure_code: str
    terminal_intent_id: UUID


class DeerFlowH1Runtime:
    """Versioned durable H1 runtime with legacy and bounded H1 2.2 orchestration."""

    production_takeover_enabled = False

    def __init__(
        self,
        *,
        data_dir: Path,
        upstream_root: Path,
        model: JavaModelGatewayChatModel,
        h12_gateway: JavaH12GatewayClient | None = None,
    ) -> None:
        self._data_dir = data_dir.resolve()
        self._upstream_root = upstream_root.resolve()
        self._model = model
        self._h12_gateway = h12_gateway
        self._h12_slots: H12DurableSlots | None = None
        self._stack: AsyncExitStack | None = None
        self._database: aiosqlite.Connection | None = None
        self._run_manager: Any | None = None
        self._run_store: Any | None = None
        self._event_store: Any | None = None
        self._graph: Any | None = None
        self._h12_graph: Any | None = None
        self._lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        legacy_ready = all(
            value is not None
            for value in (
                self._database,
                self._run_manager,
                self._run_store,
                self._event_store,
                self._graph,
            )
        )
        return legacy_ready and (
            self._h12_gateway is None
            or self._h12_slots is not None and self._h12_graph is not None
        )

    async def __aenter__(self) -> "DeerFlowH1Runtime":
        load_pinned_deerflow(self._upstream_root)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        from deerflow.persistence.engine import (
            close_engine,
            get_session_factory,
            init_engine,
        )
        from deerflow.persistence.run.sql import RunRepository
        from deerflow.runtime.checkpointer.async_provider import _async_checkpointer
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore
        from deerflow.runtime.runs.manager import RunManager

        await init_engine(
            "sqlite",
            url=f"sqlite+aiosqlite:///{self._data_dir / 'deerflow-h1-runs.db'}",
            sqlite_dir=str(self._data_dir),
        )
        session_factory = get_session_factory()
        if session_factory is None:
            raise RuntimeError("DeerFlow H1 SQLite RunStore was not initialized")
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        self._stack.push_async_callback(close_engine)
        checkpointer = await self._stack.enter_async_context(
            _async_checkpointer(
                SimpleNamespace(
                    type="sqlite",
                    connection_string=str(
                        self._data_dir / "deerflow-h1-checkpoints.db"
                    ),
                )
            )
        )
        self._run_store = RunRepository(session_factory)
        self._event_store = JsonlRunEventStore(
            self._data_dir / "deerflow-h1-events"
        )
        self._run_manager = RunManager(
            self._run_store,
            event_store=self._event_store,
        )
        self._database = await aiosqlite.connect(self._data_dir / "h1-runtime.db")
        self._database.row_factory = aiosqlite.Row
        await self._database.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS h1_execution (
                execution_id TEXT PRIMARY KEY,
                admission_snapshot_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                request_hash TEXT NOT NULL,
                snapshot_hash TEXT NOT NULL,
                admission_payload TEXT NOT NULL,
                model_call_id TEXT NOT NULL UNIQUE,
                deerflow_run_id TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL,
                output TEXT,
                failure_code TEXT,
                accepted_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (state IN ('RUNNING', 'SUCCEEDED', 'FAILED'))
            );
            """
        )
        await self._database.commit()
        self._graph = _build_h1_graph(self._model, checkpointer)
        if self._h12_gateway is not None:
            self._h12_slots = await H12DurableSlots(
                self._data_dir / "h12-runtime.db"
            ).__aenter__()
            self._h12_graph = _build_h12_graph(
                self._execute_h12_sequence,
                checkpointer,
            )
        await self._recover_unmapped_h1_runs()
        await self._recover_unknown_executions()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        if self._run_manager is not None:
            await self._run_manager.shutdown()
        if self._database is not None:
            await self._database.close()
        if self._h12_slots is not None:
            await self._h12_slots.__aexit__(None, None, None)
        if self._h12_gateway is not None:
            await self._h12_gateway.aclose()
        await self._model.aclose()
        if self._stack is not None:
            await self._stack.__aexit__(None, None, None)
        self._database = None
        self._run_manager = None
        self._run_store = None
        self._event_store = None
        self._graph = None
        self._h12_graph = None
        self._h12_slots = None
        self._stack = None

    async def start_execution(
        self,
        request: CreateH1ExecutionRequest | CreateH12ExecutionRequest,
    ) -> H1ExecutionSnapshot:
        self._ensure_ready()
        if isinstance(request, CreateH12ExecutionRequest):
            return await self._start_h12_execution(request)
        return await self._start_legacy_execution(request)

    async def _start_legacy_execution(
        self,
        request: CreateH1ExecutionRequest,
    ) -> H1ExecutionSnapshot:
        admission = request.model_dump(mode="json", by_alias=True)
        assert_safe_h1_payload(admission)
        admission_json = _canonical_json(admission)
        model_call = build_model_call_request(request)

        async with self._lock:
            existing = await self._find_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                _require_same_intent(existing, request, admission_json)
                return _snapshot(existing)
            existing = await self._find_by_execution_id(request.execution_id)
            if existing is not None:
                raise H1IdempotencyConflict(
                    "executionId is already bound to another H1 request"
                )
            now = _now_iso()
            run = await self._run_manager.create_or_reject(
                str(request.execution_id),
                metadata={
                    "dianlian_execution_id": str(request.execution_id),
                    "runtime_profile": H1_RUNTIME_PROFILE,
                },
                user_id=str(request.execution_id),
            )
            await self._run_manager.try_start(run.run_id)
            try:
                await self._database.execute("BEGIN IMMEDIATE")
                await self._database.execute(
                    """
                    INSERT INTO h1_execution (
                        execution_id, admission_snapshot_id, idempotency_key,
                        request_hash, snapshot_hash, admission_payload, model_call_id,
                        deerflow_run_id,
                        state, accepted_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RUNNING', ?, ?)
                    """,
                    (
                        str(request.execution_id),
                        str(request.admission_snapshot_id),
                        request.idempotency_key,
                        request.request_hash,
                        request.snapshot_hash,
                        admission_json,
                        str(model_call.model_call_id),
                        run.run_id,
                        now,
                        now,
                    ),
                )
                await self._put_event(
                    str(request.execution_id),
                    run.run_id,
                    "dianlian.h1.started",
                    {
                        "executionId": str(request.execution_id),
                        "modelCallId": str(model_call.model_call_id),
                    },
                )
                await self._database.commit()
            except Exception:
                await self._database.rollback()
                raise

        try:
            graph_result = await self._graph.ainvoke(
                {"execution_id": request.execution_id, "model_call": model_call},
                {"configurable": {"thread_id": str(request.execution_id)}},
            )
            return await self._complete(
                request.execution_id,
                state="SUCCEEDED",
                output=str(graph_result["output"]),
                failure_code=None,
                model_call_id=model_call.model_call_id,
            )
        except ModelGatewayFailure as exception:
            return await self._complete(
                request.execution_id,
                state="FAILED",
                output=None,
                failure_code=exception.code,
                model_call_id=model_call.model_call_id,
            )
        except Exception:
            return await self._complete(
                request.execution_id,
                state="FAILED",
                output=None,
                failure_code="MODEL_GATEWAY_OUTCOME_UNKNOWN",
                model_call_id=model_call.model_call_id,
            )

    async def _start_h12_execution(
        self,
        request: CreateH12ExecutionRequest,
    ) -> H1ExecutionSnapshot:
        if self._h12_gateway is None or self._h12_slots is None or self._h12_graph is None:
            raise RuntimeError("DeerFlow H1 2.2 gateway is unavailable")
        admission = request.model_dump(mode="json", by_alias=True)
        assert_safe_h1_payload(admission)
        admission_json = _canonical_json(admission)
        first_model_call_id = stable_model_call_id(request.execution_id, 1)

        async with self._lock:
            existing = await self._find_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                _require_same_intent(existing, request, admission_json)
                return _snapshot(existing)
            existing = await self._find_by_execution_id(request.execution_id)
            if existing is not None:
                raise H1IdempotencyConflict(
                    "executionId is already bound to another H1 request"
                )
            now = _now_iso()
            run = await self._run_manager.create_or_reject(
                str(request.execution_id),
                metadata={
                    "dianlian_execution_id": str(request.execution_id),
                    "runtime_profile": H1_RUNTIME_PROFILE,
                    "contract_version": "2.2",
                },
                user_id=str(request.execution_id),
            )
            await self._run_manager.try_start(run.run_id)
            try:
                await self._database.execute("BEGIN IMMEDIATE")
                await self._database.execute(
                    """
                    INSERT INTO h1_execution (
                        execution_id, admission_snapshot_id, idempotency_key,
                        request_hash, snapshot_hash, admission_payload, model_call_id,
                        deerflow_run_id, state, accepted_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RUNNING', ?, ?)
                    """,
                    (
                        str(request.execution_id),
                        str(request.admission_snapshot_id),
                        request.idempotency_key,
                        request.request_hash,
                        request.snapshot_hash,
                        admission_json,
                        str(first_model_call_id),
                        run.run_id,
                        now,
                        now,
                    ),
                )
                await self._put_event(
                    str(request.execution_id),
                    run.run_id,
                    "dianlian.h1.started",
                    {
                        "executionId": str(request.execution_id),
                        "modelCallId": str(first_model_call_id),
                    },
                )
                await self._database.commit()
            except Exception:
                await self._database.rollback()
                raise

        graph_result = await self._h12_graph.ainvoke(
            {"admission": request},
            {"configurable": {"thread_id": str(request.execution_id)}},
        )
        return await self._complete_h12_graph_result(request.execution_id, graph_result)

    async def _execute_h12_sequence(
        self,
        admission: CreateH12ExecutionRequest,
    ) -> _H12GraphState:
        slots = self._require_h12_slots()
        for _ in range(8):
            decision = await slots.next_action(admission.execution_id)
            if decision.action in {
                RecoveryAction.DISPATCH_MODEL_1,
                RecoveryAction.REPLAY_MODEL_1,
            }:
                await self._execute_h12_model_slot(admission, 1, decision.intent)
                continue
            if decision.action in {
                RecoveryAction.DISPATCH_TOOL_1,
                RecoveryAction.REPLAY_TOOL_1,
            }:
                await self._execute_h12_tool_slot(admission, decision.intent)
                continue
            if decision.action in {
                RecoveryAction.DISPATCH_MODEL_2,
                RecoveryAction.REPLAY_MODEL_2,
            }:
                await self._execute_h12_model_slot(admission, 2, decision.intent)
                continue
            if decision.intent is None:
                raise RuntimeError("H1 2.2 terminal durable evidence is missing")
            if decision.action == RecoveryAction.COMPLETE_FINAL:
                output = (decision.intent.response_payload or {}).get("assistantText")
                if not isinstance(output, str) or not output.strip():
                    raise RuntimeError("H1 2.2 final response text is missing")
                return {
                    "output": output,
                    "terminal_intent_id": decision.intent.intent_id,
                }
            if decision.action == RecoveryAction.FAIL_TERMINAL:
                return {
                    "failure_code": _h12_failure_code(decision.intent),
                    "terminal_intent_id": decision.intent.intent_id,
                }
            raise RuntimeError("H1 2.2 durable action is unsupported")
        raise RuntimeError("H1 2.2 orchestration exceeded its frozen slot budget")

    async def _execute_h12_model_slot(
        self,
        admission: CreateH12ExecutionRequest,
        call_index: int,
        intent: DurableIntent | None,
    ) -> None:
        slots = self._require_h12_slots()
        gateway = self._require_h12_gateway()
        if intent is None:
            intent = await slots.prepare_model(
                admission.execution_id,
                call_index,
                ModelPhase.TOOL_DECISION
                if call_index == 1
                else ModelPhase.FINAL_AFTER_TOOL,
                _h12_model_intent(admission, call_index),
            )
        if intent.local_state == LocalIntentState.TERMINAL:
            return
        if intent.local_state == LocalIntentState.PREPARED:
            await slots.mark_model_dispatching(admission.execution_id, call_index)
        elif intent.local_state != LocalIntentState.DISPATCHING:
            raise RuntimeError("H1 2.2 model intent has an invalid local state")
        request = _h12_model_request(intent)
        try:
            response = await gateway.invoke_model(admission.execution_id, request)
        except H12GatewayFailedSafe as exception:
            await slots.complete_model(
                admission.execution_id,
                call_index,
                java_status="FAILED_SAFE",
                outcome=None,
                response_payload=_h12_local_failure_payload(
                    "modelCallId",
                    intent.intent_id,
                    "FAILED_SAFE",
                    exception.code,
                ),
            )
            return
        except H12GatewayOutcomeUnknown as exception:
            await slots.complete_model(
                admission.execution_id,
                call_index,
                java_status="OUTCOME_UNKNOWN",
                outcome=None,
                response_payload=_h12_local_failure_payload(
                    "modelCallId",
                    intent.intent_id,
                    "OUTCOME_UNKNOWN",
                    exception.code,
                ),
            )
            return

        outcome = (
            ModelOutcome(response.response_kind)
            if response.response_kind in {"FINAL_TEXT", "TOOL_SELECTION"}
            else None
        )
        await slots.complete_model(
            admission.execution_id,
            call_index,
            java_status=response.status,
            outcome=outcome,
            model_tool_selection_id=(
                response.model_tool_selection_id
                if outcome == ModelOutcome.TOOL_SELECTION
                else None
            ),
            response_payload=response.model_dump(mode="json", by_alias=True),
        )

    async def _execute_h12_tool_slot(
        self,
        admission: CreateH12ExecutionRequest,
        intent: DurableIntent | None,
    ) -> None:
        slots = self._require_h12_slots()
        gateway = self._require_h12_gateway()
        if intent is None:
            source = await slots.require_model_intent(admission.execution_id, 1)
            if source.model_tool_selection_id is None:
                raise RuntimeError("H1 2.2 model selection evidence is missing")
            intent = await slots.prepare_tool(
                admission.execution_id,
                source_model_call_id=source.intent_id,
                model_tool_selection_id=source.model_tool_selection_id,
                request_without_hash=_h12_tool_intent(
                    admission,
                    source.model_tool_selection_id,
                ),
            )
        if intent.local_state == LocalIntentState.TERMINAL:
            return
        if intent.local_state == LocalIntentState.PREPARED:
            await slots.mark_tool_dispatching(admission.execution_id)
        elif intent.local_state != LocalIntentState.DISPATCHING:
            raise RuntimeError("H1 2.2 tool intent has an invalid local state")
        request = _h12_tool_request(intent)
        try:
            response = await gateway.invoke_tool(admission.execution_id, request)
        except H12GatewayFailedSafe as exception:
            await slots.complete_tool(
                admission.execution_id,
                java_status="FAILED_SAFE",
                response_payload=_h12_local_failure_payload(
                    "toolInvocationId",
                    intent.intent_id,
                    "FAILED_SAFE",
                    exception.code,
                ),
            )
            return
        except H12GatewayOutcomeUnknown as exception:
            await slots.complete_tool(
                admission.execution_id,
                java_status="OUTCOME_UNKNOWN",
                response_payload=_h12_local_failure_payload(
                    "toolInvocationId",
                    intent.intent_id,
                    "OUTCOME_UNKNOWN",
                    exception.code,
                ),
            )
            return
        await slots.complete_tool(
            admission.execution_id,
            java_status=response.status,
            response_payload=response.model_dump(mode="json", by_alias=True),
        )

    async def _complete_h12_graph_result(
        self,
        execution_id: UUID,
        graph_result: dict[str, Any],
        *,
        recovered: bool = False,
    ) -> H1ExecutionSnapshot:
        terminal_value = graph_result.get("terminal_intent_id")
        if terminal_value is None:
            raise RuntimeError("H1 2.2 terminal intent identity is missing")
        terminal_intent_id = UUID(str(terminal_value))
        failure_code = graph_result.get("failure_code")
        if failure_code is not None:
            if not isinstance(failure_code, str) or not failure_code:
                raise RuntimeError("H1 2.2 terminal failure code is invalid")
            return await self._complete(
                execution_id,
                state="FAILED",
                output=None,
                failure_code=failure_code,
                model_call_id=terminal_intent_id,
                recovered=recovered,
            )
        output = graph_result.get("output")
        if not isinstance(output, str) or not output.strip():
            raise RuntimeError("H1 2.2 terminal output is invalid")
        return await self._complete(
            execution_id,
            state="SUCCEEDED",
            output=output,
            failure_code=None,
            model_call_id=terminal_intent_id,
            recovered=recovered,
        )

    def _require_h12_slots(self) -> H12DurableSlots:
        if self._h12_slots is None:
            raise RuntimeError("H1 2.2 durable slots are unavailable")
        return self._h12_slots

    def _require_h12_gateway(self) -> JavaH12GatewayClient:
        if self._h12_gateway is None:
            raise RuntimeError("H1 2.2 Java gateway is unavailable")
        return self._h12_gateway

    async def get_execution(self, execution_id: UUID) -> H1ExecutionSnapshot:
        self._ensure_ready()
        async with self._lock:
            row = await self._find_by_execution_id(execution_id)
            if row is None:
                raise KeyError(execution_id)
            persisted_run = await self._run_manager.get(str(row["deerflow_run_id"]))
            if persisted_run is None:
                raise RuntimeError("Mapped DeerFlow H1 run is missing")
            return _snapshot(row)

    async def stream_events(
        self,
        execution_id: UUID,
        *,
        after_sequence: int = 0,
    ) -> list[H1ExecutionEvent]:
        self._ensure_ready()
        if after_sequence < 0:
            raise ValueError("afterSequence must not be negative")
        async with self._lock:
            if await self._find_by_execution_id(execution_id) is None:
                raise KeyError(execution_id)
            row = await self._find_by_execution_id(execution_id)
            events = await self._event_store.list_events(
                str(execution_id),
                str(row["deerflow_run_id"]),
                after_seq=after_sequence,
            )
            return [
                H1ExecutionEvent(
                    int(event["seq"]),
                    str(event["event_type"]),
                    str(event["category"]),
                    event["content"],
                )
                for event in events
            ]

    async def _complete(
        self,
        execution_id: UUID,
        *,
        state: str,
        output: str | None,
        failure_code: str | None,
        model_call_id: UUID,
        recovered: bool = False,
    ) -> H1ExecutionSnapshot:
        async with self._lock:
            row = await self._find_by_execution_id(execution_id)
            if row is None:
                raise KeyError(execution_id)
            if row["state"] != "RUNNING":
                return _snapshot(row)
            now = _now_iso()
            event_type = (
                "dianlian.h1.model.completed"
                if state == "SUCCEEDED"
                else "dianlian.h1.model.failed"
            )
            content = {"modelCallId": str(model_call_id), "state": state}
            if failure_code is not None:
                content["failureCode"] = failure_code
            from deerflow.runtime.runs.schemas import RunStatus

            target_run_status = (
                RunStatus.success if state == "SUCCEEDED" else RunStatus.error
            )
            await self._set_and_verify_run_status(
                execution_id,
                str(row["deerflow_run_id"]),
                target_run_status,
                error=failure_code if state == "FAILED" else None,
                recovered=recovered,
            )
            try:
                await self._database.execute("BEGIN IMMEDIATE")
                await self._database.execute(
                    """
                    UPDATE h1_execution
                       SET state = ?, output = ?, failure_code = ?, updated_at = ?
                     WHERE execution_id = ? AND state = 'RUNNING'
                    """,
                    (state, output, failure_code, now, str(execution_id)),
                )
                await self._put_event(
                    str(execution_id),
                    str(row["deerflow_run_id"]),
                    event_type,
                    content,
                )
                await self._database.commit()
            except Exception:
                await self._database.rollback()
                raise
            completed = await self._find_by_execution_id(execution_id)
            if completed is None:
                raise RuntimeError("H1 execution disappeared during completion")
            return _snapshot(completed)

    async def _recover_unknown_executions(self) -> None:
        cursor = await self._database.execute(
            """
            SELECT execution_id, model_call_id, deerflow_run_id, admission_payload
              FROM h1_execution
             WHERE state = 'RUNNING'
            """
        )
        rows = await cursor.fetchall()
        for row in rows:
            execution_id = UUID(str(row["execution_id"]))
            admission_payload = json.loads(str(row["admission_payload"]))
            persisted_run = await self._run_store.get(
                str(row["deerflow_run_id"]),
                user_id=str(execution_id),
            )
            if persisted_run is None:
                raise RuntimeError("Mapped DeerFlow H1 run is missing during recovery")
            if admission_payload.get("contractVersion") == "2.2":
                if self._h12_graph is None:
                    raise RuntimeError("H1 2.2 recovery gateway is unavailable")
                admission = CreateH12ExecutionRequest.model_validate(admission_payload)
                checkpoint = await self._h12_graph.aget_state(
                    {"configurable": {"thread_id": str(execution_id)}}
                )
                graph_result = dict(checkpoint.values)
                if graph_result.get("terminal_intent_id") is None:
                    graph_result = await self._h12_graph.ainvoke(
                        {"admission": admission},
                        {"configurable": {"thread_id": str(execution_id)}},
                    )
                await self._complete_h12_graph_result(
                    execution_id,
                    graph_result,
                    recovered=True,
                )
                continue
            if persisted_run["status"] == "success":
                state = await self._graph.aget_state(
                    {"configurable": {"thread_id": str(execution_id)}}
                )
                output = state.values.get("output")
                if not isinstance(output, str) or not output:
                    raise RuntimeError("Completed H1 checkpoint output is missing")
                await self._complete(
                    execution_id,
                    state="SUCCEEDED",
                    output=output,
                    failure_code=None,
                    model_call_id=UUID(str(row["model_call_id"])),
                    recovered=True,
                )
                continue
            await self._complete(
                execution_id,
                state="FAILED",
                output=None,
                failure_code="MODEL_GATEWAY_OUTCOME_UNKNOWN",
                model_call_id=UUID(str(row["model_call_id"])),
                recovered=True,
            )

    async def _recover_unmapped_h1_runs(self) -> None:
        cursor = await self._database.execute(
            "SELECT deerflow_run_id FROM h1_execution"
        )
        mapped_run_ids = {
            str(row["deerflow_run_id"]) for row in await cursor.fetchall()
        }
        for run in await self._run_store.list_inflight():
            metadata = run.get("metadata")
            run_id = run.get("run_id")
            if (
                run.get("operation_kind") != "run"
                or not isinstance(metadata, dict)
                or metadata.get("runtime_profile") != H1_RUNTIME_PROFILE
                or not isinstance(run_id, str)
                or not run_id
                or run_id in mapped_run_ids
            ):
                continue
            await self._run_store.update_status(
                run_id,
                "error",
                error="H1_ADMISSION_PERSISTENCE_INTERRUPTED",
            )
            current = await self._run_store.get(
                run_id,
                user_id=run.get("user_id"),
            )
            if current is not None and current.get("status") in {
                "pending",
                "running",
            }:
                raise RuntimeError("Unmapped DeerFlow H1 run remains active")

    async def _set_and_verify_run_status(
        self,
        execution_id: UUID,
        run_id: str,
        status: Any,
        *,
        error: str | None,
        recovered: bool,
    ) -> None:
        if recovered:
            persisted_update = await self._run_store.update_run_completion(
                run_id,
                status=status.value,
                error=error,
            )
            if persisted_update is False:
                raise RuntimeError("DeerFlow H1 recovered status was rejected")
        else:
            await self._run_manager.set_status(run_id, status, error=error)
        persisted = await self._run_store.get(
            run_id,
            user_id=str(execution_id),
        )
        if persisted is None or persisted.get("status") != status.value:
            raise RuntimeError("DeerFlow H1 terminal status was not persisted")

    async def _put_event(
        self,
        thread_id: str,
        run_id: str,
        event_type: str,
        content: dict[str, str],
    ) -> None:
        await self._event_store.put_if_absent(
            thread_id=thread_id,
            run_id=run_id,
            event_type=event_type,
            category="lifecycle",
            content=content,
        )

    async def _find_by_execution_id(self, execution_id: UUID) -> aiosqlite.Row | None:
        cursor = await self._database.execute(
            "SELECT * FROM h1_execution WHERE execution_id = ?",
            (str(execution_id),),
        )
        return await cursor.fetchone()

    async def _find_by_idempotency_key(self, key: str) -> aiosqlite.Row | None:
        cursor = await self._database.execute(
            "SELECT * FROM h1_execution WHERE idempotency_key = ?",
            (key,),
        )
        return await cursor.fetchone()

    def _ensure_ready(self) -> None:
        if not self.ready:
            raise RuntimeError("DeerFlow H1 runtime is not started")


def _build_h1_graph(model: JavaModelGatewayChatModel, checkpointer: Any) -> Any:
    from langgraph.graph import END, START, StateGraph

    async def invoke_java_model(state: _H1GraphState) -> dict[str, str]:
        request = state["model_call"]
        result = await model.agenerate(
            [[
                SystemMessage(content=request.system_instruction),
                HumanMessage(content=request.messages[0].text),
            ]],
            execution_id=state["execution_id"],
            model_call_request=request,
        )
        return {"output": result.generations[0][0].message.text}

    builder = StateGraph(_H1GraphState)
    builder.add_node("java_model_gateway", invoke_java_model)
    builder.add_edge(START, "java_model_gateway")
    builder.add_edge("java_model_gateway", END)
    return builder.compile(checkpointer=checkpointer)


def _build_h12_graph(
    execute: Callable[[CreateH12ExecutionRequest], Awaitable[_H12GraphState]],
    checkpointer: Any,
) -> Any:
    from langgraph.graph import END, START, StateGraph

    async def orchestrate(state: _H12GraphState) -> _H12GraphState:
        return await execute(state["admission"])

    builder = StateGraph(_H12GraphState)
    builder.add_node("h12_durable_orchestration", orchestrate)
    builder.add_edge(START, "h12_durable_orchestration")
    builder.add_edge("h12_durable_orchestration", END)
    return builder.compile(checkpointer=checkpointer)


def _h12_model_intent(
    admission: CreateH12ExecutionRequest,
    call_index: int,
) -> dict[str, Any]:
    if call_index not in {1, 2}:
        raise ValueError("H1 2.2 model call index is invalid")
    return {
        "contractVersion": "1.1",
        "modelCallId": str(stable_model_call_id(admission.execution_id, call_index)),
        "callIndex": call_index,
        "callPhase": "INITIAL" if call_index == 1 else "AFTER_TOOL",
        "executionGeneration": admission.execution_generation,
        "idempotencyKey": f"h12:{admission.execution_id}:model:{call_index}",
        "admissionSnapshotId": str(admission.admission_snapshot_id),
        "promptSnapshotId": str(admission.prompt.prompt_snapshot_id),
        "contextSnapshotId": str(admission.context.context_snapshot_id),
        "toolPolicySnapshotId": str(admission.tool_policy.tool_policy_snapshot_id),
        "orchestrationPolicySnapshotId": str(
            admission.orchestration_policy.orchestration_policy_snapshot_id
        ),
        "modelRouteBindingId": str(admission.model_route.route_binding_id),
        "modelRouteStateVersion": admission.model_route.route_state_version,
        "modelDefinitionId": str(admission.model_route.model_definition_id),
        "modelConfigurationVersion": admission.model_route.model_configuration_version,
    }


def _h12_tool_intent(
    admission: CreateH12ExecutionRequest,
    model_tool_selection_id: UUID,
) -> dict[str, Any]:
    return {
        "contractVersion": "1.1",
        "selectionMode": "MODEL_SELECTED",
        "toolInvocationId": str(stable_tool_call_id(admission.execution_id)),
        "executionGeneration": admission.execution_generation,
        "admissionSnapshotId": str(admission.admission_snapshot_id),
        "toolPolicySnapshotId": str(admission.tool_policy.tool_policy_snapshot_id),
        "modelToolSelectionId": str(model_tool_selection_id),
        "toolCallSlot": 1,
        "idempotencyKey": f"h12:{admission.execution_id}:tool:1",
    }


def _h12_model_request(intent: DurableIntent) -> JavaModelCall11Request:
    payload = _canonical_intent_payload(intent)
    payload["requestHash"] = intent.request_hash
    return JavaModelCall11Request.model_validate_json(_canonical_json(payload))


def _h12_tool_request(intent: DurableIntent) -> JavaToolCall11Request:
    payload = _canonical_intent_payload(intent)
    payload["requestHash"] = intent.request_hash
    return JavaToolCall11Request.model_validate_json(_canonical_json(payload))


def _canonical_intent_payload(intent: DurableIntent) -> dict[str, Any]:
    payload = json.loads(intent.canonical_request)
    if not isinstance(payload, dict):
        raise RuntimeError("H1 2.2 durable intent payload is invalid")
    return payload


def _h12_local_failure_payload(
    identity_key: str,
    intent_id: UUID,
    status: str,
    failure_code: str,
) -> dict[str, Any]:
    return {
        "contractVersion": "1.1",
        identity_key: str(intent_id),
        "status": status,
        "failureCode": failure_code,
    }


def _h12_failure_code(intent: DurableIntent) -> str:
    payload = intent.response_payload or {}
    failure_code = payload.get("failureCode")
    if isinstance(failure_code, str) and failure_code:
        return failure_code
    return {
        "USAGE_PENDING": "MODEL_USAGE_RECONCILIATION_REQUIRED",
        "RESPONSE_REJECTED": "MODEL_RESPONSE_REJECTED",
        "FAILED_SAFE": "H12_FAILED_SAFE",
        "OUTCOME_UNKNOWN": "H12_OUTCOME_UNKNOWN",
    }.get(intent.java_status or "", "H12_TERMINAL_FAILURE")


def _require_same_intent(
    row: aiosqlite.Row,
    request: CreateH1ExecutionRequest | CreateH12ExecutionRequest,
    admission_json: str,
) -> None:
    if (
        row["execution_id"] != str(request.execution_id)
        or row["admission_snapshot_id"] != str(request.admission_snapshot_id)
        or row["request_hash"] != request.request_hash
        or row["snapshot_hash"] != request.snapshot_hash
        or row["admission_payload"] != admission_json
    ):
        raise H1IdempotencyConflict(
            "idempotencyKey is already bound to another H1 request"
        )


def _snapshot(row: aiosqlite.Row) -> H1ExecutionSnapshot:
    admission_payload = json.loads(str(row["admission_payload"]))
    contract_version = admission_payload.get("contractVersion")
    if contract_version not in {"2.0", "2.1", "2.2"}:
        raise RuntimeError("Persisted H1 contract version is invalid")
    return H1ExecutionSnapshot(
        contract_version=contract_version,
        execution_id=UUID(str(row["execution_id"])),
        admission_snapshot_id=UUID(str(row["admission_snapshot_id"])),
        idempotency_key=str(row["idempotency_key"]),
        state=str(row["state"]),
        output=str(row["output"]) if row["output"] is not None else None,
        failure_code=(
            str(row["failure_code"]) if row["failure_code"] is not None else None
        ),
        accepted_at=datetime.fromisoformat(str(row["accepted_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()

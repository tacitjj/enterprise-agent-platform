from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from datetime import UTC, datetime
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypedDict

import aiosqlite
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from dianlian_runtime.harness.contracts import (
    ExecutionEvent,
    ExecutionSnapshot,
    StartExecutionRequest,
)
from dianlian_runtime.harness.upstream import load_pinned_deerflow


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class GuidancePreconditionRejected(RuntimeError):
    """A guidance request rejected before DeerFlow was invoked."""

    NOT_WAITING_CODE = "RUNTIME_GUIDANCE_NOT_WAITING"
    CHECKPOINT_STALE_CODE = "RUNTIME_GUIDANCE_CHECKPOINT_STALE"

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GuidanceOutcomeUnknown(RuntimeError):
    """DeerFlow invocation started, so applying the guidance is uncertain."""


class H0IdempotencyConflict(RuntimeError):
    """An H0 identity is already bound to a different request."""


class _DummyState(TypedDict, total=False):
    prompt: str
    guidance: str
    result: str


def _await_guidance(_: _DummyState) -> dict[str, str]:
    guidance = interrupt({"kind": "guidance", "message": "H0 dummy guidance"})
    return {"guidance": str(guidance)}


def _complete_dummy(state: _DummyState) -> dict[str, str]:
    return {"result": f"{state['prompt']} | guidance={state['guidance']}"}


class DeerFlowH0Runtime:
    """Single-node H0 adapter over the pinned DeerFlow runtime kernel.

    This proves persistent run metadata, events and checkpoints without models,
    tools, memory or sandbox. It is intentionally not a production supervisor:
    the pinned upstream cannot claim and resume an arbitrary graph operation in a
    different worker process, so cross-process takeover remains disabled.
    """

    production_takeover_enabled = False

    def __init__(self, *, data_dir: Path, upstream_root: Path) -> None:
        self._data_dir = data_dir.resolve()
        self._upstream_root = upstream_root.resolve()
        self._stack: AsyncExitStack | None = None
        self._mapping_db: aiosqlite.Connection | None = None
        self._run_manager: Any | None = None
        self._run_store: Any | None = None
        self._event_store: Any | None = None
        self._graph: Any | None = None
        self._lock = asyncio.Lock()

    @property
    def ready(self) -> bool:
        return all(
            value is not None
            for value in (
                self._mapping_db,
                self._run_manager,
                self._run_store,
                self._event_store,
                self._graph,
            )
        )

    async def __aenter__(self) -> DeerFlowH0Runtime:
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
            url=f"sqlite+aiosqlite:///{self._data_dir / 'deerflow-runs.db'}",
            sqlite_dir=str(self._data_dir),
        )
        session_factory = get_session_factory()
        if session_factory is None:
            raise RuntimeError("DeerFlow SQLite RunStore was not initialized")

        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        self._stack.push_async_callback(close_engine)
        checkpointer = await self._stack.enter_async_context(
            _async_checkpointer(
                SimpleNamespace(
                    type="sqlite",
                    connection_string=str(self._data_dir / "deerflow-checkpoints.db"),
                )
            )
        )
        self._run_store = RunRepository(session_factory)
        self._event_store = JsonlRunEventStore(self._data_dir / "deerflow-events")
        self._run_manager = RunManager(
            self._run_store,
            event_store=self._event_store,
        )
        self._graph = _build_dummy_graph(checkpointer)
        self._mapping_db = await aiosqlite.connect(self._data_dir / "dianlian-map.db")
        self._mapping_db.row_factory = aiosqlite.Row
        await self._mapping_db.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            CREATE TABLE IF NOT EXISTS execution_mapping (
                execution_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                thread_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                deerflow_run_id TEXT UNIQUE,
                status TEXT NOT NULL,
                checkpoint_id TEXT,
                result TEXT,
                cancel_action TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        await self._mapping_db.commit()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if self._run_manager is not None:
            await self._run_manager.shutdown()
        if self._mapping_db is not None:
            await self._mapping_db.close()
        if self._stack is not None:
            await self._stack.__aexit__(exc_type, exc, traceback)
        self._mapping_db = None
        self._run_manager = None
        self._run_store = None
        self._event_store = None
        self._graph = None
        self._stack = None

    async def start_execution(
        self,
        request: StartExecutionRequest,
    ) -> ExecutionSnapshot:
        self._ensure_ready()
        _validate_id(request.execution_id, "execution_id")
        _validate_id(request.thread_id, "thread_id")
        if not request.idempotency_key.strip():
            raise ValueError("idempotency_key must not be blank")
        if not request.request_hash.strip():
            raise ValueError("request_hash must not be blank")
        if not request.prompt.strip():
            raise ValueError("prompt must not be blank")

        async with self._lock:
            existing = await self._find_by_idempotency_key(request.idempotency_key)
            if existing is not None:
                _validate_replay(existing, request)
                if existing["status"] != "CREATING" or existing["deerflow_run_id"]:
                    return _snapshot(existing)
            else:
                existing = await self._find_by_execution_id(request.execution_id)
                if existing is not None:
                    raise H0IdempotencyConflict(
                        "execution_id is already mapped to another request"
                    )

                now = _now_iso()
                await self._mapping_db.execute(
                    """
                    INSERT INTO execution_mapping (
                        execution_id, idempotency_key, thread_id, request_hash, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'CREATING', ?, ?)
                    """,
                    (
                        request.execution_id,
                        request.idempotency_key,
                        request.thread_id,
                        request.request_hash,
                        now,
                        now,
                    ),
                )
                await self._mapping_db.commit()

            run = await self._run_manager.create(
                request.thread_id,
                metadata={"dianlian_execution_id": request.execution_id},
                user_id=request.execution_id,
            )
            await self._run_manager.try_start(run.run_id)
            await self._update_mapping(
                request.execution_id,
                deerflow_run_id=run.run_id,
                status="RUNNING",
            )
            await self._put_event(
                request.thread_id,
                run.run_id,
                "dianlian.h0.started",
                "lifecycle",
                {"executionId": request.execution_id},
            )

            graph_config = _graph_config(request.execution_id)
            await self._graph.ainvoke({"prompt": request.prompt}, graph_config)
            state = await self._graph.aget_state(graph_config)
            checkpoint_id = _checkpoint_id(state)
            await self._update_mapping(
                request.execution_id,
                status="WAITING_GUIDANCE",
                checkpoint_id=checkpoint_id,
            )
            await self._put_event(
                request.thread_id,
                run.run_id,
                "dianlian.h0.checkpoint",
                "lifecycle",
                {"checkpointId": checkpoint_id},
            )
            return await self.get_execution(request.execution_id)

    async def guide(
        self,
        execution_id: str,
        *,
        expected_checkpoint_id: str,
        guidance: str,
    ) -> ExecutionSnapshot:
        self._ensure_ready()
        if not guidance.strip():
            raise ValueError("guidance must not be blank")
        async with self._lock:
            row = await self._find_by_execution_id(execution_id)
            if row is None:
                raise KeyError(execution_id)
            if row["status"] == "SUCCEEDED":
                return _snapshot(row)
            if row["status"] != "WAITING_GUIDANCE":
                raise GuidancePreconditionRejected(
                    GuidancePreconditionRejected.NOT_WAITING_CODE,
                    f"Execution {execution_id} is not waiting for guidance",
                )
            if row["checkpoint_id"] != expected_checkpoint_id:
                raise GuidancePreconditionRejected(
                    GuidancePreconditionRejected.CHECKPOINT_STALE_CODE,
                    "checkpoint changed before guidance was applied",
                )

            try:
                result = await self._graph.ainvoke(
                    Command(resume=guidance),
                    _graph_config(execution_id),
                )
                result_text = str(result.get("result", ""))
                state = await self._graph.aget_state(_graph_config(execution_id))
                checkpoint_id = _checkpoint_id(state)
                await self._run_manager.set_status(
                    row["deerflow_run_id"],
                    _run_status("success"),
                )
                await self._update_mapping(
                    execution_id,
                    status="SUCCEEDED",
                    checkpoint_id=checkpoint_id,
                    result=result_text,
                )
                await self._put_event(
                    row["thread_id"],
                    row["deerflow_run_id"],
                    "dianlian.h0.completed",
                    "lifecycle",
                    {"checkpointId": checkpoint_id},
                )
                return await self.get_execution(execution_id)
            except Exception as exception:
                raise GuidanceOutcomeUnknown(
                    "Guidance invocation started but its outcome could not be confirmed"
                ) from exception

    async def cancel(
        self,
        execution_id: str,
        *,
        action: str = "interrupt",
    ) -> ExecutionSnapshot:
        self._ensure_ready()
        if action not in {"interrupt", "rollback"}:
            raise ValueError("cancel action must be interrupt or rollback")
        async with self._lock:
            row = await self._find_by_execution_id(execution_id)
            if row is None:
                raise KeyError(execution_id)
            if row["status"] in {"SUCCEEDED", "INTERRUPTED"}:
                return _snapshot(row)
            await self._run_manager.cancel(row["deerflow_run_id"], action=action)
            await self._update_mapping(
                execution_id,
                status="INTERRUPTED",
                cancel_action=action,
            )
            await self._put_event(
                row["thread_id"],
                row["deerflow_run_id"],
                "dianlian.h0.cancelled",
                "lifecycle",
                {"action": action},
            )
            return await self.get_execution(execution_id)

    async def get_execution(self, execution_id: str) -> ExecutionSnapshot:
        self._ensure_ready()
        row = await self._find_by_execution_id(execution_id)
        if row is None:
            raise KeyError(execution_id)
        if row["deerflow_run_id"]:
            persisted_run = await self._run_manager.get(row["deerflow_run_id"])
            if persisted_run is None:
                raise RuntimeError("Mapped DeerFlow run is missing")
        return _snapshot(row)

    async def stream_events(
        self,
        execution_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[ExecutionEvent]:
        self._ensure_ready()
        row = await self._find_by_execution_id(execution_id)
        if row is None:
            raise KeyError(execution_id)
        events = await self._event_store.list_events(
            row["thread_id"],
            row["deerflow_run_id"],
            after_seq=after_sequence,
        )
        return [
            ExecutionEvent(
                sequence=int(event["seq"]),
                event_type=str(event["event_type"]),
                category=str(event["category"]),
                content=event["content"],
            )
            for event in events
        ]

    async def _find_by_idempotency_key(self, key: str) -> aiosqlite.Row | None:
        cursor = await self._mapping_db.execute(
            "SELECT * FROM execution_mapping WHERE idempotency_key = ?",
            (key,),
        )
        return await cursor.fetchone()

    async def _find_by_execution_id(self, execution_id: str) -> aiosqlite.Row | None:
        cursor = await self._mapping_db.execute(
            "SELECT * FROM execution_mapping WHERE execution_id = ?",
            (execution_id,),
        )
        return await cursor.fetchone()

    async def _update_mapping(self, execution_id: str, **changes: Any) -> None:
        allowed = {
            "deerflow_run_id",
            "status",
            "checkpoint_id",
            "result",
            "cancel_action",
        }
        if not changes or not changes.keys() <= allowed:
            raise ValueError("unsupported execution mapping update")
        assignments = ", ".join(f"{name} = ?" for name in changes)
        values = [*changes.values(), _now_iso(), execution_id]
        await self._mapping_db.execute(
            f"UPDATE execution_mapping SET {assignments}, updated_at = ? WHERE execution_id = ?",
            values,
        )
        await self._mapping_db.commit()

    async def _put_event(
        self,
        thread_id: str,
        run_id: str,
        event_type: str,
        category: str,
        content: dict[str, Any],
    ) -> None:
        await self._event_store.put_if_absent(
            thread_id=thread_id,
            run_id=run_id,
            event_type=event_type,
            category=category,
            content=content,
        )

    def _ensure_ready(self) -> None:
        if any(
            value is None
            for value in (
                self._mapping_db,
                self._run_manager,
                self._run_store,
                self._event_store,
                self._graph,
            )
        ):
            raise RuntimeError("DeerFlow H0 runtime is not started")


def _build_dummy_graph(checkpointer: Any) -> Any:
    builder = StateGraph(_DummyState)
    builder.add_node("await_guidance", _await_guidance)
    builder.add_node("complete", _complete_dummy)
    builder.add_edge(START, "await_guidance")
    builder.add_edge("await_guidance", "complete")
    builder.add_edge("complete", END)
    return builder.compile(checkpointer=checkpointer)


def _graph_config(execution_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": execution_id}}


def _checkpoint_id(state: Any) -> str:
    value = state.config.get("configurable", {}).get("checkpoint_id")
    if not value:
        raise RuntimeError("DeerFlow checkpoint ID is missing")
    return str(value)


def _run_status(name: str) -> Any:
    from deerflow.runtime.runs.schemas import RunStatus

    return RunStatus(name)


def _snapshot(row: aiosqlite.Row) -> ExecutionSnapshot:
    return ExecutionSnapshot(
        execution_id=str(row["execution_id"]),
        idempotency_key=str(row["idempotency_key"]),
        thread_id=str(row["thread_id"]),
        request_hash=str(row["request_hash"]),
        deerflow_run_id=(
            str(row["deerflow_run_id"]) if row["deerflow_run_id"] else None
        ),
        status=str(row["status"]),
        checkpoint_id=(str(row["checkpoint_id"]) if row["checkpoint_id"] else None),
        result=str(row["result"]) if row["result"] else None,
        cancel_action=str(row["cancel_action"]) if row["cancel_action"] else None,
        accepted_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def _validate_replay(row: aiosqlite.Row, request: StartExecutionRequest) -> None:
    if (
        row["execution_id"] != request.execution_id
        or row["thread_id"] != request.thread_id
        or row["request_hash"] != request.request_hash
    ):
        raise H0IdempotencyConflict(
            "idempotency_key is already mapped to another request"
        )


def _validate_id(value: str, label: str) -> None:
    if not value or not _SAFE_ID.fullmatch(value):
        raise ValueError(f"{label} must contain only letters, digits, dash or underscore")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()

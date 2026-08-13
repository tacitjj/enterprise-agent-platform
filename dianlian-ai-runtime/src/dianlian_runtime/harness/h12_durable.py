from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import aiosqlite


class H12IntentConflict(RuntimeError):
    pass


class H12CausalFenceRejected(RuntimeError):
    pass


class LocalIntentState(StrEnum):
    PREPARED = "PREPARED"
    DISPATCHING = "DISPATCHING"
    TERMINAL = "TERMINAL"


class ModelPhase(StrEnum):
    TOOL_DECISION = "TOOL_DECISION"
    FINAL_AFTER_TOOL = "FINAL_AFTER_TOOL"


class ModelOutcome(StrEnum):
    FINAL_TEXT = "FINAL_TEXT"
    TOOL_SELECTION = "TOOL_SELECTION"


class RecoveryAction(StrEnum):
    DISPATCH_MODEL_1 = "DISPATCH_MODEL_1"
    REPLAY_MODEL_1 = "REPLAY_MODEL_1"
    DISPATCH_TOOL_1 = "DISPATCH_TOOL_1"
    REPLAY_TOOL_1 = "REPLAY_TOOL_1"
    DISPATCH_MODEL_2 = "DISPATCH_MODEL_2"
    REPLAY_MODEL_2 = "REPLAY_MODEL_2"
    COMPLETE_FINAL = "COMPLETE_FINAL"
    FAIL_TERMINAL = "FAIL_TERMINAL"


_MODEL_CONTINUABLE = {"RESPONSE_RECEIVED"}
_MODEL_TERMINAL = {
    "RESPONSE_RECEIVED",
    "RESPONSE_REJECTED",
    "USAGE_PENDING",
    "FAILED_SAFE",
    "OUTCOME_UNKNOWN",
}
_TOOL_TERMINAL = {"SUCCEEDED", "FAILED_SAFE", "OUTCOME_UNKNOWN"}
_FORBIDDEN_KEYS = {
    "apikey",
    "authorization",
    "bearer",
    "credentialref",
    "baseurl",
    "password",
    "privatekey",
    "secret",
    "token",
}


@dataclass(frozen=True)
class DurableIntent:
    execution_id: UUID
    call_index: int
    intent_id: UUID
    request_hash: str
    canonical_request: str
    local_state: LocalIntentState
    java_status: str | None
    outcome_kind: ModelOutcome | None
    model_tool_selection_id: UUID | None
    response_payload: dict[str, Any] | None


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    intent: DurableIntent | None
    failure_code: str | None = None


def stable_model_call_id(execution_id: UUID, call_index: int) -> UUID:
    if call_index not in {1, 2}:
        raise ValueError("H1 2.2 model call index must be one or two")
    return uuid5(NAMESPACE_URL, f"dianlian:h1:{execution_id}:model-call:{call_index}")


def stable_tool_call_id(execution_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"dianlian:h1:{execution_id}:tool-call:1")


def canonical_intent(value: dict[str, Any]) -> tuple[str, str]:
    _assert_no_forbidden_keys(value)
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class H12DurableSlots:
    """Local intent journal for H1 2.2. It never authorizes an external retry."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._database: aiosqlite.Connection | None = None

    async def __aenter__(self) -> "H12DurableSlots":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._database = await aiosqlite.connect(self._path)
        self._database.row_factory = aiosqlite.Row
        await self._database.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS h12_model_call (
                execution_id TEXT NOT NULL,
                call_index INTEGER NOT NULL,
                model_call_id TEXT NOT NULL UNIQUE,
                phase TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                canonical_request TEXT NOT NULL,
                local_state TEXT NOT NULL,
                java_status TEXT,
                outcome_kind TEXT,
                model_tool_selection_id TEXT,
                response_payload TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (execution_id, call_index),
                CHECK (call_index IN (1, 2)),
                CHECK (phase IN ('TOOL_DECISION', 'FINAL_AFTER_TOOL')),
                CHECK (local_state IN ('PREPARED', 'DISPATCHING', 'TERMINAL')),
                CHECK (outcome_kind IS NULL OR outcome_kind IN ('FINAL_TEXT', 'TOOL_SELECTION')),
                CHECK ((local_state = 'TERMINAL') = (java_status IS NOT NULL)),
                CHECK (response_payload IS NULL OR local_state = 'TERMINAL')
            );
            CREATE TABLE IF NOT EXISTS h12_tool_call (
                execution_id TEXT PRIMARY KEY,
                tool_call_slot INTEGER NOT NULL,
                tool_invocation_id TEXT NOT NULL UNIQUE,
                source_model_call_id TEXT NOT NULL,
                model_tool_selection_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                canonical_request TEXT NOT NULL,
                local_state TEXT NOT NULL,
                java_status TEXT,
                response_payload TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (tool_call_slot = 1),
                CHECK (local_state IN ('PREPARED', 'DISPATCHING', 'TERMINAL')),
                CHECK ((local_state = 'TERMINAL') = (java_status IS NOT NULL)),
                CHECK (response_payload IS NULL OR local_state = 'TERMINAL')
            );
            """
        )
        await self._database.commit()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        if self._database is not None:
            await self._database.close()
        self._database = None

    async def prepare_model(
        self,
        execution_id: UUID,
        call_index: int,
        phase: ModelPhase,
        request_without_hash: dict[str, Any],
    ) -> DurableIntent:
        expected_phase = (
            ModelPhase.TOOL_DECISION if call_index == 1 else ModelPhase.FINAL_AFTER_TOOL
        )
        if phase != expected_phase:
            raise ValueError("H1 2.2 model phase does not match call index")
        if call_index == 2:
            await self._require_successful_tool(execution_id)
        canonical, request_hash = canonical_intent(request_without_hash)
        intent_id = stable_model_call_id(execution_id, call_index)
        now = _now_iso()
        database = self._require_database()
        await database.execute(
            """
            INSERT INTO h12_model_call (
                execution_id, call_index, model_call_id, phase, request_hash,
                canonical_request, local_state, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'PREPARED', ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                str(execution_id),
                call_index,
                str(intent_id),
                phase.value,
                request_hash,
                canonical,
                now,
                now,
            ),
        )
        await database.commit()
        intent = await self._load_model(execution_id, call_index)
        if intent is None or (
            intent.intent_id != intent_id
            or intent.request_hash != request_hash
            or intent.canonical_request != canonical
        ):
            raise H12IntentConflict("model call slot is bound to another intent")
        return intent

    async def prepare_tool(
        self,
        execution_id: UUID,
        *,
        source_model_call_id: UUID,
        model_tool_selection_id: UUID,
        request_without_hash: dict[str, Any],
    ) -> DurableIntent:
        call_one = await self._load_model_row(execution_id, 1)
        if (
            call_one is None
            or call_one["local_state"] != LocalIntentState.TERMINAL.value
            or call_one["java_status"] not in _MODEL_CONTINUABLE
            or call_one["outcome_kind"] != ModelOutcome.TOOL_SELECTION.value
            or call_one["model_call_id"] != str(source_model_call_id)
            or call_one["model_tool_selection_id"] != str(model_tool_selection_id)
        ):
            raise H12CausalFenceRejected(
                "tool slot requires the exact terminal model selection evidence"
            )
        canonical, request_hash = canonical_intent(request_without_hash)
        intent_id = stable_tool_call_id(execution_id)
        now = _now_iso()
        database = self._require_database()
        await database.execute(
            """
            INSERT INTO h12_tool_call (
                execution_id, tool_call_slot, tool_invocation_id,
                source_model_call_id, model_tool_selection_id, request_hash,
                canonical_request, local_state, created_at, updated_at
            ) VALUES (?, 1, ?, ?, ?, ?, ?, 'PREPARED', ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                str(execution_id),
                str(intent_id),
                str(source_model_call_id),
                str(model_tool_selection_id),
                request_hash,
                canonical,
                now,
                now,
            ),
        )
        await database.commit()
        intent = await self._load_tool(execution_id)
        if intent is None or (
            intent.intent_id != intent_id
            or intent.request_hash != request_hash
            or intent.canonical_request != canonical
        ):
            raise H12IntentConflict("tool call slot is bound to another intent")
        return intent

    async def mark_model_dispatching(self, execution_id: UUID, call_index: int) -> None:
        await self._mark_dispatching("h12_model_call", execution_id, call_index)

    async def mark_tool_dispatching(self, execution_id: UUID) -> None:
        await self._mark_dispatching("h12_tool_call", execution_id, None)

    async def complete_model(
        self,
        execution_id: UUID,
        call_index: int,
        *,
        java_status: str,
        outcome: ModelOutcome | None,
        response_payload: dict[str, Any],
        model_tool_selection_id: UUID | None = None,
    ) -> None:
        if java_status not in _MODEL_TERMINAL:
            raise ValueError("unsupported terminal Java model status")
        if java_status == "RESPONSE_RECEIVED":
            if outcome is None:
                raise ValueError("successful model call requires an outcome")
            if call_index == 2 and outcome != ModelOutcome.FINAL_TEXT:
                raise ValueError("second model call must produce final text")
            if outcome == ModelOutcome.TOOL_SELECTION and model_tool_selection_id is None:
                raise ValueError("tool selection requires its Java evidence id")
            if outcome == ModelOutcome.FINAL_TEXT and model_tool_selection_id is not None:
                raise ValueError("final text cannot carry a tool selection id")
        elif java_status == "USAGE_PENDING":
            if call_index == 2 and outcome not in {None, ModelOutcome.FINAL_TEXT}:
                raise ValueError("pending second model call cannot select another tool")
            if outcome == ModelOutcome.TOOL_SELECTION and model_tool_selection_id is None:
                raise ValueError("pending tool selection requires its Java evidence id")
            if outcome != ModelOutcome.TOOL_SELECTION and model_tool_selection_id is not None:
                raise ValueError("pending non-selection cannot carry a tool selection id")
        elif outcome is not None or model_tool_selection_id is not None:
            raise ValueError("failed model call cannot carry an outcome")
        await self._complete(
            "h12_model_call",
            execution_id,
            call_index,
            java_status,
            response_payload,
            outcome.value if outcome is not None else None,
            str(model_tool_selection_id) if model_tool_selection_id is not None else None,
        )

    async def complete_tool(
        self,
        execution_id: UUID,
        *,
        java_status: str,
        response_payload: dict[str, Any],
    ) -> None:
        if java_status not in _TOOL_TERMINAL:
            raise ValueError("unsupported terminal Java tool status")
        await self._complete(
            "h12_tool_call",
            execution_id,
            None,
            java_status,
            response_payload,
            None,
            None,
        )

    async def next_action(self, execution_id: UUID) -> RecoveryDecision:
        call_one = await self._load_model(execution_id, 1)
        if call_one is None:
            return RecoveryDecision(RecoveryAction.DISPATCH_MODEL_1, None)
        if call_one.local_state == LocalIntentState.PREPARED:
            return RecoveryDecision(RecoveryAction.DISPATCH_MODEL_1, call_one)
        if call_one.local_state == LocalIntentState.DISPATCHING:
            return RecoveryDecision(RecoveryAction.REPLAY_MODEL_1, call_one)
        row_one = await self._load_model_row(execution_id, 1)
        if call_one.java_status not in _MODEL_CONTINUABLE:
            return RecoveryDecision(
                RecoveryAction.FAIL_TERMINAL,
                call_one,
                call_one.java_status,
            )
        if row_one is None:
            raise RuntimeError("terminal model call evidence disappeared")
        if row_one["outcome_kind"] == ModelOutcome.FINAL_TEXT.value:
            return RecoveryDecision(RecoveryAction.COMPLETE_FINAL, call_one)

        tool = await self._load_tool(execution_id)
        if tool is None:
            return RecoveryDecision(RecoveryAction.DISPATCH_TOOL_1, None)
        if tool.local_state == LocalIntentState.PREPARED:
            return RecoveryDecision(RecoveryAction.DISPATCH_TOOL_1, tool)
        if tool.local_state == LocalIntentState.DISPATCHING:
            return RecoveryDecision(RecoveryAction.REPLAY_TOOL_1, tool)
        if tool.java_status != "SUCCEEDED":
            return RecoveryDecision(
                RecoveryAction.FAIL_TERMINAL,
                tool,
                tool.java_status,
            )

        call_two = await self._load_model(execution_id, 2)
        if call_two is None:
            return RecoveryDecision(RecoveryAction.DISPATCH_MODEL_2, None)
        if call_two.local_state == LocalIntentState.PREPARED:
            return RecoveryDecision(RecoveryAction.DISPATCH_MODEL_2, call_two)
        if call_two.local_state == LocalIntentState.DISPATCHING:
            return RecoveryDecision(RecoveryAction.REPLAY_MODEL_2, call_two)
        if call_two.java_status not in _MODEL_CONTINUABLE:
            return RecoveryDecision(
                RecoveryAction.FAIL_TERMINAL,
                call_two,
                call_two.java_status,
            )
        return RecoveryDecision(RecoveryAction.COMPLETE_FINAL, call_two)

    async def require_model_intent(
        self,
        execution_id: UUID,
        call_index: int,
    ) -> DurableIntent:
        intent = await self._load_model(execution_id, call_index)
        if intent is None:
            raise H12CausalFenceRejected("required model intent is missing")
        return intent

    async def _require_successful_tool(self, execution_id: UUID) -> None:
        tool = await self._load_tool(execution_id)
        if (
            tool is None
            or tool.local_state != LocalIntentState.TERMINAL
            or tool.java_status != "SUCCEEDED"
        ):
            raise H12CausalFenceRejected(
                "second model call requires a terminal successful tool slot"
            )

    async def _mark_dispatching(
        self,
        table: str,
        execution_id: UUID,
        call_index: int | None,
    ) -> None:
        database = self._require_database()
        suffix = " AND call_index = ?" if call_index is not None else ""
        parameters: tuple[Any, ...] = (
            (_now_iso(), str(execution_id), call_index)
            if call_index is not None
            else (_now_iso(), str(execution_id))
        )
        changed = await database.execute(
            f"""
            UPDATE {table}
               SET local_state = 'DISPATCHING', updated_at = ?
             WHERE execution_id = ?{suffix} AND local_state = 'PREPARED'
            """,
            parameters,
        )
        if changed.rowcount != 1:
            raise H12CausalFenceRejected("intent is not in PREPARED state")
        await database.commit()

    async def _complete(
        self,
        table: str,
        execution_id: UUID,
        call_index: int | None,
        java_status: str,
        response_payload: dict[str, Any],
        outcome_kind: str | None,
        model_tool_selection_id: str | None,
    ) -> None:
        _assert_no_forbidden_keys(response_payload)
        payload = json.dumps(
            response_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        database = self._require_database()
        if table == "h12_model_call":
            changed = await database.execute(
                """
                UPDATE h12_model_call
                   SET local_state = 'TERMINAL', java_status = ?, outcome_kind = ?,
                       model_tool_selection_id = ?, response_payload = ?, updated_at = ?
                 WHERE execution_id = ? AND call_index = ?
                   AND local_state = 'DISPATCHING'
                """,
                (
                    java_status,
                    outcome_kind,
                    model_tool_selection_id,
                    payload,
                    _now_iso(),
                    str(execution_id),
                    call_index,
                ),
            )
        else:
            changed = await database.execute(
                """
                UPDATE h12_tool_call
                   SET local_state = 'TERMINAL', java_status = ?,
                       response_payload = ?, updated_at = ?
                 WHERE execution_id = ? AND local_state = 'DISPATCHING'
                """,
                (java_status, payload, _now_iso(), str(execution_id)),
            )
        if changed.rowcount != 1:
            await database.rollback()
            current = (
                await self._load_model(execution_id, call_index or 0)
                if table == "h12_model_call"
                else await self._load_tool(execution_id)
            )
            if (
                current is not None
                and current.local_state == LocalIntentState.TERMINAL
                and current.java_status == java_status
                and (
                    current.outcome_kind.value
                    if current.outcome_kind is not None
                    else None
                )
                == outcome_kind
                and (
                    str(current.model_tool_selection_id)
                    if current.model_tool_selection_id is not None
                    else None
                )
                == model_tool_selection_id
                and current.response_payload == response_payload
            ):
                return
            raise H12IntentConflict("terminal result conflicts with durable evidence")
        await database.commit()

    async def _load_model(
        self,
        execution_id: UUID,
        call_index: int,
    ) -> DurableIntent | None:
        row = await self._load_model_row(execution_id, call_index)
        return _intent(row, call_index) if row is not None else None

    async def _load_model_row(
        self,
        execution_id: UUID,
        call_index: int,
    ) -> aiosqlite.Row | None:
        cursor = await self._require_database().execute(
            "SELECT * FROM h12_model_call WHERE execution_id = ? AND call_index = ?",
            (str(execution_id), call_index),
        )
        return await cursor.fetchone()

    async def _load_tool(self, execution_id: UUID) -> DurableIntent | None:
        cursor = await self._require_database().execute(
            "SELECT * FROM h12_tool_call WHERE execution_id = ?",
            (str(execution_id),),
        )
        row = await cursor.fetchone()
        return _intent(row, 1) if row is not None else None

    def _require_database(self) -> aiosqlite.Connection:
        if self._database is None:
            raise RuntimeError("H1 2.2 durable slots are not open")
        return self._database


def _intent(row: aiosqlite.Row, call_index: int) -> DurableIntent:
    response = (
        json.loads(str(row["response_payload"]))
        if row["response_payload"] is not None
        else None
    )
    identity_column = (
        "model_call_id" if "model_call_id" in row.keys() else "tool_invocation_id"
    )
    return DurableIntent(
        execution_id=UUID(str(row["execution_id"])),
        call_index=call_index,
        intent_id=UUID(str(row[identity_column])),
        request_hash=str(row["request_hash"]),
        canonical_request=str(row["canonical_request"]),
        local_state=LocalIntentState(str(row["local_state"])),
        java_status=str(row["java_status"]) if row["java_status"] else None,
        outcome_kind=(
            ModelOutcome(str(row["outcome_kind"]))
            if "outcome_kind" in row.keys() and row["outcome_kind"] is not None
            else None
        ),
        model_tool_selection_id=(
            UUID(str(row["model_tool_selection_id"]))
            if "model_tool_selection_id" in row.keys()
            and row["model_tool_selection_id"] is not None
            else None
        ),
        response_payload=response,
    )


def _assert_no_forbidden_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("_", "").replace("-", "")
            if normalized in _FORBIDDEN_KEYS:
                raise ValueError("H1 2.2 durable payload contains a forbidden key")
            _assert_no_forbidden_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_forbidden_keys(nested)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()

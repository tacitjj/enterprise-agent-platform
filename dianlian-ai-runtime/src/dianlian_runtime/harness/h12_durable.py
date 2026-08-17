from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

import aiosqlite

if TYPE_CHECKING:
    from dianlian_runtime.harness.governed_model_gateway import (
        GovernedInitialModelCallResponse,
    )
    from dianlian_runtime.harness.governed_model_intent import (
        GovernedInitialModelIntent,
    )
    from dianlian_runtime.harness.governed_model_receipt import (
        GovernedAfterToolModelRequestReceipt,
        GovernedInitialModelRequestReceipt,
    )
    from dianlian_runtime.harness.governed_tool_receipt import (
        GovernedToolRequestReceipt,
    )
    from dianlian_runtime.harness.governed_tool_gateway import (
        GovernedToolCallResponse,
    )
    from dianlian_runtime.supervisor.driver import DriverFence


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


@dataclass(frozen=True, slots=True)
class GovernedInitialTerminalEvidence:
    execution_id: UUID
    model_call_id: UUID
    request_hash: str
    completion_kind: str
    persisted_permit_id: UUID
    attempted_permit_id: UUID
    outcome_status: str | None
    source_fact_id: UUID | None
    source_fact_version: int | None
    source_fact_hash: str | None
    outcome_code: str | None
    java_status: str
    outcome_kind: ModelOutcome | None
    model_tool_selection_id: UUID | None
    response_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GovernedAfterToolTerminalEvidence:
    execution_id: UUID
    model_call_id: UUID
    request_hash: str
    completion_kind: str
    persisted_permit_id: UUID
    attempted_permit_id: UUID
    outcome_status: str | None
    source_fact_id: UUID | None
    source_fact_version: int | None
    source_fact_hash: str | None
    outcome_code: str | None
    java_status: str
    response_payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GovernedToolTerminalEvidence:
    execution_id: UUID
    tool_invocation_id: UUID
    request_hash: str
    persisted_permit_id: UUID
    attempted_permit_id: UUID
    outcome_status: str
    source_fact_id: UUID
    source_fact_version: int
    source_fact_hash: str
    outcome_code: str
    java_status: str
    response_payload: dict[str, Any]


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


def stable_model_tool_selection_id(model_call_id: UUID) -> UUID:
    _require_non_nil_uuid("model_call_id", model_call_id)
    return uuid5(NAMESPACE_URL, f"dianlian:model-tool-selection:{model_call_id}")


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
        self._write_lock = asyncio.Lock()

    async def __aenter__(self) -> "H12DurableSlots":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._database = await aiosqlite.connect(self._path)
        self._database.row_factory = aiosqlite.Row
        async with self._write_lock:
            try:
                await self._database.executescript(
                    """
                    PRAGMA journal_mode=WAL;
                    PRAGMA synchronous=FULL;
                    BEGIN IMMEDIATE;
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
            CREATE TABLE IF NOT EXISTS h12_governed_model_request_receipt (
                runtime_external_permit_id TEXT PRIMARY KEY,
                arm_event_id TEXT NOT NULL UNIQUE,
                execution_id TEXT NOT NULL,
                call_index INTEGER NOT NULL,
                model_call_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                lease_epoch INTEGER NOT NULL,
                body_sha256 TEXT NOT NULL,
                exact_body BLOB NOT NULL,
                CHECK (call_index = 1),
                CHECK (lease_epoch >= 1),
                UNIQUE (execution_id, call_index, lease_epoch)
            );
            CREATE INDEX IF NOT EXISTS
                h12_governed_model_request_receipt_slot_idx
                ON h12_governed_model_request_receipt (
                    execution_id, call_index, lease_epoch
                );
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_model_request_receipt_no_update
                BEFORE UPDATE ON h12_governed_model_request_receipt
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed model request receipts are append-only'
                    );
                END;
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_model_request_receipt_no_delete
                BEFORE DELETE ON h12_governed_model_request_receipt
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed model request receipts are append-only'
                    );
                END;
            CREATE TABLE IF NOT EXISTS h12_governed_model_dispatch_binding (
                runtime_external_permit_id TEXT PRIMARY KEY,
                arm_event_id TEXT NOT NULL UNIQUE,
                execution_id TEXT NOT NULL,
                call_index INTEGER NOT NULL,
                model_call_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                lease_epoch INTEGER NOT NULL,
                body_sha256 TEXT NOT NULL,
                bound_at TEXT NOT NULL,
                CHECK (call_index = 1),
                CHECK (lease_epoch >= 1),
                UNIQUE (execution_id, call_index, lease_epoch)
            );
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_model_dispatch_binding_no_update
                BEFORE UPDATE ON h12_governed_model_dispatch_binding
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed model dispatch bindings are append-only'
                    );
                END;
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_model_dispatch_binding_no_delete
                BEFORE DELETE ON h12_governed_model_dispatch_binding
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed model dispatch bindings are append-only'
                    );
                END;
            CREATE TABLE IF NOT EXISTS
                h12_governed_after_tool_model_request_receipt (
                runtime_external_permit_id TEXT PRIMARY KEY,
                arm_event_id TEXT NOT NULL UNIQUE,
                execution_id TEXT NOT NULL,
                call_index INTEGER NOT NULL,
                model_call_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                lease_epoch INTEGER NOT NULL,
                body_sha256 TEXT NOT NULL,
                exact_body BLOB NOT NULL,
                CHECK (call_index = 2),
                CHECK (lease_epoch >= 1),
                UNIQUE (execution_id, call_index, lease_epoch)
            );
            CREATE INDEX IF NOT EXISTS
                h12_governed_after_tool_model_receipt_slot_idx
                ON h12_governed_after_tool_model_request_receipt (
                    execution_id, call_index, lease_epoch
                );
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_after_tool_model_receipt_no_update
                BEFORE UPDATE ON h12_governed_after_tool_model_request_receipt
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed AFTER_TOOL model receipts are append-only'
                    );
                END;
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_after_tool_model_receipt_no_delete
                BEFORE DELETE ON h12_governed_after_tool_model_request_receipt
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed AFTER_TOOL model receipts are append-only'
                    );
                END;
            CREATE TABLE IF NOT EXISTS
                h12_governed_after_tool_model_dispatch_binding (
                runtime_external_permit_id TEXT PRIMARY KEY,
                arm_event_id TEXT NOT NULL UNIQUE,
                execution_id TEXT NOT NULL,
                call_index INTEGER NOT NULL,
                model_call_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                lease_epoch INTEGER NOT NULL,
                body_sha256 TEXT NOT NULL,
                bound_at TEXT NOT NULL,
                CHECK (call_index = 2),
                CHECK (lease_epoch >= 1),
                UNIQUE (execution_id, call_index, lease_epoch)
            );
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_after_tool_model_binding_no_update
                BEFORE UPDATE ON h12_governed_after_tool_model_dispatch_binding
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed AFTER_TOOL model bindings are append-only'
                    );
                END;
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_after_tool_model_binding_no_delete
                BEFORE DELETE ON h12_governed_after_tool_model_dispatch_binding
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed AFTER_TOOL model bindings are append-only'
                    );
                END;
            CREATE TABLE IF NOT EXISTS
                h12_governed_after_tool_model_terminal_evidence (
                execution_id TEXT NOT NULL,
                call_index INTEGER NOT NULL,
                model_call_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                persisted_permit_id TEXT NOT NULL,
                persisted_arm_event_id TEXT NOT NULL,
                persisted_lease_epoch INTEGER NOT NULL,
                attempted_permit_id TEXT NOT NULL,
                attempted_arm_event_id TEXT NOT NULL,
                attempted_lease_epoch INTEGER NOT NULL,
                completion_kind TEXT NOT NULL,
                outcome_event_id TEXT,
                outcome_status TEXT,
                source_fact_id TEXT,
                source_fact_version INTEGER,
                source_fact_hash TEXT,
                outcome_code TEXT,
                result_hash TEXT,
                response_payload_hash TEXT NOT NULL,
                accepted_by_lease_owner TEXT NOT NULL,
                accepted_by_lease_epoch INTEGER NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (execution_id, call_index),
                CHECK (call_index = 2),
                CHECK (persisted_lease_epoch >= 1),
                CHECK (attempted_lease_epoch >= 1),
                CHECK (accepted_by_lease_epoch >= 1),
                CHECK (completion_kind IN (
                    'FAILED_SAFE_BEFORE_ARM', 'CANONICAL_APPLIED'
                )),
                CHECK (
                    (completion_kind = 'FAILED_SAFE_BEFORE_ARM'
                        AND outcome_event_id IS NULL
                        AND outcome_status IS NULL
                        AND source_fact_id IS NULL
                        AND source_fact_version IS NULL
                        AND source_fact_hash IS NULL
                        AND outcome_code IS NULL
                        AND result_hash IS NULL)
                    OR
                    (completion_kind = 'CANONICAL_APPLIED'
                        AND outcome_event_id IS NOT NULL
                        AND outcome_status IN (
                            'NOT_DISPATCHED', 'SUCCEEDED', 'FAILED_CONFIRMED'
                        )
                        AND source_fact_id IS NOT NULL
                        AND source_fact_version >= 1
                        AND source_fact_hash IS NOT NULL
                        AND outcome_code IS NOT NULL
                        AND (
                            (outcome_status = 'NOT_DISPATCHED'
                                AND result_hash IS NULL)
                            OR
                            (outcome_status IN ('SUCCEEDED', 'FAILED_CONFIRMED')
                                AND result_hash IS NOT NULL)
                        ))
                )
            );
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_after_tool_model_terminal_no_update
                BEFORE UPDATE
                ON h12_governed_after_tool_model_terminal_evidence
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed AFTER_TOOL terminal evidence is append-only'
                    );
                END;
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_after_tool_model_terminal_no_delete
                BEFORE DELETE
                ON h12_governed_after_tool_model_terminal_evidence
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed AFTER_TOOL terminal evidence is append-only'
                    );
                END;
            CREATE TABLE IF NOT EXISTS h12_governed_tool_request_receipt (
                runtime_external_permit_id TEXT PRIMARY KEY,
                arm_event_id TEXT NOT NULL UNIQUE,
                execution_id TEXT NOT NULL,
                tool_call_slot INTEGER NOT NULL,
                tool_invocation_id TEXT NOT NULL,
                source_model_call_id TEXT NOT NULL,
                model_tool_selection_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                lease_epoch INTEGER NOT NULL,
                body_sha256 TEXT NOT NULL,
                exact_body BLOB NOT NULL,
                CHECK (tool_call_slot = 1),
                CHECK (lease_epoch >= 1),
                UNIQUE (execution_id, tool_call_slot, lease_epoch)
            );
            CREATE INDEX IF NOT EXISTS
                h12_governed_tool_request_receipt_slot_idx
                ON h12_governed_tool_request_receipt (
                    execution_id, tool_call_slot, lease_epoch
                );
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_tool_request_receipt_no_update
                BEFORE UPDATE ON h12_governed_tool_request_receipt
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed tool request receipts are append-only'
                    );
                END;
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_tool_request_receipt_no_delete
                BEFORE DELETE ON h12_governed_tool_request_receipt
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed tool request receipts are append-only'
                    );
                END;
            CREATE TABLE IF NOT EXISTS h12_governed_tool_dispatch_binding (
                runtime_external_permit_id TEXT PRIMARY KEY,
                arm_event_id TEXT NOT NULL UNIQUE,
                execution_id TEXT NOT NULL,
                tool_call_slot INTEGER NOT NULL,
                tool_invocation_id TEXT NOT NULL,
                source_model_call_id TEXT NOT NULL,
                model_tool_selection_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                lease_epoch INTEGER NOT NULL,
                body_sha256 TEXT NOT NULL,
                bound_at TEXT NOT NULL,
                CHECK (tool_call_slot = 1),
                CHECK (lease_epoch >= 1),
                UNIQUE (execution_id, tool_call_slot, lease_epoch)
            );
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_tool_dispatch_binding_no_update
                BEFORE UPDATE ON h12_governed_tool_dispatch_binding
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed tool dispatch bindings are append-only'
                    );
                END;
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_tool_dispatch_binding_no_delete
                BEFORE DELETE ON h12_governed_tool_dispatch_binding
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed tool dispatch bindings are append-only'
                    );
                END;
            CREATE TABLE IF NOT EXISTS h12_governed_model_terminal_evidence (
                execution_id TEXT NOT NULL,
                call_index INTEGER NOT NULL,
                model_call_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                persisted_permit_id TEXT NOT NULL,
                persisted_arm_event_id TEXT NOT NULL,
                persisted_lease_epoch INTEGER NOT NULL,
                attempted_permit_id TEXT NOT NULL,
                attempted_arm_event_id TEXT NOT NULL,
                attempted_lease_epoch INTEGER NOT NULL,
                completion_kind TEXT NOT NULL,
                outcome_event_id TEXT,
                outcome_status TEXT,
                source_fact_id TEXT,
                source_fact_version INTEGER,
                source_fact_hash TEXT,
                outcome_code TEXT,
                result_hash TEXT,
                response_payload_hash TEXT NOT NULL,
                accepted_by_lease_owner TEXT NOT NULL,
                accepted_by_lease_epoch INTEGER NOT NULL,
                completed_at TEXT NOT NULL,
                PRIMARY KEY (execution_id, call_index),
                CHECK (call_index = 1),
                CHECK (persisted_lease_epoch >= 1),
                CHECK (attempted_lease_epoch >= 1),
                CHECK (accepted_by_lease_epoch >= 1),
                CHECK (completion_kind IN ('FAILED_SAFE_BEFORE_ARM', 'CANONICAL_APPLIED')),
                CHECK (
                    (completion_kind = 'FAILED_SAFE_BEFORE_ARM'
                        AND outcome_event_id IS NULL
                        AND outcome_status IS NULL
                        AND source_fact_id IS NULL
                        AND source_fact_version IS NULL
                        AND source_fact_hash IS NULL
                        AND outcome_code IS NULL
                        AND result_hash IS NULL)
                    OR
                    (completion_kind = 'CANONICAL_APPLIED'
                        AND outcome_event_id IS NOT NULL
                        AND outcome_status IN (
                            'NOT_DISPATCHED', 'SUCCEEDED', 'FAILED_CONFIRMED'
                        )
                        AND source_fact_id IS NOT NULL
                        AND source_fact_version >= 1
                        AND source_fact_hash IS NOT NULL
                        AND outcome_code IS NOT NULL
                        AND (
                            (outcome_status = 'NOT_DISPATCHED' AND result_hash IS NULL)
                            OR
                            (outcome_status IN ('SUCCEEDED', 'FAILED_CONFIRMED')
                                AND result_hash IS NOT NULL)
                        ))
                )
            );
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_model_terminal_evidence_no_update
                BEFORE UPDATE ON h12_governed_model_terminal_evidence
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed model terminal evidence is append-only'
                    );
                END;
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_model_terminal_evidence_no_delete
                BEFORE DELETE ON h12_governed_model_terminal_evidence
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed model terminal evidence is append-only'
                    );
                END;
            CREATE TABLE IF NOT EXISTS h12_governed_tool_terminal_evidence (
                execution_id TEXT PRIMARY KEY,
                tool_call_slot INTEGER NOT NULL,
                tool_invocation_id TEXT NOT NULL,
                source_model_call_id TEXT NOT NULL,
                model_tool_selection_id TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                persisted_permit_id TEXT NOT NULL,
                persisted_arm_event_id TEXT NOT NULL,
                persisted_lease_epoch INTEGER NOT NULL,
                attempted_permit_id TEXT NOT NULL,
                attempted_arm_event_id TEXT NOT NULL,
                attempted_lease_epoch INTEGER NOT NULL,
                outcome_event_id TEXT NOT NULL,
                outcome_status TEXT NOT NULL,
                source_fact_id TEXT NOT NULL,
                source_fact_version INTEGER NOT NULL,
                source_fact_hash TEXT NOT NULL,
                outcome_code TEXT NOT NULL,
                result_hash TEXT,
                response_payload_hash TEXT NOT NULL,
                accepted_by_lease_owner TEXT NOT NULL,
                accepted_by_lease_epoch INTEGER NOT NULL,
                completed_at TEXT NOT NULL,
                CHECK (tool_call_slot = 1),
                CHECK (persisted_lease_epoch >= 1),
                CHECK (attempted_lease_epoch >= 1),
                CHECK (accepted_by_lease_epoch >= 1),
                CHECK (source_fact_version >= 1),
                CHECK (outcome_status IN (
                    'NOT_DISPATCHED', 'SUCCEEDED', 'FAILED_CONFIRMED'
                )),
                CHECK (
                    (outcome_status = 'NOT_DISPATCHED' AND result_hash IS NULL)
                    OR
                    (outcome_status IN ('SUCCEEDED', 'FAILED_CONFIRMED')
                        AND result_hash IS NOT NULL)
                )
            );
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_tool_terminal_evidence_no_update
                BEFORE UPDATE ON h12_governed_tool_terminal_evidence
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed Tool terminal evidence is append-only'
                    );
                END;
            CREATE TRIGGER IF NOT EXISTS
                h12_governed_tool_terminal_evidence_no_delete
                BEFORE DELETE ON h12_governed_tool_terminal_evidence
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'governed Tool terminal evidence is append-only'
                    );
                END;
                    COMMIT;
            """
                )
            except BaseException:
                database = self._database
                assert database is not None
                try:
                    await self._rollback_before_unlock(database)
                finally:
                    try:
                        await database.close()
                    finally:
                        self._database = None
                raise
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
        canonical, request_hash = canonical_intent(request_without_hash)
        intent_id = stable_model_call_id(execution_id, call_index)
        now = _now_iso()
        async with self._write_transaction() as database:
            if call_index == 2:
                await self._require_successful_tool_unlocked(database, execution_id)
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
            intent = await self._load_model_unlocked(
                database,
                execution_id,
                call_index,
            )
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
        canonical, request_hash = canonical_intent(request_without_hash)
        intent_id = stable_tool_call_id(execution_id)
        now = _now_iso()
        async with self._write_transaction() as database:
            call_one = await self._load_model_row_unlocked(database, execution_id, 1)
            if (
                call_one is None
                or call_one["local_state"] != LocalIntentState.TERMINAL.value
                or call_one["java_status"] not in _MODEL_CONTINUABLE
                or call_one["outcome_kind"] != ModelOutcome.TOOL_SELECTION.value
                or call_one["model_call_id"] != str(source_model_call_id)
                or call_one["model_tool_selection_id"]
                != str(model_tool_selection_id)
            ):
                raise H12CausalFenceRejected(
                    "tool slot requires the exact terminal model selection evidence"
                )
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
            intent = await self._load_tool_unlocked(database, execution_id)
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
        async with self._read_snapshot() as database:
            return await self._next_action_unlocked(database, execution_id)

    async def _next_action_unlocked(
        self,
        database: aiosqlite.Connection,
        execution_id: UUID,
    ) -> RecoveryDecision:
        call_one = await self._load_model_unlocked(database, execution_id, 1)
        if call_one is None:
            return RecoveryDecision(RecoveryAction.DISPATCH_MODEL_1, None)
        if call_one.local_state == LocalIntentState.PREPARED:
            return RecoveryDecision(RecoveryAction.DISPATCH_MODEL_1, call_one)
        if call_one.local_state == LocalIntentState.DISPATCHING:
            return RecoveryDecision(RecoveryAction.REPLAY_MODEL_1, call_one)
        row_one = await self._load_model_row_unlocked(database, execution_id, 1)
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

        tool = await self._load_tool_unlocked(database, execution_id)
        if tool is None:
            return RecoveryDecision(RecoveryAction.DISPATCH_TOOL_1, None)
        governed_tool = await database.execute(
            """
            SELECT 1
              FROM h12_governed_tool_request_receipt
             WHERE execution_id = ? AND tool_call_slot = 1
             LIMIT 1
            """,
            (str(execution_id),),
        )
        if await governed_tool.fetchone() is not None:
            raise H12CausalFenceRejected(
                "governed Tool intent requires the governed runtime Driver"
            )
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

        call_two = await self._load_model_unlocked(database, execution_id, 2)
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
        async with self._read_snapshot() as database:
            intent = await self._load_model_unlocked(
                database,
                execution_id,
                call_index,
            )
            if intent is None:
                raise H12CausalFenceRejected("required model intent is missing")
            return intent

    async def load_governed_initial_model_intent(
        self,
        execution_id: UUID,
    ) -> GovernedInitialModelIntent | None:
        """Load the committed v1.2 logical intent without selecting a Permit."""

        from dianlian_runtime.harness.governed_model_intent import (
            GovernedInitialModelIntent,
        )

        _require_non_nil_uuid("execution_id", execution_id)
        async with self._read_snapshot() as database:
            intent = await self._load_model_unlocked(database, execution_id, 1)
        if intent is None:
            return None
        try:
            governed = GovernedInitialModelIntent.model_validate_json(
                intent.canonical_request,
                strict=True,
            )
        except (TypeError, ValueError) as exception:
            raise H12IntentConflict(
                "initial model slot does not contain a governed logical intent"
            ) from exception
        _, expected_hash = canonical_intent(governed.durable_payload())
        if (
            governed.model_call_id != intent.intent_id
            or governed.execution_generation < 1
            or expected_hash != intent.request_hash
        ):
            raise H12IntentConflict(
                "governed logical intent differs from durable slot identity"
            )
        return governed

    async def load_governed_initial_terminal_evidence(
        self,
        execution_id: UUID,
    ) -> GovernedInitialTerminalEvidence | None:
        """Load one committed terminal fact; it does not authorize Run completion."""

        _require_non_nil_uuid("execution_id", execution_id)
        async with self._read_snapshot() as database:
            cursor = await database.execute(
                """
                SELECT evidence.*, model.java_status, model.outcome_kind,
                       model.model_tool_selection_id, model.response_payload
                  FROM h12_governed_model_terminal_evidence AS evidence
                  JOIN h12_model_call AS model
                    ON model.execution_id = evidence.execution_id
                   AND model.call_index = evidence.call_index
                   AND model.model_call_id = evidence.model_call_id
                   AND model.request_hash = evidence.request_hash
                 WHERE evidence.execution_id = ? AND evidence.call_index = 1
                   AND model.local_state = 'TERMINAL'
                """,
                (str(execution_id),),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["response_payload"]))
        if not isinstance(payload, dict):
            raise H12IntentConflict(
                "governed terminal payload is not a JSON object"
            )
        evidence = GovernedInitialTerminalEvidence(
            execution_id=UUID(str(row["execution_id"])),
            model_call_id=UUID(str(row["model_call_id"])),
            request_hash=str(row["request_hash"]),
            completion_kind=str(row["completion_kind"]),
            persisted_permit_id=UUID(str(row["persisted_permit_id"])),
            attempted_permit_id=UUID(str(row["attempted_permit_id"])),
            outcome_status=(
                str(row["outcome_status"])
                if row["outcome_status"] is not None
                else None
            ),
            source_fact_id=(
                UUID(str(row["source_fact_id"]))
                if row["source_fact_id"] is not None
                else None
            ),
            source_fact_version=(
                int(row["source_fact_version"])
                if row["source_fact_version"] is not None
                else None
            ),
            source_fact_hash=(
                str(row["source_fact_hash"])
                if row["source_fact_hash"] is not None
                else None
            ),
            outcome_code=(
                str(row["outcome_code"])
                if row["outcome_code"] is not None
                else None
            ),
            java_status=str(row["java_status"]),
            outcome_kind=(
                ModelOutcome(str(row["outcome_kind"]))
                if row["outcome_kind"] is not None
                else None
            ),
            model_tool_selection_id=(
                UUID(str(row["model_tool_selection_id"]))
                if row["model_tool_selection_id"] is not None
                else None
            ),
            response_payload=payload,
        )
        _validate_governed_terminal_evidence(evidence)
        return evidence

    async def begin_governed_initial_model_dispatch(
        self,
        receipt: GovernedInitialModelRequestReceipt,
        fence: DriverFence,
    ) -> None:
        """Bind one exact receipt before its sole governed Java POST.

        The caller must still perform a live Supervisor authorization immediately
        before this local transition. ``DriverFence`` is persisted identity evidence,
        not a substitute for that live gate.
        """

        from dianlian_runtime.harness.governed_model_receipt import (
            GovernedInitialModelRequestReceipt,
        )
        from dianlian_runtime.supervisor.driver import DriverFence

        if not isinstance(receipt, GovernedInitialModelRequestReceipt):
            raise TypeError("receipt must be a GovernedInitialModelRequestReceipt")
        if not isinstance(fence, DriverFence):
            raise TypeError("fence must be a DriverFence")
        if not _fence_matches_receipt(fence, receipt):
            raise H12CausalFenceRejected(
                "current Driver fence does not match the governed request receipt"
            )

        request = receipt.request
        now = _now_iso()
        async with self._write_transaction() as database:
            stored = await self._load_governed_initial_model_receipt_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            if stored != receipt:
                raise H12CausalFenceRejected(
                    "governed dispatch requires the exact persisted receipt"
                )
            logical = await self._load_model_row_unlocked(
                database,
                receipt.execution_id,
                1,
            )
            if logical is None or (
                logical["model_call_id"] != str(request.model_call_id)
                or logical["request_hash"] != request.request_hash
            ):
                raise H12IntentConflict(
                    "governed dispatch differs from the durable logical intent"
                )
            if logical["local_state"] == LocalIntentState.TERMINAL.value:
                raise H12CausalFenceRejected(
                    "terminal model slot cannot bind another governed dispatch"
                )

            existing = await self._load_governed_dispatch_binding_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            if existing is not None:
                if not _binding_matches_receipt(existing, receipt):
                    raise H12IntentConflict(
                        "runtime permit id is bound to another governed dispatch"
                    )
                if logical["local_state"] != LocalIntentState.DISPATCHING.value:
                    raise H12IntentConflict(
                        "governed dispatch binding and local state differ"
                    )
                return

            inserted = await database.execute(
                """
                INSERT INTO h12_governed_model_dispatch_binding (
                    runtime_external_permit_id, arm_event_id, execution_id,
                    call_index, model_call_id, request_hash, lease_epoch,
                    body_sha256, bound_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    str(receipt.runtime_external_permit_id),
                    str(receipt.arm_event_id),
                    str(receipt.execution_id),
                    str(request.model_call_id),
                    request.request_hash,
                    receipt.lease_epoch,
                    receipt.body_sha256,
                    now,
                ),
            )
            if inserted.rowcount != 1:
                raise H12IntentConflict("governed dispatch evidence was not appended")
            if logical["local_state"] == LocalIntentState.PREPARED.value:
                changed = await database.execute(
                    """
                    UPDATE h12_model_call
                       SET local_state = 'DISPATCHING', updated_at = ?
                     WHERE execution_id = ? AND call_index = 1
                       AND model_call_id = ? AND request_hash = ?
                       AND local_state = 'PREPARED'
                    """,
                    (
                        now,
                        str(receipt.execution_id),
                        str(request.model_call_id),
                        request.request_hash,
                    ),
                )
                if changed.rowcount != 1:
                    raise H12CausalFenceRejected(
                        "logical model slot is no longer PREPARED"
                    )
            elif logical["local_state"] != LocalIntentState.DISPATCHING.value:
                raise H12CausalFenceRejected(
                    "logical model slot cannot bind a governed dispatch"
                )

    async def complete_governed_initial_model(
        self,
        execution_id: UUID,
        fence: DriverFence,
        response: GovernedInitialModelCallResponse,
    ) -> None:
        """Accept only a determinate, applied v1.2 terminal under the current fence."""

        from dianlian_runtime.harness.governed_model_gateway import (
            GovernedInitialModelCallResponse,
        )
        from dianlian_runtime.supervisor.driver import DriverFence

        _require_non_nil_uuid("execution_id", execution_id)
        if not isinstance(fence, DriverFence):
            raise TypeError("fence must be a DriverFence")
        if not isinstance(response, GovernedInitialModelCallResponse):
            raise TypeError("response must be a GovernedInitialModelCallResponse")
        if response.model_call_id != stable_model_call_id(execution_id, 1):
            raise H12IntentConflict("governed response modelCallId differs from the slot")

        completion = _governed_terminal_completion(response)
        attempted_permit = response.attempted_dispatch.runtime_external_permit_id
        persisted_permit = response.persisted_dispatch.runtime_external_permit_id
        now = _now_iso()

        async with self._write_transaction() as database:
            attempted = await self._load_governed_initial_model_receipt_unlocked(
                database,
                attempted_permit,
            )
            persisted = await self._load_governed_initial_model_receipt_unlocked(
                database,
                persisted_permit,
            )
            if (
                attempted is None
                or persisted is None
                or not _response_identity_matches_receipt(
                    response.attempted_dispatch,
                    attempted,
                )
                or not _response_identity_matches_receipt(
                    response.persisted_dispatch,
                    persisted,
                )
                or response.request_hash != attempted.request.request_hash
                or response.request_hash != persisted.request.request_hash
                or response.model_call_id != attempted.request.model_call_id
                or response.model_call_id != persisted.request.model_call_id
            ):
                raise H12IntentConflict(
                    "governed terminal response is not bound to receipt history"
                )
            if not _current_fence_can_settle_receipt(fence, attempted):
                raise H12CausalFenceRejected(
                    "current Driver fence cannot settle the attempted receipt"
                )
            attempted_binding = await self._load_governed_dispatch_binding_unlocked(
                database,
                attempted.runtime_external_permit_id,
            )
            persisted_binding = await self._load_governed_dispatch_binding_unlocked(
                database,
                persisted.runtime_external_permit_id,
            )
            if (
                attempted_binding is None
                or persisted_binding is None
                or not _binding_matches_receipt(attempted_binding, attempted)
                or not _binding_matches_receipt(persisted_binding, persisted)
            ):
                raise H12CausalFenceRejected(
                    "governed terminal response lacks exact dispatch history"
                )

            payload = json.dumps(
                completion["response_payload"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            evidence_values = _governed_terminal_evidence_values(
                execution_id,
                fence,
                response,
                completion["completion_kind"],
                payload_hash,
                now,
            )
            existing = await database.execute(
                """
                SELECT *
                  FROM h12_governed_model_terminal_evidence
                 WHERE execution_id = ? AND call_index = 1
                """,
                (str(execution_id),),
            )
            existing_evidence = await existing.fetchone()
            logical = await self._load_model_row_unlocked(database, execution_id, 1)
            if existing_evidence is not None:
                if (
                    not _terminal_evidence_matches(existing_evidence, evidence_values)
                    or logical is None
                    or logical["local_state"] != LocalIntentState.TERMINAL.value
                    or logical["java_status"] != completion["java_status"]
                    or logical["outcome_kind"] != completion["outcome_kind"]
                    or logical["model_tool_selection_id"]
                    != completion["model_tool_selection_id"]
                    or logical["response_payload"] != payload
                ):
                    raise H12IntentConflict(
                        "governed terminal result conflicts with durable evidence"
                    )
                return
            if (
                logical is None
                or logical["local_state"] != LocalIntentState.DISPATCHING.value
                or logical["model_call_id"] != str(response.model_call_id)
                or logical["request_hash"] != response.request_hash
            ):
                raise H12CausalFenceRejected(
                    "governed model slot is not eligible for terminal convergence"
                )

            await database.execute(
                """
                INSERT INTO h12_governed_model_terminal_evidence (
                    execution_id, call_index, model_call_id, request_hash,
                    persisted_permit_id, persisted_arm_event_id,
                    persisted_lease_epoch, attempted_permit_id,
                    attempted_arm_event_id, attempted_lease_epoch,
                    completion_kind, outcome_event_id, outcome_status,
                    source_fact_id, source_fact_version, source_fact_hash,
                    outcome_code, result_hash, response_payload_hash,
                    accepted_by_lease_owner, accepted_by_lease_epoch, completed_at
                ) VALUES (
                    ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                evidence_values,
            )
            changed = await database.execute(
                """
                UPDATE h12_model_call
                   SET local_state = 'TERMINAL', java_status = ?, outcome_kind = ?,
                       model_tool_selection_id = ?, response_payload = ?, updated_at = ?
                 WHERE execution_id = ? AND call_index = 1
                   AND model_call_id = ? AND request_hash = ?
                   AND local_state = 'DISPATCHING'
                """,
                (
                    completion["java_status"],
                    completion["outcome_kind"],
                    completion["model_tool_selection_id"],
                    payload,
                    now,
                    str(execution_id),
                    str(response.model_call_id),
                    response.request_hash,
                ),
            )
            if changed.rowcount != 1:
                raise H12CausalFenceRejected(
                    "governed model slot changed during terminal convergence"
                )

    async def require_governed_initial_model_dispatch_binding(
        self,
        receipt: GovernedInitialModelRequestReceipt,
    ) -> None:
        """Require one exact historical binding without granting another POST."""

        from dianlian_runtime.harness.governed_model_receipt import (
            GovernedInitialModelRequestReceipt,
        )

        if not isinstance(receipt, GovernedInitialModelRequestReceipt):
            raise TypeError("receipt must be a GovernedInitialModelRequestReceipt")
        async with self._read_snapshot() as database:
            stored = await self._load_governed_initial_model_receipt_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            binding = await self._load_governed_dispatch_binding_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
        if (
            stored != receipt
            or binding is None
            or not _binding_matches_receipt(binding, receipt)
        ):
            raise H12CausalFenceRejected(
                "governed receipt has no exact historical dispatch binding"
            )

    async def persist_governed_initial_model_receipt(
        self,
        receipt: GovernedInitialModelRequestReceipt,
    ) -> GovernedInitialModelRequestReceipt:
        """Append exact v1.2 request evidence without granting dispatch authority.

        A takeover may append another Permit receipt only while the logical slot is
        PREPARED or DISPATCHING. The local state is merely a persistence fence; Java
        lifecycle plus Supervisor authority must still select the usable receipt.
        """

        from dianlian_runtime.harness.governed_model_receipt import (
            GovernedInitialModelRequestReceipt,
        )

        if not isinstance(receipt, GovernedInitialModelRequestReceipt):
            raise TypeError(
                "receipt must be a GovernedInitialModelRequestReceipt"
            )
        request = receipt.request
        logical_canonical, logical_hash = canonical_intent(
            request.logical_payload()
        )
        async with self._write_transaction() as database:
            row = await self._load_model_row_unlocked(
                database,
                receipt.execution_id,
                1,
            )
            if row is None:
                raise H12CausalFenceRejected(
                    "governed receipt requires an existing logical model slot"
                )
            if (
                row["model_call_id"] != str(request.model_call_id)
                or row["request_hash"] != request.request_hash
                or row["request_hash"] != logical_hash
                or row["canonical_request"] != logical_canonical
            ):
                raise H12IntentConflict(
                    "governed receipt differs from the durable logical intent"
                )

            existing = await self._load_governed_initial_model_receipt_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            if existing is not None:
                if existing != receipt:
                    raise H12IntentConflict(
                        "runtime permit id is bound to another exact request receipt"
                    )
                return existing

            history_summary = await database.execute(
                """
                SELECT COUNT(*), MAX(lease_epoch)
                  FROM h12_governed_model_request_receipt
                 WHERE execution_id = ? AND call_index = 1
                """,
                (str(receipt.execution_id),),
            )
            summary_row = await history_summary.fetchone()
            prior_receipts = int(summary_row[0]) if summary_row is not None else 0
            latest_lease_epoch = (
                int(summary_row[1])
                if summary_row is not None and summary_row[1] is not None
                else None
            )
            local_state = LocalIntentState(str(row["local_state"]))
            if local_state == LocalIntentState.TERMINAL:
                raise H12CausalFenceRejected(
                    "terminal model slot cannot accept another request receipt"
                )
            if prior_receipts == 0 and local_state != LocalIntentState.PREPARED:
                raise H12CausalFenceRejected(
                    "first governed receipt must be persisted from PREPARED"
                )
            if (
                latest_lease_epoch is not None
                and receipt.lease_epoch <= latest_lease_epoch
            ):
                raise H12IntentConflict(
                    "a new governed receipt must advance the lease epoch"
                )

            inserted = await database.execute(
                """
                INSERT INTO h12_governed_model_request_receipt (
                    runtime_external_permit_id, arm_event_id, execution_id,
                    call_index, model_call_id, request_hash, lease_epoch,
                    body_sha256, exact_body
                )
                SELECT ?, ?, ?, 1, ?, ?, ?, ?, ?
                  FROM h12_model_call AS logical
                 WHERE logical.execution_id = ?
                   AND logical.call_index = 1
                   AND logical.model_call_id = ?
                   AND logical.request_hash = ?
                   AND logical.canonical_request = ?
                   AND (
                        logical.local_state = 'PREPARED'
                        OR (
                            logical.local_state = 'DISPATCHING'
                            AND EXISTS (
                                SELECT 1
                                  FROM h12_governed_model_request_receipt AS prior
                                 WHERE prior.execution_id = logical.execution_id
                                   AND prior.call_index = logical.call_index
                            )
                        )
                   )
                   AND NOT EXISTS (
                        SELECT 1
                          FROM h12_governed_model_request_receipt AS newer
                         WHERE newer.execution_id = logical.execution_id
                           AND newer.call_index = logical.call_index
                           AND newer.lease_epoch >= ?
                   )
                ON CONFLICT DO NOTHING
                """,
                (
                    str(receipt.runtime_external_permit_id),
                    str(receipt.arm_event_id),
                    str(receipt.execution_id),
                    str(request.model_call_id),
                    request.request_hash,
                    receipt.lease_epoch,
                    receipt.body_sha256,
                    receipt.exact_body,
                    str(receipt.execution_id),
                    str(request.model_call_id),
                    request.request_hash,
                    logical_canonical,
                    receipt.lease_epoch,
                ),
            )
            if inserted.rowcount != 1:
                concurrent = await self._load_governed_initial_model_receipt_unlocked(
                    database,
                    receipt.runtime_external_permit_id,
                )
                if concurrent == receipt:
                    return concurrent
                raise H12IntentConflict(
                    "governed receipt collides with existing Permit, Arm or lease evidence"
                )
            stored = await self._load_governed_initial_model_receipt_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            if stored != receipt:
                raise H12IntentConflict(
                    "stored governed request receipt is inconsistent"
                )
            return stored

    async def load_governed_initial_model_receipt(
        self,
        runtime_external_permit_id: UUID,
    ) -> GovernedInitialModelRequestReceipt | None:
        """Read one exact historical receipt; this never authorizes another POST."""

        _require_non_nil_uuid(
            "runtime_external_permit_id",
            runtime_external_permit_id,
        )
        async with self._read_snapshot() as database:
            return await self._load_governed_initial_model_receipt_unlocked(
                database,
                runtime_external_permit_id,
            )

    async def _load_governed_initial_model_receipt_unlocked(
        self,
        database: aiosqlite.Connection,
        runtime_external_permit_id: UUID,
    ) -> GovernedInitialModelRequestReceipt | None:
        cursor = await database.execute(
            """
            SELECT *
              FROM h12_governed_model_request_receipt
             WHERE runtime_external_permit_id = ?
            """,
            (str(runtime_external_permit_id),),
        )
        row = await cursor.fetchone()
        return _governed_receipt(row) if row is not None else None

    async def load_governed_initial_model_receipt_history(
        self,
        execution_id: UUID,
    ) -> tuple[GovernedInitialModelRequestReceipt, ...]:
        """Return every receipt for reconciliation, never an implicitly usable latest."""

        _require_non_nil_uuid("execution_id", execution_id)
        async with self._read_snapshot() as database:
            return await self._load_governed_initial_model_receipt_history_unlocked(
                database,
                execution_id,
            )

    async def _load_governed_initial_model_receipt_history_unlocked(
        self,
        database: aiosqlite.Connection,
        execution_id: UUID,
    ) -> tuple[GovernedInitialModelRequestReceipt, ...]:
        cursor = await database.execute(
            """
            SELECT *
              FROM h12_governed_model_request_receipt
             WHERE execution_id = ? AND call_index = 1
             ORDER BY lease_epoch, runtime_external_permit_id
            """,
            (str(execution_id),),
        )
        rows = await cursor.fetchall()
        return tuple(_governed_receipt(row) for row in rows)

    async def persist_governed_after_tool_model_receipt(
        self,
        receipt: GovernedAfterToolModelRequestReceipt,
    ) -> GovernedAfterToolModelRequestReceipt:
        """Append one exact call-two request without authorizing its POST."""

        from dianlian_runtime.harness.governed_model_receipt import (
            GovernedAfterToolModelRequestReceipt,
        )

        if not isinstance(receipt, GovernedAfterToolModelRequestReceipt):
            raise TypeError(
                "receipt must be a GovernedAfterToolModelRequestReceipt"
            )
        request = receipt.request
        logical_canonical, logical_hash = canonical_intent(
            request.logical_payload()
        )
        async with self._write_transaction() as database:
            row = await self._load_model_row_unlocked(
                database,
                receipt.execution_id,
                2,
            )
            if row is None:
                raise H12CausalFenceRejected(
                    "AFTER_TOOL receipt requires an existing call-two intent"
                )
            if (
                row["model_call_id"] != str(request.model_call_id)
                or row["request_hash"] != request.request_hash
                or row["request_hash"] != logical_hash
                or row["canonical_request"] != logical_canonical
            ):
                raise H12IntentConflict(
                    "AFTER_TOOL receipt differs from the durable call-two intent"
                )

            existing = await self._load_governed_after_tool_model_receipt_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            if existing is not None:
                if existing != receipt:
                    raise H12IntentConflict(
                        "runtime Permit id is bound to another AFTER_TOOL request"
                    )
                return existing

            history_summary = await database.execute(
                """
                SELECT COUNT(*), MAX(lease_epoch)
                  FROM h12_governed_after_tool_model_request_receipt
                 WHERE execution_id = ? AND call_index = 2
                """,
                (str(receipt.execution_id),),
            )
            summary_row = await history_summary.fetchone()
            prior_receipts = int(summary_row[0]) if summary_row is not None else 0
            latest_lease_epoch = (
                int(summary_row[1])
                if summary_row is not None and summary_row[1] is not None
                else None
            )
            local_state = LocalIntentState(str(row["local_state"]))
            if local_state == LocalIntentState.TERMINAL:
                raise H12CausalFenceRejected(
                    "terminal call two cannot accept another receipt"
                )
            if prior_receipts == 0 and local_state != LocalIntentState.PREPARED:
                raise H12CausalFenceRejected(
                    "first AFTER_TOOL receipt must be persisted from PREPARED"
                )
            if (
                latest_lease_epoch is not None
                and receipt.lease_epoch <= latest_lease_epoch
            ):
                raise H12IntentConflict(
                    "a new AFTER_TOOL receipt must advance the lease epoch"
                )

            inserted = await database.execute(
                """
                INSERT INTO h12_governed_after_tool_model_request_receipt (
                    runtime_external_permit_id, arm_event_id, execution_id,
                    call_index, model_call_id, request_hash, lease_epoch,
                    body_sha256, exact_body
                )
                SELECT ?, ?, ?, 2, ?, ?, ?, ?, ?
                  FROM h12_model_call AS logical
                 WHERE logical.execution_id = ?
                   AND logical.call_index = 2
                   AND logical.model_call_id = ?
                   AND logical.request_hash = ?
                   AND logical.canonical_request = ?
                   AND (
                        logical.local_state = 'PREPARED'
                        OR (
                            logical.local_state = 'DISPATCHING'
                            AND EXISTS (
                                SELECT 1
                                  FROM h12_governed_after_tool_model_request_receipt AS prior
                                 WHERE prior.execution_id = logical.execution_id
                                   AND prior.call_index = logical.call_index
                            )
                        )
                   )
                   AND NOT EXISTS (
                        SELECT 1
                          FROM h12_governed_after_tool_model_request_receipt AS newer
                         WHERE newer.execution_id = logical.execution_id
                           AND newer.call_index = logical.call_index
                           AND newer.lease_epoch >= ?
                   )
                ON CONFLICT DO NOTHING
                """,
                (
                    str(receipt.runtime_external_permit_id),
                    str(receipt.arm_event_id),
                    str(receipt.execution_id),
                    str(request.model_call_id),
                    request.request_hash,
                    receipt.lease_epoch,
                    receipt.body_sha256,
                    receipt.exact_body,
                    str(receipt.execution_id),
                    str(request.model_call_id),
                    request.request_hash,
                    logical_canonical,
                    receipt.lease_epoch,
                ),
            )
            if inserted.rowcount != 1:
                concurrent = (
                    await self._load_governed_after_tool_model_receipt_unlocked(
                        database,
                        receipt.runtime_external_permit_id,
                    )
                )
                if concurrent == receipt:
                    return concurrent
                raise H12IntentConflict(
                    "AFTER_TOOL receipt collides with existing dispatch evidence"
                )
            stored = await self._load_governed_after_tool_model_receipt_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            if stored != receipt:
                raise H12IntentConflict("stored AFTER_TOOL receipt is inconsistent")
            return stored

    async def load_governed_after_tool_model_receipt(
        self,
        runtime_external_permit_id: UUID,
    ) -> GovernedAfterToolModelRequestReceipt | None:
        _require_non_nil_uuid(
            "runtime_external_permit_id",
            runtime_external_permit_id,
        )
        async with self._read_snapshot() as database:
            return await self._load_governed_after_tool_model_receipt_unlocked(
                database,
                runtime_external_permit_id,
            )

    async def _load_governed_after_tool_model_receipt_unlocked(
        self,
        database: aiosqlite.Connection,
        runtime_external_permit_id: UUID,
    ) -> GovernedAfterToolModelRequestReceipt | None:
        cursor = await database.execute(
            """
            SELECT *
              FROM h12_governed_after_tool_model_request_receipt
             WHERE runtime_external_permit_id = ?
            """,
            (str(runtime_external_permit_id),),
        )
        row = await cursor.fetchone()
        return (
            _governed_after_tool_model_receipt(row)
            if row is not None
            else None
        )

    async def load_governed_after_tool_model_receipt_history(
        self,
        execution_id: UUID,
    ) -> tuple[GovernedAfterToolModelRequestReceipt, ...]:
        _require_non_nil_uuid("execution_id", execution_id)
        async with self._read_snapshot() as database:
            cursor = await database.execute(
                """
                SELECT *
                  FROM h12_governed_after_tool_model_request_receipt
                 WHERE execution_id = ? AND call_index = 2
                 ORDER BY lease_epoch, runtime_external_permit_id
                """,
                (str(execution_id),),
            )
            rows = await cursor.fetchall()
        return tuple(_governed_after_tool_model_receipt(row) for row in rows)

    async def begin_governed_after_tool_model_dispatch(
        self,
        receipt: GovernedAfterToolModelRequestReceipt,
        fence: DriverFence,
    ) -> None:
        """Bind one exact call-two receipt after a fresh live Driver gate."""

        from dianlian_runtime.harness.governed_model_receipt import (
            GovernedAfterToolModelRequestReceipt,
        )
        from dianlian_runtime.supervisor.driver import DriverFence

        if not isinstance(receipt, GovernedAfterToolModelRequestReceipt):
            raise TypeError(
                "receipt must be a GovernedAfterToolModelRequestReceipt"
            )
        if not isinstance(fence, DriverFence):
            raise TypeError("fence must be a DriverFence")
        if not _after_tool_fence_matches_receipt(fence, receipt):
            raise H12CausalFenceRejected(
                "current Driver fence does not match the AFTER_TOOL receipt"
            )
        request = receipt.request
        now = _now_iso()
        async with self._write_transaction() as database:
            stored = await self._load_governed_after_tool_model_receipt_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            if stored != receipt:
                raise H12CausalFenceRejected(
                    "AFTER_TOOL dispatch requires the exact persisted receipt"
                )
            logical = await self._load_model_row_unlocked(
                database,
                receipt.execution_id,
                2,
            )
            if logical is None or (
                logical["model_call_id"] != str(request.model_call_id)
                or logical["request_hash"] != request.request_hash
            ):
                raise H12IntentConflict(
                    "AFTER_TOOL dispatch differs from the call-two intent"
                )
            if logical["local_state"] == LocalIntentState.TERMINAL.value:
                raise H12CausalFenceRejected(
                    "terminal call two cannot bind another dispatch"
                )
            existing = (
                await self._load_governed_after_tool_model_binding_unlocked(
                    database,
                    receipt.runtime_external_permit_id,
                )
            )
            if existing is not None:
                if not _after_tool_binding_matches_receipt(existing, receipt):
                    raise H12IntentConflict(
                        "runtime Permit id is bound to another call-two dispatch"
                    )
                if logical["local_state"] != LocalIntentState.DISPATCHING.value:
                    raise H12IntentConflict(
                        "AFTER_TOOL binding and local state differ"
                    )
                return
            inserted = await database.execute(
                """
                INSERT INTO h12_governed_after_tool_model_dispatch_binding (
                    runtime_external_permit_id, arm_event_id, execution_id,
                    call_index, model_call_id, request_hash, lease_epoch,
                    body_sha256, bound_at
                ) VALUES (?, ?, ?, 2, ?, ?, ?, ?, ?)
                """,
                (
                    str(receipt.runtime_external_permit_id),
                    str(receipt.arm_event_id),
                    str(receipt.execution_id),
                    str(request.model_call_id),
                    request.request_hash,
                    receipt.lease_epoch,
                    receipt.body_sha256,
                    now,
                ),
            )
            if inserted.rowcount != 1:
                raise H12IntentConflict("AFTER_TOOL binding was not appended")
            if logical["local_state"] == LocalIntentState.PREPARED.value:
                changed = await database.execute(
                    """
                    UPDATE h12_model_call
                       SET local_state = 'DISPATCHING', updated_at = ?
                     WHERE execution_id = ? AND call_index = 2
                       AND model_call_id = ? AND request_hash = ?
                       AND local_state = 'PREPARED'
                    """,
                    (
                        now,
                        str(receipt.execution_id),
                        str(request.model_call_id),
                        request.request_hash,
                    ),
                )
                if changed.rowcount != 1:
                    raise H12CausalFenceRejected(
                        "call-two intent is no longer PREPARED"
                    )
            elif logical["local_state"] != LocalIntentState.DISPATCHING.value:
                raise H12CausalFenceRejected(
                    "call-two intent cannot bind an AFTER_TOOL dispatch"
                )

    async def require_governed_after_tool_model_dispatch_binding(
        self,
        receipt: GovernedAfterToolModelRequestReceipt,
    ) -> None:
        from dianlian_runtime.harness.governed_model_receipt import (
            GovernedAfterToolModelRequestReceipt,
        )

        if not isinstance(receipt, GovernedAfterToolModelRequestReceipt):
            raise TypeError(
                "receipt must be a GovernedAfterToolModelRequestReceipt"
            )
        async with self._read_snapshot() as database:
            stored = await self._load_governed_after_tool_model_receipt_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            binding = await self._load_governed_after_tool_model_binding_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
        if (
            stored != receipt
            or binding is None
            or not _after_tool_binding_matches_receipt(binding, receipt)
        ):
            raise H12CausalFenceRejected(
                "AFTER_TOOL receipt has no exact historical dispatch binding"
            )

    async def complete_governed_after_tool_model(
        self,
        execution_id: UUID,
        fence: DriverFence,
        response: GovernedInitialModelCallResponse,
    ) -> None:
        """Accept one determinate call-two result under the current Run fence."""

        from dianlian_runtime.harness.governed_model_gateway import (
            GovernedInitialModelCallResponse,
        )
        from dianlian_runtime.supervisor.driver import DriverFence

        _require_non_nil_uuid("execution_id", execution_id)
        if not isinstance(fence, DriverFence):
            raise TypeError("fence must be a DriverFence")
        if not isinstance(response, GovernedInitialModelCallResponse):
            raise TypeError("response must be a GovernedInitialModelCallResponse")
        if response.model_call_id != stable_model_call_id(execution_id, 2):
            raise H12IntentConflict("AFTER_TOOL response differs from call two")

        completion = _governed_terminal_completion(response)
        if completion["outcome_kind"] == ModelOutcome.TOOL_SELECTION.value:
            raise H12CausalFenceRejected(
                "AFTER_TOOL model call cannot select another Tool"
            )
        attempted_permit = response.attempted_dispatch.runtime_external_permit_id
        persisted_permit = response.persisted_dispatch.runtime_external_permit_id
        now = _now_iso()

        async with self._write_transaction() as database:
            attempted = await self._load_governed_after_tool_model_receipt_unlocked(
                database,
                attempted_permit,
            )
            persisted = await self._load_governed_after_tool_model_receipt_unlocked(
                database,
                persisted_permit,
            )
            if (
                attempted is None
                or persisted is None
                or not _after_tool_response_identity_matches_receipt(
                    response.attempted_dispatch,
                    attempted,
                )
                or not _after_tool_response_identity_matches_receipt(
                    response.persisted_dispatch,
                    persisted,
                )
                or response.request_hash != attempted.request.request_hash
                or response.request_hash != persisted.request.request_hash
                or response.model_call_id != attempted.request.model_call_id
                or response.model_call_id != persisted.request.model_call_id
            ):
                raise H12IntentConflict(
                    "AFTER_TOOL result is not bound to receipt history"
                )
            if not _current_fence_can_settle_after_tool_receipt(fence, attempted):
                raise H12CausalFenceRejected(
                    "current Driver fence cannot settle the attempted call-two receipt"
                )
            attempted_binding = (
                await self._load_governed_after_tool_model_binding_unlocked(
                    database,
                    attempted.runtime_external_permit_id,
                )
            )
            persisted_binding = (
                await self._load_governed_after_tool_model_binding_unlocked(
                    database,
                    persisted.runtime_external_permit_id,
                )
            )
            if (
                attempted_binding is None
                or persisted_binding is None
                or not _after_tool_binding_matches_receipt(
                    attempted_binding,
                    attempted,
                )
                or not _after_tool_binding_matches_receipt(
                    persisted_binding,
                    persisted,
                )
            ):
                raise H12CausalFenceRejected(
                    "AFTER_TOOL result lacks exact dispatch history"
                )

            payload = json.dumps(
                completion["response_payload"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            evidence_values = _governed_terminal_evidence_values(
                execution_id,
                fence,
                response,
                completion["completion_kind"],
                payload_hash,
                now,
            )
            existing = await database.execute(
                """
                SELECT *
                  FROM h12_governed_after_tool_model_terminal_evidence
                 WHERE execution_id = ? AND call_index = 2
                """,
                (str(execution_id),),
            )
            existing_evidence = await existing.fetchone()
            logical = await self._load_model_row_unlocked(database, execution_id, 2)
            if existing_evidence is not None:
                if (
                    not _terminal_evidence_matches(
                        existing_evidence,
                        evidence_values,
                    )
                    or logical is None
                    or logical["local_state"] != LocalIntentState.TERMINAL.value
                    or logical["java_status"] != completion["java_status"]
                    or logical["outcome_kind"] != completion["outcome_kind"]
                    or logical["model_tool_selection_id"]
                    != completion["model_tool_selection_id"]
                    or logical["response_payload"] != payload
                ):
                    raise H12IntentConflict(
                        "AFTER_TOOL result conflicts with durable evidence"
                    )
                return
            if (
                logical is None
                or logical["local_state"] != LocalIntentState.DISPATCHING.value
                or logical["model_call_id"] != str(response.model_call_id)
                or logical["request_hash"] != response.request_hash
            ):
                raise H12CausalFenceRejected(
                    "call two is not eligible for terminal convergence"
                )

            inserted = await database.execute(
                """
                INSERT INTO h12_governed_after_tool_model_terminal_evidence (
                    execution_id, call_index, model_call_id, request_hash,
                    persisted_permit_id, persisted_arm_event_id,
                    persisted_lease_epoch, attempted_permit_id,
                    attempted_arm_event_id, attempted_lease_epoch,
                    completion_kind, outcome_event_id, outcome_status,
                    source_fact_id, source_fact_version, source_fact_hash,
                    outcome_code, result_hash, response_payload_hash,
                    accepted_by_lease_owner, accepted_by_lease_epoch, completed_at
                ) VALUES (
                    ?, 2, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                evidence_values,
            )
            if inserted.rowcount != 1:
                raise H12IntentConflict(
                    "AFTER_TOOL terminal evidence was not appended"
                )
            changed = await database.execute(
                """
                UPDATE h12_model_call
                   SET local_state = 'TERMINAL', java_status = ?, outcome_kind = ?,
                       model_tool_selection_id = NULL,
                       response_payload = ?, updated_at = ?
                 WHERE execution_id = ? AND call_index = 2
                   AND model_call_id = ? AND request_hash = ?
                   AND local_state = 'DISPATCHING'
                """,
                (
                    completion["java_status"],
                    completion["outcome_kind"],
                    payload,
                    now,
                    str(execution_id),
                    str(response.model_call_id),
                    response.request_hash,
                ),
            )
            if changed.rowcount != 1:
                raise H12CausalFenceRejected(
                    "call two changed during terminal convergence"
                )

    async def load_governed_after_tool_terminal_evidence(
        self,
        execution_id: UUID,
    ) -> GovernedAfterToolTerminalEvidence | None:
        _require_non_nil_uuid("execution_id", execution_id)
        async with self._read_snapshot() as database:
            cursor = await database.execute(
                """
                SELECT evidence.*, model.java_status, model.response_payload
                  FROM h12_governed_after_tool_model_terminal_evidence AS evidence
                  JOIN h12_model_call AS model
                    ON model.execution_id = evidence.execution_id
                   AND model.call_index = evidence.call_index
                   AND model.model_call_id = evidence.model_call_id
                   AND model.request_hash = evidence.request_hash
                 WHERE evidence.execution_id = ? AND evidence.call_index = 2
                   AND model.local_state = 'TERMINAL'
                """,
                (str(execution_id),),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["response_payload"]))
        if not isinstance(payload, dict):
            raise H12IntentConflict("AFTER_TOOL payload is not a JSON object")
        evidence = GovernedAfterToolTerminalEvidence(
            execution_id=UUID(str(row["execution_id"])),
            model_call_id=UUID(str(row["model_call_id"])),
            request_hash=str(row["request_hash"]),
            completion_kind=str(row["completion_kind"]),
            persisted_permit_id=UUID(str(row["persisted_permit_id"])),
            attempted_permit_id=UUID(str(row["attempted_permit_id"])),
            outcome_status=(
                str(row["outcome_status"])
                if row["outcome_status"] is not None
                else None
            ),
            source_fact_id=(
                UUID(str(row["source_fact_id"]))
                if row["source_fact_id"] is not None
                else None
            ),
            source_fact_version=(
                int(row["source_fact_version"])
                if row["source_fact_version"] is not None
                else None
            ),
            source_fact_hash=(
                str(row["source_fact_hash"])
                if row["source_fact_hash"] is not None
                else None
            ),
            outcome_code=(
                str(row["outcome_code"])
                if row["outcome_code"] is not None
                else None
            ),
            java_status=str(row["java_status"]),
            response_payload=payload,
        )
        _validate_governed_terminal_evidence(evidence)
        return evidence

    async def persist_governed_tool_receipt(
        self,
        receipt: GovernedToolRequestReceipt,
    ) -> GovernedToolRequestReceipt:
        """Append one exact Tool request without authorizing its Java POST."""

        from dianlian_runtime.harness.governed_tool_receipt import (
            GovernedToolRequestReceipt,
        )

        if not isinstance(receipt, GovernedToolRequestReceipt):
            raise TypeError("receipt must be a GovernedToolRequestReceipt")
        request = receipt.request
        logical_canonical, logical_hash = canonical_intent(
            request.logical_payload()
        )
        async with self._write_transaction() as database:
            row = await self._load_tool_row_unlocked(database, receipt.execution_id)
            if row is None:
                raise H12CausalFenceRejected(
                    "governed Tool receipt requires an existing logical Tool slot"
                )
            if (
                row["tool_invocation_id"] != str(request.tool_invocation_id)
                or row["source_model_call_id"]
                != str(request.source_model_call_id)
                or row["model_tool_selection_id"]
                != str(request.model_tool_selection_id)
                or row["request_hash"] != request.request_hash
                or row["request_hash"] != logical_hash
                or row["canonical_request"] != logical_canonical
            ):
                raise H12IntentConflict(
                    "governed Tool receipt differs from the durable logical intent"
                )

            existing = await self._load_governed_tool_receipt_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            if existing is not None:
                if existing != receipt:
                    raise H12IntentConflict(
                        "runtime Permit id is bound to another exact Tool request"
                    )
                return existing

            history_summary = await database.execute(
                """
                SELECT COUNT(*), MAX(lease_epoch)
                  FROM h12_governed_tool_request_receipt
                 WHERE execution_id = ? AND tool_call_slot = 1
                """,
                (str(receipt.execution_id),),
            )
            summary_row = await history_summary.fetchone()
            prior_receipts = int(summary_row[0]) if summary_row is not None else 0
            latest_lease_epoch = (
                int(summary_row[1])
                if summary_row is not None and summary_row[1] is not None
                else None
            )
            local_state = LocalIntentState(str(row["local_state"]))
            if local_state == LocalIntentState.TERMINAL:
                raise H12CausalFenceRejected(
                    "terminal Tool slot cannot accept another request receipt"
                )
            if prior_receipts == 0 and local_state != LocalIntentState.PREPARED:
                raise H12CausalFenceRejected(
                    "first governed Tool receipt must be persisted from PREPARED"
                )
            if (
                latest_lease_epoch is not None
                and receipt.lease_epoch <= latest_lease_epoch
            ):
                raise H12IntentConflict(
                    "a new governed Tool receipt must advance the lease epoch"
                )

            inserted = await database.execute(
                """
                INSERT INTO h12_governed_tool_request_receipt (
                    runtime_external_permit_id, arm_event_id, execution_id,
                    tool_call_slot, tool_invocation_id, source_model_call_id,
                    model_tool_selection_id, request_hash, lease_epoch,
                    body_sha256, exact_body
                )
                SELECT ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?
                  FROM h12_tool_call AS logical
                 WHERE logical.execution_id = ?
                   AND logical.tool_call_slot = 1
                   AND logical.tool_invocation_id = ?
                   AND logical.source_model_call_id = ?
                   AND logical.model_tool_selection_id = ?
                   AND logical.request_hash = ?
                   AND logical.canonical_request = ?
                   AND (
                        logical.local_state = 'PREPARED'
                        OR (
                            logical.local_state = 'DISPATCHING'
                            AND EXISTS (
                                SELECT 1
                                  FROM h12_governed_tool_request_receipt AS prior
                                 WHERE prior.execution_id = logical.execution_id
                                   AND prior.tool_call_slot = logical.tool_call_slot
                            )
                        )
                   )
                   AND NOT EXISTS (
                        SELECT 1
                          FROM h12_governed_tool_request_receipt AS newer
                         WHERE newer.execution_id = logical.execution_id
                           AND newer.tool_call_slot = logical.tool_call_slot
                           AND newer.lease_epoch >= ?
                   )
                ON CONFLICT DO NOTHING
                """,
                (
                    str(receipt.runtime_external_permit_id),
                    str(receipt.arm_event_id),
                    str(receipt.execution_id),
                    str(request.tool_invocation_id),
                    str(request.source_model_call_id),
                    str(request.model_tool_selection_id),
                    request.request_hash,
                    receipt.lease_epoch,
                    receipt.body_sha256,
                    receipt.exact_body,
                    str(receipt.execution_id),
                    str(request.tool_invocation_id),
                    str(request.source_model_call_id),
                    str(request.model_tool_selection_id),
                    request.request_hash,
                    logical_canonical,
                    receipt.lease_epoch,
                ),
            )
            if inserted.rowcount != 1:
                concurrent = await self._load_governed_tool_receipt_unlocked(
                    database,
                    receipt.runtime_external_permit_id,
                )
                if concurrent == receipt:
                    return concurrent
                raise H12IntentConflict(
                    "governed Tool receipt collides with Permit, Arm or lease history"
                )
            stored = await self._load_governed_tool_receipt_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            if stored != receipt:
                raise H12IntentConflict(
                    "stored governed Tool request receipt is inconsistent"
                )
            return stored

    async def load_governed_tool_receipt(
        self,
        runtime_external_permit_id: UUID,
    ) -> GovernedToolRequestReceipt | None:
        """Read one exact historical Tool receipt; never select a usable latest."""

        _require_non_nil_uuid(
            "runtime_external_permit_id",
            runtime_external_permit_id,
        )
        async with self._read_snapshot() as database:
            return await self._load_governed_tool_receipt_unlocked(
                database,
                runtime_external_permit_id,
            )

    async def _load_governed_tool_receipt_unlocked(
        self,
        database: aiosqlite.Connection,
        runtime_external_permit_id: UUID,
    ) -> GovernedToolRequestReceipt | None:
        cursor = await database.execute(
            """
            SELECT *
              FROM h12_governed_tool_request_receipt
             WHERE runtime_external_permit_id = ?
            """,
            (str(runtime_external_permit_id),),
        )
        row = await cursor.fetchone()
        return _governed_tool_receipt(row) if row is not None else None

    async def load_governed_tool_receipt_history(
        self,
        execution_id: UUID,
    ) -> tuple[GovernedToolRequestReceipt, ...]:
        """Return all Tool receipts for explicit reconciliation only."""

        _require_non_nil_uuid("execution_id", execution_id)
        async with self._read_snapshot() as database:
            cursor = await database.execute(
                """
                SELECT *
                  FROM h12_governed_tool_request_receipt
                 WHERE execution_id = ? AND tool_call_slot = 1
                 ORDER BY lease_epoch, runtime_external_permit_id
                """,
                (str(execution_id),),
            )
            rows = await cursor.fetchall()
        return tuple(_governed_tool_receipt(row) for row in rows)

    async def begin_governed_tool_dispatch(
        self,
        receipt: GovernedToolRequestReceipt,
        fence: DriverFence,
    ) -> None:
        """Bind an exact Tool receipt after a fresh live Driver gate."""

        from dianlian_runtime.harness.governed_tool_receipt import (
            GovernedToolRequestReceipt,
        )
        from dianlian_runtime.supervisor.driver import DriverFence

        if not isinstance(receipt, GovernedToolRequestReceipt):
            raise TypeError("receipt must be a GovernedToolRequestReceipt")
        if not isinstance(fence, DriverFence):
            raise TypeError("fence must be a DriverFence")
        if not _tool_fence_matches_receipt(fence, receipt):
            raise H12CausalFenceRejected(
                "current Driver fence does not match the governed Tool receipt"
            )

        request = receipt.request
        now = _now_iso()
        async with self._write_transaction() as database:
            stored = await self._load_governed_tool_receipt_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            if stored != receipt:
                raise H12CausalFenceRejected(
                    "governed Tool dispatch requires the exact persisted receipt"
                )
            logical = await self._load_tool_row_unlocked(
                database,
                receipt.execution_id,
            )
            if logical is None or (
                logical["tool_invocation_id"] != str(request.tool_invocation_id)
                or logical["source_model_call_id"]
                != str(request.source_model_call_id)
                or logical["model_tool_selection_id"]
                != str(request.model_tool_selection_id)
                or logical["request_hash"] != request.request_hash
            ):
                raise H12IntentConflict(
                    "governed Tool dispatch differs from its durable logical intent"
                )
            if logical["local_state"] == LocalIntentState.TERMINAL.value:
                raise H12CausalFenceRejected(
                    "terminal Tool slot cannot bind another governed dispatch"
                )

            existing = await self._load_governed_tool_dispatch_binding_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            if existing is not None:
                if not _tool_binding_matches_receipt(existing, receipt):
                    raise H12IntentConflict(
                        "runtime Permit id is bound to another governed Tool dispatch"
                    )
                if logical["local_state"] != LocalIntentState.DISPATCHING.value:
                    raise H12IntentConflict(
                        "governed Tool binding and local state differ"
                    )
                return

            inserted = await database.execute(
                """
                INSERT INTO h12_governed_tool_dispatch_binding (
                    runtime_external_permit_id, arm_event_id, execution_id,
                    tool_call_slot, tool_invocation_id, source_model_call_id,
                    model_tool_selection_id, request_hash, lease_epoch,
                    body_sha256, bound_at
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(receipt.runtime_external_permit_id),
                    str(receipt.arm_event_id),
                    str(receipt.execution_id),
                    str(request.tool_invocation_id),
                    str(request.source_model_call_id),
                    str(request.model_tool_selection_id),
                    request.request_hash,
                    receipt.lease_epoch,
                    receipt.body_sha256,
                    now,
                ),
            )
            if inserted.rowcount != 1:
                raise H12IntentConflict(
                    "governed Tool dispatch evidence was not appended"
                )
            if logical["local_state"] == LocalIntentState.PREPARED.value:
                changed = await database.execute(
                    """
                    UPDATE h12_tool_call
                       SET local_state = 'DISPATCHING', updated_at = ?
                     WHERE execution_id = ? AND tool_call_slot = 1
                       AND tool_invocation_id = ?
                       AND source_model_call_id = ?
                       AND model_tool_selection_id = ?
                       AND request_hash = ?
                       AND local_state = 'PREPARED'
                    """,
                    (
                        now,
                        str(receipt.execution_id),
                        str(request.tool_invocation_id),
                        str(request.source_model_call_id),
                        str(request.model_tool_selection_id),
                        request.request_hash,
                    ),
                )
                if changed.rowcount != 1:
                    raise H12CausalFenceRejected(
                        "logical Tool slot is no longer PREPARED"
                    )
            elif logical["local_state"] != LocalIntentState.DISPATCHING.value:
                raise H12CausalFenceRejected(
                    "logical Tool slot cannot bind a governed dispatch"
                )

    async def complete_governed_tool(
        self,
        execution_id: UUID,
        fence: DriverFence,
        response: GovernedToolCallResponse,
    ) -> None:
        """Release a Tool slot only from an exact, determinate canonical fact."""

        from dianlian_runtime.harness.governed_tool_gateway import (
            GovernedToolCallResponse,
        )
        from dianlian_runtime.supervisor.driver import DriverFence

        _require_non_nil_uuid("execution_id", execution_id)
        if not isinstance(fence, DriverFence):
            raise TypeError("fence must be a DriverFence")
        if not isinstance(response, GovernedToolCallResponse):
            raise TypeError("response must be a GovernedToolCallResponse")
        if response.tool_invocation_id != stable_tool_call_id(execution_id):
            raise H12IntentConflict(
                "governed Tool response differs from the durable slot"
            )

        completion = _governed_tool_terminal_completion(response)
        attempted_permit = response.attempted_dispatch.runtime_external_permit_id
        persisted_permit = response.persisted_dispatch.runtime_external_permit_id
        now = _now_iso()

        async with self._write_transaction() as database:
            attempted = await self._load_governed_tool_receipt_unlocked(
                database,
                attempted_permit,
            )
            persisted = await self._load_governed_tool_receipt_unlocked(
                database,
                persisted_permit,
            )
            if (
                attempted is None
                or persisted is None
                or not _tool_response_identity_matches_receipt(
                    response.attempted_dispatch,
                    attempted,
                )
                or not _tool_response_identity_matches_receipt(
                    response.persisted_dispatch,
                    persisted,
                )
                or response.request_hash != attempted.request.request_hash
                or response.request_hash != persisted.request.request_hash
                or response.tool_invocation_id
                != attempted.request.tool_invocation_id
                or response.tool_invocation_id
                != persisted.request.tool_invocation_id
            ):
                raise H12IntentConflict(
                    "governed Tool terminal response is not bound to receipt history"
                )
            if not _current_fence_can_settle_tool_receipt(fence, attempted):
                raise H12CausalFenceRejected(
                    "current Driver fence cannot settle the attempted Tool receipt"
                )
            attempted_binding = (
                await self._load_governed_tool_dispatch_binding_unlocked(
                    database,
                    attempted.runtime_external_permit_id,
                )
            )
            persisted_binding = (
                await self._load_governed_tool_dispatch_binding_unlocked(
                    database,
                    persisted.runtime_external_permit_id,
                )
            )
            if (
                attempted_binding is None
                or persisted_binding is None
                or not _tool_binding_matches_receipt(
                    attempted_binding,
                    attempted,
                )
                or not _tool_binding_matches_receipt(
                    persisted_binding,
                    persisted,
                )
            ):
                raise H12CausalFenceRejected(
                    "governed Tool terminal response lacks dispatch history"
                )

            payload = json.dumps(
                completion["response_payload"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            evidence_values = _governed_tool_terminal_evidence_values(
                execution_id,
                fence,
                response,
                persisted,
                attempted,
                payload_hash,
                now,
            )
            existing = await database.execute(
                """
                SELECT *
                  FROM h12_governed_tool_terminal_evidence
                 WHERE execution_id = ?
                """,
                (str(execution_id),),
            )
            existing_evidence = await existing.fetchone()
            logical = await self._load_tool_row_unlocked(database, execution_id)
            if existing_evidence is not None:
                if (
                    not _tool_terminal_evidence_matches(
                        existing_evidence,
                        evidence_values,
                    )
                    or logical is None
                    or logical["local_state"] != LocalIntentState.TERMINAL.value
                    or logical["java_status"] != completion["java_status"]
                    or logical["response_payload"] != payload
                ):
                    raise H12IntentConflict(
                        "governed Tool terminal result conflicts with durable evidence"
                    )
                return
            if (
                logical is None
                or logical["local_state"] != LocalIntentState.DISPATCHING.value
                or logical["tool_invocation_id"]
                != str(response.tool_invocation_id)
                or logical["request_hash"] != response.request_hash
            ):
                raise H12CausalFenceRejected(
                    "governed Tool slot is not eligible for terminal convergence"
                )

            inserted = await database.execute(
                """
                INSERT INTO h12_governed_tool_terminal_evidence (
                    execution_id, tool_call_slot, tool_invocation_id,
                    source_model_call_id, model_tool_selection_id, request_hash,
                    persisted_permit_id, persisted_arm_event_id,
                    persisted_lease_epoch, attempted_permit_id,
                    attempted_arm_event_id, attempted_lease_epoch,
                    outcome_event_id, outcome_status, source_fact_id,
                    source_fact_version, source_fact_hash, outcome_code,
                    result_hash, response_payload_hash,
                    accepted_by_lease_owner, accepted_by_lease_epoch, completed_at
                ) VALUES (
                    ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                evidence_values,
            )
            if inserted.rowcount != 1:
                raise H12IntentConflict(
                    "governed Tool terminal evidence was not appended"
                )
            changed = await database.execute(
                """
                UPDATE h12_tool_call
                   SET local_state = 'TERMINAL', java_status = ?,
                       response_payload = ?, updated_at = ?
                 WHERE execution_id = ? AND tool_call_slot = 1
                   AND tool_invocation_id = ? AND request_hash = ?
                   AND local_state = 'DISPATCHING'
                """,
                (
                    completion["java_status"],
                    payload,
                    now,
                    str(execution_id),
                    str(response.tool_invocation_id),
                    response.request_hash,
                ),
            )
            if changed.rowcount != 1:
                raise H12CausalFenceRejected(
                    "governed Tool slot changed during terminal convergence"
                )

    async def load_governed_tool_terminal_evidence(
        self,
        execution_id: UUID,
    ) -> GovernedToolTerminalEvidence | None:
        """Load committed Tool convergence evidence without authorizing an action."""

        _require_non_nil_uuid("execution_id", execution_id)
        async with self._read_snapshot() as database:
            cursor = await database.execute(
                """
                SELECT evidence.*, tool.java_status, tool.response_payload
                  FROM h12_governed_tool_terminal_evidence AS evidence
                  JOIN h12_tool_call AS tool
                    ON tool.execution_id = evidence.execution_id
                   AND tool.tool_call_slot = evidence.tool_call_slot
                   AND tool.tool_invocation_id = evidence.tool_invocation_id
                   AND tool.request_hash = evidence.request_hash
                 WHERE evidence.execution_id = ?
                   AND tool.local_state = 'TERMINAL'
                """,
                (str(execution_id),),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["response_payload"]))
        if not isinstance(payload, dict):
            raise H12IntentConflict(
                "governed Tool terminal payload is not a JSON object"
            )
        evidence = GovernedToolTerminalEvidence(
            execution_id=UUID(str(row["execution_id"])),
            tool_invocation_id=UUID(str(row["tool_invocation_id"])),
            request_hash=str(row["request_hash"]),
            persisted_permit_id=UUID(str(row["persisted_permit_id"])),
            attempted_permit_id=UUID(str(row["attempted_permit_id"])),
            outcome_status=str(row["outcome_status"]),
            source_fact_id=UUID(str(row["source_fact_id"])),
            source_fact_version=int(row["source_fact_version"]),
            source_fact_hash=str(row["source_fact_hash"]),
            outcome_code=str(row["outcome_code"]),
            java_status=str(row["java_status"]),
            response_payload=payload,
        )
        _validate_governed_tool_terminal_evidence(evidence)
        return evidence

    async def require_governed_tool_dispatch_binding(
        self,
        receipt: GovernedToolRequestReceipt,
    ) -> None:
        """Require exact historical Tool dispatch evidence without authorizing POST."""

        from dianlian_runtime.harness.governed_tool_receipt import (
            GovernedToolRequestReceipt,
        )

        if not isinstance(receipt, GovernedToolRequestReceipt):
            raise TypeError("receipt must be a GovernedToolRequestReceipt")
        async with self._read_snapshot() as database:
            stored = await self._load_governed_tool_receipt_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
            binding = await self._load_governed_tool_dispatch_binding_unlocked(
                database,
                receipt.runtime_external_permit_id,
            )
        if (
            stored != receipt
            or binding is None
            or not _tool_binding_matches_receipt(binding, receipt)
        ):
            raise H12CausalFenceRejected(
                "governed Tool receipt has no exact historical dispatch binding"
            )

    @asynccontextmanager
    async def _read_snapshot(self) -> AsyncIterator[aiosqlite.Connection]:
        """Read only committed evidence without joining the writer transaction."""

        self._require_database()
        database = await aiosqlite.connect(
            f"{self._path.resolve().as_uri()}?mode=ro",
            uri=True,
        )
        database.row_factory = aiosqlite.Row
        try:
            await database.execute("BEGIN")
            yield database
        finally:
            await database.close()

    @asynccontextmanager
    async def _write_transaction(
        self,
    ) -> AsyncIterator[aiosqlite.Connection]:
        """Keep one connection's commits and rollbacks inside one writer boundary."""

        async with self._write_lock:
            database = self._require_database()
            try:
                await database.execute("BEGIN IMMEDIATE")
                yield database
                await database.commit()
            except BaseException:
                await self._rollback_before_unlock(database)
                raise

    async def _rollback_before_unlock(
        self,
        database: aiosqlite.Connection,
    ) -> None:
        rollback = asyncio.create_task(database.rollback())
        try:
            await asyncio.shield(rollback)
        except asyncio.CancelledError:
            await rollback
            raise

    async def _require_successful_tool_unlocked(
        self,
        database: aiosqlite.Connection,
        execution_id: UUID,
    ) -> None:
        tool = await self._load_tool_unlocked(database, execution_id)
        if (
            tool is None
            or tool.local_state != LocalIntentState.TERMINAL
            or tool.java_status != "SUCCEEDED"
        ):
            raise H12CausalFenceRejected(
                "second model call requires a terminal successful tool slot"
            )
        governed = await database.execute(
            """
            SELECT 1
              FROM h12_governed_tool_request_receipt
             WHERE execution_id = ? AND tool_call_slot = 1
             LIMIT 1
            """,
            (str(execution_id),),
        )
        if await governed.fetchone() is None:
            return
        evidence = await database.execute(
            """
            SELECT 1
              FROM h12_governed_tool_terminal_evidence
             WHERE execution_id = ? AND tool_call_slot = 1
               AND tool_invocation_id = ? AND request_hash = ?
               AND outcome_status = 'SUCCEEDED'
            """,
            (
                str(execution_id),
                str(tool.intent_id),
                tool.request_hash,
            ),
        )
        if await evidence.fetchone() is None:
            raise H12CausalFenceRejected(
                "second model call requires governed Tool terminal evidence"
            )

    async def _mark_dispatching(
        self,
        table: str,
        execution_id: UUID,
        call_index: int | None,
    ) -> None:
        suffix = " AND call_index = ?" if call_index is not None else ""
        parameters: tuple[Any, ...] = (
            (_now_iso(), str(execution_id), call_index)
            if call_index is not None
            else (_now_iso(), str(execution_id))
        )
        async with self._write_transaction() as database:
            if table == "h12_model_call":
                governed = await database.execute(
                    """
                    SELECT 1 FROM h12_governed_model_request_receipt
                     WHERE execution_id = ? AND call_index = ?
                    UNION ALL
                    SELECT 1 FROM h12_governed_after_tool_model_request_receipt
                     WHERE execution_id = ? AND call_index = ?
                     LIMIT 1
                    """,
                    (
                        str(execution_id),
                        call_index,
                        str(execution_id),
                        call_index,
                    ),
                )
                if await governed.fetchone() is not None:
                    raise H12CausalFenceRejected(
                        "governed model intent requires an exact dispatch receipt"
                    )
            elif table == "h12_tool_call":
                governed = await database.execute(
                    """
                    SELECT 1
                      FROM h12_governed_tool_request_receipt
                     WHERE execution_id = ? AND tool_call_slot = 1
                     LIMIT 1
                    """,
                    (str(execution_id),),
                )
                if await governed.fetchone() is not None:
                    raise H12CausalFenceRejected(
                        "governed Tool intent requires an exact dispatch receipt"
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
        async with self._write_transaction() as database:
            if table == "h12_model_call":
                governed = await database.execute(
                    """
                    SELECT 1 FROM h12_governed_model_request_receipt
                     WHERE execution_id = ? AND call_index = ?
                    UNION ALL
                    SELECT 1 FROM h12_governed_after_tool_model_request_receipt
                     WHERE execution_id = ? AND call_index = ?
                     LIMIT 1
                    """,
                    (
                        str(execution_id),
                        call_index,
                        str(execution_id),
                        call_index,
                    ),
                )
                if await governed.fetchone() is not None:
                    raise H12CausalFenceRejected(
                        "governed model intent requires canonical terminal evidence"
                    )
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
                governed = await database.execute(
                    """
                    SELECT 1
                      FROM h12_governed_tool_request_receipt
                     WHERE execution_id = ? AND tool_call_slot = 1
                     LIMIT 1
                    """,
                    (str(execution_id),),
                )
                if await governed.fetchone() is not None:
                    raise H12CausalFenceRejected(
                        "governed Tool intent requires canonical terminal evidence"
                    )
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
                current = (
                    await self._load_model_unlocked(
                        database,
                        execution_id,
                        call_index or 0,
                    )
                    if table == "h12_model_call"
                    else await self._load_tool_unlocked(database, execution_id)
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
                raise H12IntentConflict(
                    "terminal result conflicts with durable evidence"
                )

    async def _load_model_unlocked(
        self,
        database: aiosqlite.Connection,
        execution_id: UUID,
        call_index: int,
    ) -> DurableIntent | None:
        row = await self._load_model_row_unlocked(
            database,
            execution_id,
            call_index,
        )
        return _intent(row, call_index) if row is not None else None

    async def _load_model_row_unlocked(
        self,
        database: aiosqlite.Connection,
        execution_id: UUID,
        call_index: int,
    ) -> aiosqlite.Row | None:
        cursor = await database.execute(
            "SELECT * FROM h12_model_call WHERE execution_id = ? AND call_index = ?",
            (str(execution_id), call_index),
        )
        return await cursor.fetchone()

    async def _load_governed_dispatch_binding_unlocked(
        self,
        database: aiosqlite.Connection,
        runtime_external_permit_id: UUID,
    ) -> aiosqlite.Row | None:
        cursor = await database.execute(
            """
            SELECT *
              FROM h12_governed_model_dispatch_binding
             WHERE runtime_external_permit_id = ?
            """,
            (str(runtime_external_permit_id),),
        )
        return await cursor.fetchone()

    async def _load_governed_after_tool_model_binding_unlocked(
        self,
        database: aiosqlite.Connection,
        runtime_external_permit_id: UUID,
    ) -> aiosqlite.Row | None:
        cursor = await database.execute(
            """
            SELECT *
              FROM h12_governed_after_tool_model_dispatch_binding
             WHERE runtime_external_permit_id = ?
            """,
            (str(runtime_external_permit_id),),
        )
        return await cursor.fetchone()

    async def _load_governed_tool_dispatch_binding_unlocked(
        self,
        database: aiosqlite.Connection,
        runtime_external_permit_id: UUID,
    ) -> aiosqlite.Row | None:
        cursor = await database.execute(
            """
            SELECT *
              FROM h12_governed_tool_dispatch_binding
             WHERE runtime_external_permit_id = ?
            """,
            (str(runtime_external_permit_id),),
        )
        return await cursor.fetchone()

    async def _load_tool_unlocked(
        self,
        database: aiosqlite.Connection,
        execution_id: UUID,
    ) -> DurableIntent | None:
        row = await self._load_tool_row_unlocked(database, execution_id)
        return _intent(row, 1) if row is not None else None

    async def _load_tool_row_unlocked(
        self,
        database: aiosqlite.Connection,
        execution_id: UUID,
    ) -> aiosqlite.Row | None:
        cursor = await database.execute(
            "SELECT * FROM h12_tool_call WHERE execution_id = ?",
            (str(execution_id),),
        )
        return await cursor.fetchone()

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


def _governed_receipt(
    row: aiosqlite.Row,
) -> GovernedInitialModelRequestReceipt:
    from dianlian_runtime.harness.governed_model_receipt import (
        GovernedInitialModelRequestReceipt,
    )

    raw_body = row["exact_body"]
    exact_body = bytes(raw_body) if not isinstance(raw_body, bytes) else raw_body
    receipt = GovernedInitialModelRequestReceipt.restore(
        UUID(str(row["execution_id"])),
        exact_body,
        str(row["body_sha256"]),
    )
    if (
        row["call_index"] != 1
        or row["model_call_id"] != str(receipt.request.model_call_id)
        or row["request_hash"] != receipt.request.request_hash
        or row["runtime_external_permit_id"]
        != str(receipt.runtime_external_permit_id)
        or row["arm_event_id"] != str(receipt.arm_event_id)
        or row["lease_epoch"] != receipt.lease_epoch
    ):
        raise H12IntentConflict("stored governed request receipt is inconsistent")
    return receipt


def _governed_after_tool_model_receipt(
    row: aiosqlite.Row,
) -> GovernedAfterToolModelRequestReceipt:
    from dianlian_runtime.harness.governed_model_receipt import (
        GovernedAfterToolModelRequestReceipt,
    )

    raw_body = row["exact_body"]
    exact_body = bytes(raw_body) if not isinstance(raw_body, bytes) else raw_body
    receipt = GovernedAfterToolModelRequestReceipt.restore(
        UUID(str(row["execution_id"])),
        exact_body,
        str(row["body_sha256"]),
    )
    if (
        row["call_index"] != 2
        or row["model_call_id"] != str(receipt.request.model_call_id)
        or row["request_hash"] != receipt.request.request_hash
        or row["runtime_external_permit_id"]
        != str(receipt.runtime_external_permit_id)
        or row["arm_event_id"] != str(receipt.arm_event_id)
        or row["lease_epoch"] != receipt.lease_epoch
    ):
        raise H12IntentConflict("stored AFTER_TOOL receipt is inconsistent")
    return receipt


def _governed_tool_receipt(
    row: aiosqlite.Row,
) -> GovernedToolRequestReceipt:
    from dianlian_runtime.harness.governed_tool_receipt import (
        GovernedToolRequestReceipt,
    )

    raw_body = row["exact_body"]
    exact_body = bytes(raw_body) if not isinstance(raw_body, bytes) else raw_body
    receipt = GovernedToolRequestReceipt.restore(
        UUID(str(row["execution_id"])),
        exact_body,
        str(row["body_sha256"]),
    )
    request = receipt.request
    if (
        row["tool_call_slot"] != 1
        or row["tool_invocation_id"] != str(request.tool_invocation_id)
        or row["source_model_call_id"] != str(request.source_model_call_id)
        or row["model_tool_selection_id"]
        != str(request.model_tool_selection_id)
        or row["request_hash"] != request.request_hash
        or row["runtime_external_permit_id"]
        != str(receipt.runtime_external_permit_id)
        or row["arm_event_id"] != str(receipt.arm_event_id)
        or row["lease_epoch"] != receipt.lease_epoch
    ):
        raise H12IntentConflict("stored governed Tool receipt is inconsistent")
    return receipt


def _fence_matches_receipt(
    fence: DriverFence,
    receipt: GovernedInitialModelRequestReceipt,
) -> bool:
    request = receipt.request
    arm = request.dispatch_arm
    return (
        fence.tenant_id == arm.tenant_id
        and fence.runtime_run_id == receipt.execution_id
        and fence.task_execution_generation == request.execution_generation
        and fence.lease_owner == arm.lease_owner
        and fence.lease_epoch == arm.lease_epoch
        and fence.admission_contract_version == "2.2"
        and fence.admission_snapshot_id == request.admission_snapshot_id
        and fence.admission_snapshot_hash == arm.admission_snapshot_hash
    )


def _tool_fence_matches_receipt(
    fence: DriverFence,
    receipt: GovernedToolRequestReceipt,
) -> bool:
    request = receipt.request
    arm = request.dispatch_arm
    return (
        fence.tenant_id == arm.tenant_id
        and fence.runtime_run_id == receipt.execution_id
        and fence.task_execution_generation == request.execution_generation
        and fence.lease_owner == arm.lease_owner
        and fence.lease_epoch == arm.lease_epoch
        and fence.admission_contract_version == "2.2"
        and fence.admission_snapshot_id == request.admission_snapshot_id
        and fence.admission_snapshot_hash == arm.admission_snapshot_hash
    )


def _after_tool_fence_matches_receipt(
    fence: DriverFence,
    receipt: GovernedAfterToolModelRequestReceipt,
) -> bool:
    request = receipt.request
    arm = request.dispatch_arm
    return (
        fence.tenant_id == arm.tenant_id
        and fence.runtime_run_id == receipt.execution_id
        and fence.task_execution_generation == request.execution_generation
        and fence.lease_owner == arm.lease_owner
        and fence.lease_epoch == arm.lease_epoch
        and fence.admission_contract_version == "2.2"
        and fence.admission_snapshot_id == request.admission_snapshot_id
        and fence.admission_snapshot_hash == arm.admission_snapshot_hash
    )


def _current_fence_can_settle_receipt(
    fence: DriverFence,
    receipt: GovernedInitialModelRequestReceipt,
) -> bool:
    request = receipt.request
    arm = request.dispatch_arm
    lease_topology_matches = (
        fence.lease_epoch > arm.lease_epoch
        or (
            fence.lease_epoch == arm.lease_epoch
            and fence.lease_owner == arm.lease_owner
        )
    )
    return (
        fence.tenant_id == arm.tenant_id
        and fence.runtime_run_id == receipt.execution_id
        and fence.task_execution_generation == request.execution_generation
        and fence.admission_contract_version == "2.2"
        and fence.admission_snapshot_id == request.admission_snapshot_id
        and fence.admission_snapshot_hash == arm.admission_snapshot_hash
        and lease_topology_matches
    )


def _current_fence_can_settle_after_tool_receipt(
    fence: DriverFence,
    receipt: GovernedAfterToolModelRequestReceipt,
) -> bool:
    request = receipt.request
    arm = request.dispatch_arm
    lease_topology_matches = (
        fence.lease_epoch > arm.lease_epoch
        or (
            fence.lease_epoch == arm.lease_epoch
            and fence.lease_owner == arm.lease_owner
        )
    )
    return (
        fence.tenant_id == arm.tenant_id
        and fence.runtime_run_id == receipt.execution_id
        and fence.task_execution_generation == request.execution_generation
        and fence.admission_contract_version == "2.2"
        and fence.admission_snapshot_id == request.admission_snapshot_id
        and fence.admission_snapshot_hash == arm.admission_snapshot_hash
        and lease_topology_matches
    )


def _current_fence_can_settle_tool_receipt(
    fence: DriverFence,
    receipt: GovernedToolRequestReceipt,
) -> bool:
    request = receipt.request
    arm = request.dispatch_arm
    lease_topology_matches = (
        fence.lease_epoch > arm.lease_epoch
        or (
            fence.lease_epoch == arm.lease_epoch
            and fence.lease_owner == arm.lease_owner
        )
    )
    return (
        fence.tenant_id == arm.tenant_id
        and fence.runtime_run_id == receipt.execution_id
        and fence.task_execution_generation == request.execution_generation
        and fence.admission_contract_version == "2.2"
        and fence.admission_snapshot_id == request.admission_snapshot_id
        and fence.admission_snapshot_hash == arm.admission_snapshot_hash
        and lease_topology_matches
    )


def _binding_matches_receipt(
    row: aiosqlite.Row,
    receipt: GovernedInitialModelRequestReceipt,
) -> bool:
    return (
        row["runtime_external_permit_id"]
        == str(receipt.runtime_external_permit_id)
        and row["arm_event_id"] == str(receipt.arm_event_id)
        and row["execution_id"] == str(receipt.execution_id)
        and row["call_index"] == 1
        and row["model_call_id"] == str(receipt.request.model_call_id)
        and row["request_hash"] == receipt.request.request_hash
        and row["lease_epoch"] == receipt.lease_epoch
        and row["body_sha256"] == receipt.body_sha256
    )


def _after_tool_binding_matches_receipt(
    row: aiosqlite.Row,
    receipt: GovernedAfterToolModelRequestReceipt,
) -> bool:
    return (
        row["runtime_external_permit_id"]
        == str(receipt.runtime_external_permit_id)
        and row["arm_event_id"] == str(receipt.arm_event_id)
        and row["execution_id"] == str(receipt.execution_id)
        and row["call_index"] == 2
        and row["model_call_id"] == str(receipt.request.model_call_id)
        and row["request_hash"] == receipt.request.request_hash
        and row["lease_epoch"] == receipt.lease_epoch
        and row["body_sha256"] == receipt.body_sha256
    )


def _tool_binding_matches_receipt(
    row: aiosqlite.Row,
    receipt: GovernedToolRequestReceipt,
) -> bool:
    request = receipt.request
    return (
        row["runtime_external_permit_id"]
        == str(receipt.runtime_external_permit_id)
        and row["arm_event_id"] == str(receipt.arm_event_id)
        and row["execution_id"] == str(receipt.execution_id)
        and row["tool_call_slot"] == 1
        and row["tool_invocation_id"] == str(request.tool_invocation_id)
        and row["source_model_call_id"] == str(request.source_model_call_id)
        and row["model_tool_selection_id"]
        == str(request.model_tool_selection_id)
        and row["request_hash"] == request.request_hash
        and row["lease_epoch"] == receipt.lease_epoch
        and row["body_sha256"] == receipt.body_sha256
    )


def _response_identity_matches_receipt(
    identity: Any,
    receipt: GovernedInitialModelRequestReceipt,
) -> bool:
    arm = receipt.request.dispatch_arm
    return (
        identity.runtime_external_permit_id == arm.runtime_external_permit_id
        and identity.lease_owner == arm.lease_owner
        and identity.lease_epoch == arm.lease_epoch
        and identity.arm_event_id == arm.arm_event_id
    )


def _after_tool_response_identity_matches_receipt(
    identity: Any,
    receipt: GovernedAfterToolModelRequestReceipt,
) -> bool:
    arm = receipt.request.dispatch_arm
    return (
        identity.runtime_external_permit_id == arm.runtime_external_permit_id
        and identity.lease_owner == arm.lease_owner
        and identity.lease_epoch == arm.lease_epoch
        and identity.arm_event_id == arm.arm_event_id
    )


def _tool_response_identity_matches_receipt(
    identity: Any,
    receipt: GovernedToolRequestReceipt,
) -> bool:
    arm = receipt.request.dispatch_arm
    return (
        identity.runtime_external_permit_id == arm.runtime_external_permit_id
        and identity.lease_owner == arm.lease_owner
        and identity.lease_epoch == arm.lease_epoch
        and identity.arm_event_id == arm.arm_event_id
    )


def _governed_tool_terminal_completion(
    response: GovernedToolCallResponse,
) -> dict[str, Any]:
    if response.disposition != "CANONICAL_OUTCOME_APPLIED":
        raise H12CausalFenceRejected(
            "governed Tool response is not a releasable terminal state"
        )
    fact = response.canonical_fact
    if fact is None or fact.outcome_status == "OUTCOME_UNKNOWN":
        raise H12CausalFenceRejected(
            "unknown governed Tool outcome requires manual reconciliation"
        )
    if response.action != "NONE":
        raise H12CausalFenceRejected(
            "determinate governed Tool response still requires reconciliation"
        )
    java_status = (
        "SUCCEEDED" if fact.outcome_status == "SUCCEEDED" else "FAILED_SAFE"
    )
    return {
        "java_status": java_status,
        "response_payload": {
            "contractVersion": "1.2",
            "disposition": response.disposition,
            "outcomeStatus": fact.outcome_status,
            "outcomeCode": fact.outcome_code,
        },
    }


def _governed_tool_terminal_evidence_values(
    execution_id: UUID,
    fence: DriverFence,
    response: GovernedToolCallResponse,
    persisted: GovernedToolRequestReceipt,
    attempted: GovernedToolRequestReceipt,
    response_payload_hash: str,
    completed_at: str,
) -> tuple[Any, ...]:
    fact = response.canonical_fact
    assert fact is not None
    persisted_dispatch = response.persisted_dispatch
    attempted_dispatch = response.attempted_dispatch
    return (
        str(execution_id),
        str(response.tool_invocation_id),
        str(persisted.request.source_model_call_id),
        str(persisted.request.model_tool_selection_id),
        response.request_hash,
        str(persisted_dispatch.runtime_external_permit_id),
        str(persisted_dispatch.arm_event_id),
        persisted_dispatch.lease_epoch,
        str(attempted_dispatch.runtime_external_permit_id),
        str(attempted_dispatch.arm_event_id),
        attempted_dispatch.lease_epoch,
        str(fact.outcome_event_id),
        fact.outcome_status,
        str(fact.source_fact_id),
        fact.source_fact_version,
        fact.source_fact_hash,
        fact.outcome_code,
        fact.result_hash,
        response_payload_hash,
        fence.lease_owner,
        fence.lease_epoch,
        completed_at,
    )


def _tool_terminal_evidence_matches(
    row: aiosqlite.Row,
    values: tuple[Any, ...],
) -> bool:
    columns = (
        "execution_id",
        "tool_invocation_id",
        "source_model_call_id",
        "model_tool_selection_id",
        "request_hash",
        "persisted_permit_id",
        "persisted_arm_event_id",
        "persisted_lease_epoch",
        "attempted_permit_id",
        "attempted_arm_event_id",
        "attempted_lease_epoch",
        "outcome_event_id",
        "outcome_status",
        "source_fact_id",
        "source_fact_version",
        "source_fact_hash",
        "outcome_code",
        "result_hash",
        "response_payload_hash",
        "accepted_by_lease_owner",
        "accepted_by_lease_epoch",
        "completed_at",
    )
    return all(
        row[column] == value
        for column, value in zip(columns[:-1], values[:-1])
    )


def _validate_governed_tool_terminal_evidence(
    evidence: GovernedToolTerminalEvidence,
) -> None:
    if (
        evidence.outcome_status
        not in {"NOT_DISPATCHED", "SUCCEEDED", "FAILED_CONFIRMED"}
        or evidence.source_fact_version < 1
        or len(evidence.source_fact_hash) != 64
        or not evidence.outcome_code
    ):
        raise H12IntentConflict(
            "governed Tool terminal evidence is inconsistent"
        )
    expected_status = (
        "SUCCEEDED" if evidence.outcome_status == "SUCCEEDED" else "FAILED_SAFE"
    )
    if evidence.java_status != expected_status:
        raise H12IntentConflict(
            "governed Tool fact differs from the local terminal status"
        )


def _governed_terminal_completion(
    response: GovernedInitialModelCallResponse,
) -> dict[str, Any]:
    if response.disposition == "FAILED_SAFE_BEFORE_ARM":
        if (
            response.model_call_status != "FAILED_SAFE"
            or response.action != "NONE"
            or response.persisted_dispatch != response.attempted_dispatch
            or response.canonical_fact is not None
            or response.terminal_result is not None
        ):
            raise H12CausalFenceRejected(
                "pre-arm failure response is not safe to finalize"
            )
        return {
            "completion_kind": "FAILED_SAFE_BEFORE_ARM",
            "java_status": "FAILED_SAFE",
            "outcome_kind": None,
            "model_tool_selection_id": None,
            "response_payload": {
                "contractVersion": "1.2",
                "disposition": response.disposition,
                "failureCode": response.failure_code,
            },
        }
    if response.disposition == "GOVERNED_TOOL_REQUIRED":
        fact = response.canonical_fact
        if (
            response.model_call_status != "RESPONSE_RECEIVED"
            or response.failure_code is not None
            or response.action != "WAIT_FOR_GOVERNED_TOOL_CHAIN"
            or response.terminal_result is not None
            or fact is None
            or fact.outcome_status != "SUCCEEDED"
        ):
            raise H12CausalFenceRejected(
                "governed Tool selection evidence is inconsistent"
            )
        selection_id = stable_model_tool_selection_id(response.model_call_id)
        return {
            "completion_kind": "CANONICAL_APPLIED",
            "java_status": "RESPONSE_RECEIVED",
            "outcome_kind": ModelOutcome.TOOL_SELECTION.value,
            "model_tool_selection_id": str(selection_id),
            "response_payload": {
                "contractVersion": "1.2",
                "disposition": response.disposition,
                "modelToolSelectionId": str(selection_id),
                "outcomeStatus": fact.outcome_status,
            },
        }
    if response.disposition != "CANONICAL_OUTCOME_APPLIED":
        raise H12CausalFenceRejected(
            "governed response has not reached a releasable terminal state"
        )
    fact = response.canonical_fact
    if fact is None or fact.outcome_status == "OUTCOME_UNKNOWN":
        raise H12CausalFenceRejected(
            "unknown canonical outcome requires manual reconciliation"
        )
    if response.action != "NONE":
        raise H12CausalFenceRejected(
            "determinate canonical response still requires reconciliation"
        )
    if fact.outcome_status == "NOT_DISPATCHED":
        if response.terminal_result is not None or response.model_call_status != "FAILED_SAFE":
            raise H12CausalFenceRejected(
                "zero-dispatch canonical response is inconsistent"
            )
        return {
            "completion_kind": "CANONICAL_APPLIED",
            "java_status": "FAILED_SAFE",
            "outcome_kind": None,
            "model_tool_selection_id": None,
            "response_payload": {
                "contractVersion": "1.2",
                "disposition": response.disposition,
                "failureCode": response.failure_code,
                "outcomeStatus": fact.outcome_status,
            },
        }
    result = response.terminal_result
    if result is None:
        raise H12CausalFenceRejected(
            "determinate canonical response does not contain a terminal result"
        )
    if fact.outcome_status == "SUCCEEDED":
        if (
            result.status != "RESPONSE_RECEIVED"
            or result.response_kind != "FINAL_TEXT"
            or response.model_call_status != result.status
        ):
            raise H12CausalFenceRejected(
                "successful canonical response is inconsistent"
            )
        outcome_kind = ModelOutcome.FINAL_TEXT.value
    elif fact.outcome_status == "FAILED_CONFIRMED":
        if (
            result.status != "RESPONSE_REJECTED"
            or result.response_kind != "RESPONSE_REJECTED"
            or response.model_call_status != result.status
        ):
            raise H12CausalFenceRejected(
                "confirmed failure canonical response is inconsistent"
            )
        outcome_kind = None
    else:
        raise H12CausalFenceRejected("unsupported governed canonical outcome")
    return {
        "completion_kind": "CANONICAL_APPLIED",
        "java_status": result.status,
        "outcome_kind": outcome_kind,
        "model_tool_selection_id": None,
        "response_payload": result.model_dump(mode="json", by_alias=True),
    }


def _governed_terminal_evidence_values(
    execution_id: UUID,
    fence: DriverFence,
    response: GovernedInitialModelCallResponse,
    completion_kind: str,
    response_payload_hash: str,
    completed_at: str,
) -> tuple[Any, ...]:
    persisted = response.persisted_dispatch
    attempted = response.attempted_dispatch
    fact = response.canonical_fact
    return (
        str(execution_id),
        str(response.model_call_id),
        response.request_hash,
        str(persisted.runtime_external_permit_id),
        str(persisted.arm_event_id),
        persisted.lease_epoch,
        str(attempted.runtime_external_permit_id),
        str(attempted.arm_event_id),
        attempted.lease_epoch,
        completion_kind,
        str(fact.outcome_event_id) if fact is not None else None,
        fact.outcome_status if fact is not None else None,
        str(fact.source_fact_id) if fact is not None else None,
        fact.source_fact_version if fact is not None else None,
        fact.source_fact_hash if fact is not None else None,
        fact.outcome_code if fact is not None else None,
        fact.result_hash if fact is not None else None,
        response_payload_hash,
        fence.lease_owner,
        fence.lease_epoch,
        completed_at,
    )


def _terminal_evidence_matches(
    row: aiosqlite.Row,
    values: tuple[Any, ...],
) -> bool:
    columns = (
        "execution_id",
        "model_call_id",
        "request_hash",
        "persisted_permit_id",
        "persisted_arm_event_id",
        "persisted_lease_epoch",
        "attempted_permit_id",
        "attempted_arm_event_id",
        "attempted_lease_epoch",
        "completion_kind",
        "outcome_event_id",
        "outcome_status",
        "source_fact_id",
        "source_fact_version",
        "source_fact_hash",
        "outcome_code",
        "result_hash",
        "response_payload_hash",
        "accepted_by_lease_owner",
        "accepted_by_lease_epoch",
        "completed_at",
    )
    # completed_at is local append time and is ignored for exact response replay.
    return all(row[column] == value for column, value in zip(columns[:-1], values[:-1]))


def _validate_governed_terminal_evidence(
    evidence: (
        GovernedInitialTerminalEvidence
        | GovernedAfterToolTerminalEvidence
    ),
) -> None:
    if evidence.completion_kind == "FAILED_SAFE_BEFORE_ARM":
        if (
            evidence.java_status != "FAILED_SAFE"
            or evidence.outcome_status is not None
            or evidence.source_fact_id is not None
            or evidence.source_fact_version is not None
            or evidence.source_fact_hash is not None
            or evidence.outcome_code is not None
        ):
            raise H12IntentConflict(
                "pre-arm terminal evidence contains a canonical outcome"
            )
        return
    if (
        evidence.completion_kind != "CANONICAL_APPLIED"
        or evidence.outcome_status
        not in {"NOT_DISPATCHED", "SUCCEEDED", "FAILED_CONFIRMED"}
        or evidence.source_fact_id is None
        or evidence.source_fact_version is None
        or evidence.source_fact_version < 1
        or evidence.source_fact_hash is None
        or evidence.outcome_code is None
    ):
        raise H12IntentConflict("canonical terminal evidence is inconsistent")
    expected_java_status = {
        "NOT_DISPATCHED": "FAILED_SAFE",
        "SUCCEEDED": "RESPONSE_RECEIVED",
        "FAILED_CONFIRMED": "RESPONSE_REJECTED",
    }[evidence.outcome_status]
    if evidence.java_status != expected_java_status:
        raise H12IntentConflict(
            "canonical terminal status differs from the local model result"
        )
    if isinstance(evidence, GovernedInitialTerminalEvidence):
        has_selection = evidence.outcome_kind == ModelOutcome.TOOL_SELECTION
        if has_selection != (evidence.model_tool_selection_id is not None):
            raise H12IntentConflict(
                "governed initial selection evidence is inconsistent"
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


def _require_non_nil_uuid(name: str, value: UUID) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{name} must be a UUID")
    if value.int == 0:
        raise ValueError(f"{name} must not be the nil UUID")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()

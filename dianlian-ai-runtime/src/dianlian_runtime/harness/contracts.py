from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class StartExecutionRequest:
    execution_id: str
    idempotency_key: str
    thread_id: str
    request_hash: str
    prompt: str


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    sequence: int
    event_type: str
    category: str
    content: str | dict[str, Any]


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    execution_id: str
    idempotency_key: str
    thread_id: str
    request_hash: str
    deerflow_run_id: str | None
    status: str
    checkpoint_id: str | None
    result: str | None
    cancel_action: str | None
    accepted_at: datetime
    updated_at: datetime

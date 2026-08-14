from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

from dianlian_runtime.harness.contracts import ExecutionEvent, ExecutionSnapshot


RUNTIME_CONTRACT_VERSION = "1.0"
SafeRuntimeId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,128}$"),
]
NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _RuntimeContract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class CreateExecutionRequest(_RuntimeContract):
    contract_version: Literal["1.0"]
    execution_id: SafeRuntimeId
    idempotency_key: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    ]
    thread_id: SafeRuntimeId
    execution_generation: int = Field(ge=1, le=2_147_483_647)
    tenant_id: UUID
    actor_user_id: UUID
    request_hash: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
    ]


class GuideExecutionRequest(_RuntimeContract):
    contract_version: Literal["1.0"]
    expected_checkpoint_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
    ]
    guidance: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=32_768),
    ]


class CancelAction(StrEnum):
    INTERRUPT = "interrupt"
    ROLLBACK = "rollback"


class CancelExecutionRequest(_RuntimeContract):
    contract_version: Literal["1.0"]
    action: CancelAction = CancelAction.INTERRUPT


class ExecutionSnapshotResponse(_RuntimeContract):
    contract_version: Literal["1.0"] = RUNTIME_CONTRACT_VERSION
    execution_id: str
    idempotency_key: str
    thread_id: str
    state: str
    checkpoint_id: str | None
    output: str | None
    cancel_action: str | None
    accepted_at: datetime
    updated_at: datetime
    production_takeover_enabled: Literal[False] = False

    @classmethod
    def from_snapshot(
        cls,
        snapshot: ExecutionSnapshot,
    ) -> "ExecutionSnapshotResponse":
        return cls(
            execution_id=snapshot.execution_id,
            idempotency_key=snapshot.idempotency_key,
            thread_id=snapshot.thread_id,
            state=snapshot.status,
            checkpoint_id=snapshot.checkpoint_id,
            output=snapshot.result,
            cancel_action=snapshot.cancel_action,
            accepted_at=snapshot.accepted_at,
            updated_at=snapshot.updated_at,
        )


class ExecutionEventResponse(_RuntimeContract):
    sequence: int = Field(ge=1)
    event_type: str
    category: str
    content: str | dict[str, Any]

    @classmethod
    def from_event(cls, event: ExecutionEvent) -> "ExecutionEventResponse":
        return cls(
            sequence=event.sequence,
            event_type=event.event_type,
            category=event.category,
            content=event.content,
        )


class ExecutionEventPageResponse(_RuntimeContract):
    contract_version: Literal["1.0"] = RUNTIME_CONTRACT_VERSION
    execution_id: str
    after_sequence: int = Field(ge=0)
    next_sequence: int = Field(ge=0)
    events: list[ExecutionEventResponse]


class RuntimeApiProblem(_RuntimeContract):
    code: str
    message: str

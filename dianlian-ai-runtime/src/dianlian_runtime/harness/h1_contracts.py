from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel


H1_CONTRACT_VERSIONS = ("2.0", "2.1", "2.2")
H1_RUNTIME_PROFILE = "DEERFLOW_H1_TEXT"
LowerSha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
BoundedKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
BoundedText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=60_000),
]


class _H1Contract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class ModelRouteSnapshot(_H1Contract):
    route_binding_id: UUID
    route_state_version: int = Field(ge=1)
    model_definition_id: UUID
    model_configuration_version: int = Field(ge=1)
    reservation_ceiling_micro_credit: int = Field(ge=1)


class PromptMessage(_H1Contract):
    role: Literal["HUMAN"]
    text: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=40_000),
    ]


class PromptSnapshot(_H1Contract):
    prompt_snapshot_id: UUID
    system_instruction: BoundedText
    messages: list[PromptMessage]
    hash: LowerSha256

    @model_validator(mode="after")
    def require_one_human_message(self) -> "PromptSnapshot":
        if len(self.messages) != 1:
            raise ValueError("H1 requires exactly one HUMAN message")
        return self


class ContextSnapshot(_H1Contract):
    context_snapshot_id: UUID
    mode: Literal["EMPTY", "FENCED"]
    hash: LowerSha256


class DenyAllToolPolicySnapshot(_H1Contract):
    tool_policy_snapshot_id: UUID
    allowed_tools: list[str]
    hash: LowerSha256

    @model_validator(mode="after")
    def deny_all_tools(self) -> "DenyAllToolPolicySnapshot":
        if self.allowed_tools:
            raise ValueError("H1 tool policy must deny all tools")
        return self


ToolKey = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z][A-Z0-9_.-]{1,127}$"),
]


class AllowedToolDefinition(_H1Contract):
    ordinal: int = Field(ge=1, le=32)
    tool_definition_id: UUID
    tool_key: ToolKey
    definition_version: int = Field(ge=1)
    side_effect_mode: Literal["NO_SIDE_EFFECT"]


class FrozenToolPolicySnapshot(_H1Contract):
    tool_policy_snapshot_id: UUID
    schema_version: Literal["runtime-tool-policy-v1"]
    mode: Literal["DENY_ALL", "ALLOW_LIST"]
    configuration_policy_id: UUID
    configuration_policy_hash: LowerSha256
    allowed_tools: list[AllowedToolDefinition] = Field(max_length=32)
    hash: LowerSha256

    @model_validator(mode="after")
    def validate_allowlist(self) -> "FrozenToolPolicySnapshot":
        if self.mode == "DENY_ALL" and self.allowed_tools:
            raise ValueError("DENY_ALL tool policy must not allow tools")
        if self.mode == "ALLOW_LIST" and not self.allowed_tools:
            raise ValueError("ALLOW_LIST tool policy must allow at least one tool")
        if [tool.ordinal for tool in self.allowed_tools] != list(
            range(1, len(self.allowed_tools) + 1)
        ):
            raise ValueError("allowedTools ordinals must be ordered from one")
        tool_keys = {tool.tool_key for tool in self.allowed_tools}
        definition_refs = {
            (tool.tool_definition_id, tool.definition_version)
            for tool in self.allowed_tools
        }
        if len(tool_keys) != len(self.allowed_tools) or len(definition_refs) != len(
            self.allowed_tools
        ):
            raise ValueError("allowedTools must contain unique keys and definitions")
        if self.hash != _runtime_tool_policy_hash(self):
            raise ValueError("tool policy hash does not match the frozen payload")
        return self


def _runtime_tool_policy_hash(policy: FrozenToolPolicySnapshot) -> str:
    tools = ",".join(
        (
            f'{{"ordinal":{tool.ordinal},'
            f'"toolDefinitionId":"{tool.tool_definition_id}",'
            f'"toolKey":"{tool.tool_key}",'
            f'"definitionVersion":{tool.definition_version},'
            '"sideEffectMode":"NO_SIDE_EFFECT"}'
        )
        for tool in policy.allowed_tools
    )
    canonical = (
        '{"schemaVersion":"runtime-tool-policy-v1",'
        f'"mode":"{policy.mode}",'
        f'"configurationPolicyId":"{policy.configuration_policy_id}",'
        f'"configurationPolicyHash":"{policy.configuration_policy_hash}",'
        f'"allowedTools":[{tools}]}}'
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CreateH1ExecutionRequest(_H1Contract):
    contract_version: Literal["2.0", "2.1"]
    runtime_profile: Literal["DEERFLOW_H1_TEXT"]
    execution_id: UUID
    task_id: UUID
    task_step_id: UUID
    execution_generation: int = Field(ge=1)
    admission_snapshot_id: UUID
    idempotency_key: BoundedKey
    request_hash: LowerSha256
    tenant_id: UUID
    actor_user_id: UUID
    input_snapshot_id: UUID
    enterprise_agent_id: UUID
    agent_version_id: UUID
    configuration_version_id: UUID
    point_reservation_id: UUID
    model_route: ModelRouteSnapshot
    prompt: PromptSnapshot
    context: ContextSnapshot
    tool_policy: DenyAllToolPolicySnapshot | FrozenToolPolicySnapshot
    snapshot_hash: LowerSha256

    @model_validator(mode="after")
    def require_versioned_tool_policy(self) -> "CreateH1ExecutionRequest":
        if self.contract_version == "2.0" and not isinstance(
            self.tool_policy, DenyAllToolPolicySnapshot
        ):
            raise ValueError("H1 2.0 requires the deny-all tool policy contract")
        if self.contract_version == "2.1" and not isinstance(
            self.tool_policy, FrozenToolPolicySnapshot
        ):
            raise ValueError("H1 2.1 requires the frozen tool policy contract")
        return self


class H1ExecutionSnapshot:
    def __init__(
        self,
        *,
        contract_version: str,
        execution_id: UUID,
        admission_snapshot_id: UUID,
        idempotency_key: str,
        state: str,
        output: str | None,
        failure_code: str | None,
        accepted_at: datetime,
        updated_at: datetime,
    ) -> None:
        if contract_version not in H1_CONTRACT_VERSIONS:
            raise ValueError("H1 contract version is unsupported")
        self.contract_version = contract_version
        self.execution_id = execution_id
        self.admission_snapshot_id = admission_snapshot_id
        self.idempotency_key = idempotency_key
        self.state = state
        self.output = output
        self.failure_code = failure_code
        self.accepted_at = accepted_at
        self.updated_at = updated_at


class H1ExecutionEvent:
    def __init__(
        self,
        sequence: int,
        event_type: str,
        category: str,
        content: dict[str, Any],
    ) -> None:
        self.sequence = sequence
        self.event_type = event_type
        self.category = category
        self.content = content


class H1ExecutionSnapshotResponse(_H1Contract):
    contract_version: Literal["2.0", "2.1", "2.2"]
    runtime_profile: Literal["DEERFLOW_H1_TEXT"] = H1_RUNTIME_PROFILE
    execution_id: UUID
    admission_snapshot_id: UUID
    idempotency_key: str
    state: Literal["CREATING", "RUNNING", "SUCCEEDED", "FAILED"]
    output: str | None
    failure_code: str | None
    accepted_at: datetime
    updated_at: datetime
    production_takeover_enabled: Literal[False] = False

    @classmethod
    def from_snapshot(
        cls,
        snapshot: H1ExecutionSnapshot,
    ) -> "H1ExecutionSnapshotResponse":
        return cls(
            contract_version=snapshot.contract_version,
            execution_id=snapshot.execution_id,
            admission_snapshot_id=snapshot.admission_snapshot_id,
            idempotency_key=snapshot.idempotency_key,
            state=snapshot.state,
            output=snapshot.output,
            failure_code=snapshot.failure_code,
            accepted_at=snapshot.accepted_at,
            updated_at=snapshot.updated_at,
        )


class H1ExecutionEventResponse(_H1Contract):
    sequence: int = Field(ge=1)
    event_type: str
    category: str
    content: dict[str, Any]

    @classmethod
    def from_event(cls, event: H1ExecutionEvent) -> "H1ExecutionEventResponse":
        return cls(
            sequence=event.sequence,
            event_type=event.event_type,
            category=event.category,
            content=event.content,
        )


class H1ExecutionEventPageResponse(_H1Contract):
    contract_version: Literal["2.0", "2.1", "2.2"]
    execution_id: UUID
    after_sequence: int = Field(ge=0)
    next_sequence: int = Field(ge=0)
    events: list[H1ExecutionEventResponse]

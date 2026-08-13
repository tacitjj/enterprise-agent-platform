from __future__ import annotations

import hashlib
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from dianlian_runtime.harness.h1_contracts import (
    BoundedKey,
    ContextSnapshot,
    FrozenToolPolicySnapshot,
    LowerSha256,
    ModelRouteSnapshot,
    PromptSnapshot,
)


H12_CONTRACT_VERSION = "2.2"
H12_RUNTIME_PROFILE = "DEERFLOW_H1_TEXT"
ORCHESTRATION_SCHEMA_VERSION = "runtime-orchestration-policy-v1"
OrchestrationHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class _H12Contract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


class FrozenOrchestrationPolicySnapshot(_H12Contract):
    orchestration_policy_snapshot_id: UUID
    schema_version: Literal["runtime-orchestration-policy-v1"]
    max_model_calls: Literal[2]
    max_tool_calls: Literal[1]
    model_call_reservation_ceiling: int = Field(ge=1)
    total_model_reservation_ceiling: int = Field(ge=2)
    hash: OrchestrationHash

    @model_validator(mode="after")
    def validate_frozen_policy(self) -> "FrozenOrchestrationPolicySnapshot":
        if self.total_model_reservation_ceiling != (
            self.model_call_reservation_ceiling * self.max_model_calls
        ):
            raise ValueError(
                "total model reservation ceiling must equal both model call ceilings"
            )
        if self.hash != runtime_orchestration_policy_hash(self):
            raise ValueError("orchestration policy hash does not match the frozen payload")
        return self


def runtime_orchestration_policy_hash(
    policy: FrozenOrchestrationPolicySnapshot,
) -> str:
    canonical = (
        '{"schemaVersion":"runtime-orchestration-policy-v1",'
        '"maxModelCalls":2,'
        '"maxToolCalls":1,'
        f'"modelCallReservationCeiling":{policy.model_call_reservation_ceiling},'
        f'"totalModelReservationCeiling":{policy.total_model_reservation_ceiling}}}'
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CreateH12ExecutionRequest(_H12Contract):
    contract_version: Literal["2.2"]
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
    tool_policy: FrozenToolPolicySnapshot
    orchestration_policy: FrozenOrchestrationPolicySnapshot
    snapshot_hash: LowerSha256

    @model_validator(mode="after")
    def require_model_selected_tool_loop(self) -> "CreateH12ExecutionRequest":
        if self.tool_policy.mode != "ALLOW_LIST":
            raise ValueError("H1 2.2 requires a non-empty frozen tool allowlist")
        if (
            self.model_route.reservation_ceiling_micro_credit
            != self.orchestration_policy.model_call_reservation_ceiling
        ):
            raise ValueError(
                "model route ceiling must match the orchestration call ceiling"
            )
        return self

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from dianlian_runtime.harness.admission_manifest import (
    JavaAdmissionManifest,
    NonNilUuid,
)
from dianlian_runtime.harness.h1_contracts import BoundedKey
from dianlian_runtime.harness.h12_durable import stable_model_call_id


class GovernedInitialModelIntent(BaseModel):
    """INITIAL model-call 1.2 logical intent before any Permit is attached."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=False,
        validate_by_alias=True,
        validate_by_name=False,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    contract_version: Literal["1.2"] = "1.2"
    model_call_id: NonNilUuid
    call_index: Literal[1] = 1
    call_phase: Literal["INITIAL"] = "INITIAL"
    execution_generation: int = Field(ge=1)
    idempotency_key: BoundedKey
    admission_snapshot_id: NonNilUuid
    prompt_snapshot_id: NonNilUuid
    context_snapshot_id: NonNilUuid
    tool_policy_snapshot_id: NonNilUuid
    orchestration_policy_snapshot_id: NonNilUuid
    model_route_binding_id: NonNilUuid
    model_route_state_version: int = Field(ge=1)
    model_definition_id: NonNilUuid
    model_configuration_version: int = Field(ge=1)

    def durable_payload(self) -> dict[str, object]:
        """Return the exact camelCase payload whose canonical hash identifies the intent."""

        return self.model_dump(mode="json", by_alias=True)


class GovernedAfterToolModelIntent(BaseModel):
    """AFTER_TOOL model-call 1.2 logical intent before a Permit is attached."""

    model_config = GovernedInitialModelIntent.model_config

    contract_version: Literal["1.2"] = "1.2"
    model_call_id: NonNilUuid
    call_index: Literal[2] = 2
    call_phase: Literal["AFTER_TOOL"] = "AFTER_TOOL"
    execution_generation: int = Field(ge=1)
    idempotency_key: BoundedKey
    admission_snapshot_id: NonNilUuid
    prompt_snapshot_id: NonNilUuid
    context_snapshot_id: NonNilUuid
    tool_policy_snapshot_id: NonNilUuid
    orchestration_policy_snapshot_id: NonNilUuid
    model_route_binding_id: NonNilUuid
    model_route_state_version: int = Field(ge=1)
    model_definition_id: NonNilUuid
    model_configuration_version: int = Field(ge=1)

    def durable_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True)


def build_governed_initial_model_intent(
    manifest: JavaAdmissionManifest,
) -> GovernedInitialModelIntent:
    """Build the stable INITIAL intent from opaque Java admission receipts only."""

    if not isinstance(manifest, JavaAdmissionManifest):
        raise TypeError("manifest must be a JavaAdmissionManifest")
    return GovernedInitialModelIntent.model_validate(
        {
            "contractVersion": "1.2",
            "modelCallId": stable_model_call_id(manifest.runtime_run_id, 1),
            "callIndex": 1,
            "callPhase": "INITIAL",
            "executionGeneration": manifest.execution_generation,
            "idempotencyKey": f"h12:{manifest.runtime_run_id}:model:1",
            "admissionSnapshotId": manifest.admission_snapshot_id,
            "promptSnapshotId": manifest.prompt.prompt_snapshot_id,
            "contextSnapshotId": manifest.context.context_snapshot_id,
            "toolPolicySnapshotId": manifest.tool_policy.tool_policy_snapshot_id,
            "orchestrationPolicySnapshotId": (
                manifest.orchestration_policy.orchestration_policy_snapshot_id
            ),
            "modelRouteBindingId": manifest.model_route.route_binding_id,
            "modelRouteStateVersion": manifest.model_route.route_state_version,
            "modelDefinitionId": manifest.model_route.model_definition_id,
            "modelConfigurationVersion": (
                manifest.model_route.model_configuration_version
            ),
        },
        strict=True,
    )


def build_governed_after_tool_model_intent(
    manifest: JavaAdmissionManifest,
) -> GovernedAfterToolModelIntent:
    """Build call two from the same frozen admission receipts as call one."""

    if not isinstance(manifest, JavaAdmissionManifest):
        raise TypeError("manifest must be a JavaAdmissionManifest")
    return GovernedAfterToolModelIntent.model_validate(
        {
            "contractVersion": "1.2",
            "modelCallId": stable_model_call_id(manifest.runtime_run_id, 2),
            "callIndex": 2,
            "callPhase": "AFTER_TOOL",
            "executionGeneration": manifest.execution_generation,
            "idempotencyKey": f"h12:{manifest.runtime_run_id}:model:2",
            "admissionSnapshotId": manifest.admission_snapshot_id,
            "promptSnapshotId": manifest.prompt.prompt_snapshot_id,
            "contextSnapshotId": manifest.context.context_snapshot_id,
            "toolPolicySnapshotId": manifest.tool_policy.tool_policy_snapshot_id,
            "orchestrationPolicySnapshotId": (
                manifest.orchestration_policy.orchestration_policy_snapshot_id
            ),
            "modelRouteBindingId": manifest.model_route.route_binding_id,
            "modelRouteStateVersion": manifest.model_route.route_state_version,
            "modelDefinitionId": manifest.model_route.model_definition_id,
            "modelConfigurationVersion": (
                manifest.model_route.model_configuration_version
            ),
        },
        strict=True,
    )

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from dianlian_runtime.harness.admission_manifest import NonNilUuid
from dianlian_runtime.harness.h1_contracts import BoundedKey, LowerSha256
from dianlian_runtime.harness.h12_durable import (
    canonical_intent,
    stable_model_call_id,
    stable_tool_call_id,
)
from dianlian_runtime.supervisor.contracts import ExternalOperation
from dianlian_runtime.supervisor.tool_permit_issuer import ToolPermitReceipt


LeaseOwner = Annotated[
    str,
    StringConstraints(strip_whitespace=False, min_length=1, max_length=160),
]


class _StrictContract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=False,
        validate_by_alias=True,
        validate_by_name=False,
        extra="forbid",
        frozen=True,
        strict=True,
    )


class GovernedToolIntent(_StrictContract):
    """Stable H12 Tool intent; no Permit, lease or transport metadata."""

    contract_version: Literal["1.2"] = "1.2"
    selection_mode: Literal["MODEL_SELECTED"] = "MODEL_SELECTED"
    tool_invocation_id: NonNilUuid
    source_model_call_id: NonNilUuid
    execution_generation: int = Field(ge=1)
    admission_snapshot_id: NonNilUuid
    tool_policy_snapshot_id: NonNilUuid
    model_tool_selection_id: NonNilUuid
    tool_call_slot: Literal[1] = 1
    idempotency_key: BoundedKey

    def durable_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True)


class GovernedToolDispatchArmEnvelope(_StrictContract):
    tenant_id: NonNilUuid
    runtime_external_permit_id: NonNilUuid
    lease_owner: LeaseOwner
    lease_epoch: int = Field(ge=1)
    admission_snapshot_hash: LowerSha256
    arm_event_id: NonNilUuid

    @model_validator(mode="after")
    def reject_padded_owner(self) -> "GovernedToolDispatchArmEnvelope":
        if self.lease_owner != self.lease_owner.strip():
            raise ValueError("leaseOwner must not contain surrounding whitespace")
        return self


class GovernedToolCallRequest(_StrictContract):
    contract_version: Literal["1.2"] = "1.2"
    selection_mode: Literal["MODEL_SELECTED"] = "MODEL_SELECTED"
    tool_invocation_id: NonNilUuid
    source_model_call_id: NonNilUuid
    execution_generation: int = Field(ge=1)
    admission_snapshot_id: NonNilUuid
    tool_policy_snapshot_id: NonNilUuid
    model_tool_selection_id: NonNilUuid
    tool_call_slot: Literal[1] = 1
    idempotency_key: BoundedKey
    request_hash: LowerSha256
    dispatch_arm: GovernedToolDispatchArmEnvelope

    @model_validator(mode="after")
    def validate_logical_hash(self) -> "GovernedToolCallRequest":
        GovernedToolIntent.model_validate(
            self.model_dump(
                mode="python",
                by_alias=True,
                exclude={"request_hash", "dispatch_arm"},
            ),
            strict=True,
        )
        _, expected = canonical_intent(self.logical_payload())
        if self.request_hash != expected:
            raise ValueError("requestHash does not match the logical Tool intent")
        return self

    def logical_payload(self) -> dict[str, object]:
        return self.model_dump(
            mode="json",
            by_alias=True,
            exclude={"request_hash", "dispatch_arm"},
        )

    def exact_body(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class GovernedToolRequestReceipt:
    """Exact dormant Tool request history; never an authorization by itself."""

    execution_id: UUID
    request: GovernedToolCallRequest
    exact_body: bytes
    body_sha256: str

    def __post_init__(self) -> None:
        _require_uuid("execution_id", self.execution_id)
        if not isinstance(self.request, GovernedToolCallRequest):
            raise TypeError("request must be a GovernedToolCallRequest")
        if self.request.tool_invocation_id != stable_tool_call_id(self.execution_id):
            raise ValueError("toolInvocationId does not match the path execution id")
        if self.request.source_model_call_id != stable_model_call_id(
            self.execution_id,
            1,
        ):
            raise ValueError("sourceModelCallId does not match INITIAL model call")
        if not isinstance(self.exact_body, bytes):
            raise TypeError("exact_body must be bytes")
        if self.exact_body != self.request.exact_body():
            raise ValueError("exact_body is not the canonical Tool request body")
        if self.body_sha256 != hashlib.sha256(self.exact_body).hexdigest():
            raise ValueError("body_sha256 does not match exact_body")

    @classmethod
    def create(
        cls,
        execution_id: UUID,
        intent: GovernedToolIntent,
        permit: ToolPermitReceipt,
    ) -> "GovernedToolRequestReceipt":
        _require_uuid("execution_id", execution_id)
        if not isinstance(intent, GovernedToolIntent):
            raise TypeError("intent must be a GovernedToolIntent")
        if not isinstance(permit, ToolPermitReceipt):
            raise TypeError("permit must be a ToolPermitReceipt")
        _, request_hash = canonical_intent(intent.durable_payload())
        if (
            intent.tool_invocation_id != stable_tool_call_id(execution_id)
            or intent.source_model_call_id != stable_model_call_id(execution_id, 1)
            or permit.operation_kind != ExternalOperation.TOOL_INVOKE
            or permit.runtime_run_id != execution_id
            or permit.intent_id != intent.tool_invocation_id
            or permit.task_execution_generation != intent.execution_generation
            or permit.admission_snapshot_id != intent.admission_snapshot_id
            or permit.request_hash != request_hash
        ):
            raise ValueError("Tool intent, path and permit receipt do not match")
        request = GovernedToolCallRequest.model_validate(
            {
                **intent.model_dump(mode="python", by_alias=True),
                "requestHash": request_hash,
                "dispatchArm": {
                    "tenantId": permit.tenant_id,
                    "runtimeExternalPermitId": permit.runtime_external_permit_id,
                    "leaseOwner": permit.lease_owner,
                    "leaseEpoch": permit.lease_epoch,
                    "admissionSnapshotHash": permit.admission_snapshot_hash,
                    "armEventId": permit.arm_event_id,
                },
            },
            strict=True,
        )
        body = request.exact_body()
        return cls(
            execution_id,
            request,
            body,
            hashlib.sha256(body).hexdigest(),
        )

    @classmethod
    def restore(
        cls,
        execution_id: UUID,
        exact_body: bytes,
        body_sha256: str,
    ) -> "GovernedToolRequestReceipt":
        _reject_duplicate_json_keys(exact_body)
        request = GovernedToolCallRequest.model_validate_json(
            exact_body,
            strict=True,
        )
        return cls(execution_id, request, exact_body, body_sha256)

    @property
    def runtime_external_permit_id(self) -> UUID:
        return self.request.dispatch_arm.runtime_external_permit_id

    @property
    def arm_event_id(self) -> UUID:
        return self.request.dispatch_arm.arm_event_id

    @property
    def lease_epoch(self) -> int:
        return self.request.dispatch_arm.lease_epoch


def _reject_duplicate_json_keys(value: bytes) -> None:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, nested in pairs:
            if key in result:
                raise ValueError("exact Tool request body contains a duplicate key")
            result[key] = nested
        return result

    json.loads(value, object_pairs_hook=reject)


def _require_uuid(name: str, value: UUID) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{name} must be a UUID")
    if value.int == 0:
        raise ValueError(f"{name} must not be the nil UUID")

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel

from dianlian_runtime.harness.admission_manifest import NonNilUuid
from dianlian_runtime.harness.governed_model_intent import (
    GovernedAfterToolModelIntent,
    GovernedInitialModelIntent,
)
from dianlian_runtime.harness.h1_contracts import BoundedKey, LowerSha256
from dianlian_runtime.harness.h12_durable import (
    canonical_intent,
    stable_model_call_id,
)
from dianlian_runtime.supervisor.contracts import ExternalOperation
from dianlian_runtime.supervisor.model_permit_issuer import ModelPermitReceipt


LeaseOwner = Annotated[
    str,
    StringConstraints(strip_whitespace=False, min_length=1, max_length=160),
]


class GovernedModelDispatchArmEnvelope(BaseModel):
    """Only the six Arm claims that Java cannot derive from path and intent."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=False,
        validate_by_alias=True,
        validate_by_name=False,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    tenant_id: NonNilUuid
    runtime_external_permit_id: NonNilUuid
    lease_owner: LeaseOwner
    lease_epoch: int = Field(ge=1)
    admission_snapshot_hash: LowerSha256
    arm_event_id: NonNilUuid

    @model_validator(mode="after")
    def reject_padded_owner(self) -> "GovernedModelDispatchArmEnvelope":
        if self.lease_owner != self.lease_owner.strip():
            raise ValueError("leaseOwner must not contain surrounding whitespace")
        return self


class GovernedInitialModelCallRequest(BaseModel):
    """Frozen model-call 1.2 body; the execution id remains in the HTTP path."""

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
    request_hash: LowerSha256
    dispatch_arm: GovernedModelDispatchArmEnvelope

    @model_validator(mode="after")
    def validate_frozen_initial_intent(self) -> "GovernedInitialModelCallRequest":
        # Validate through the existing strict logical contract so the receipt cannot
        # silently widen the public model intent.
        GovernedInitialModelIntent.model_validate(
            self.model_dump(
                mode="python",
                by_alias=True,
                exclude={"request_hash", "dispatch_arm"},
            ),
            strict=True,
        )
        _, expected_hash = canonical_intent(self.logical_payload())
        if self.request_hash != expected_hash:
            raise ValueError("requestHash does not match the logical model intent")
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
class GovernedInitialModelRequestReceipt:
    """Exact dormant HTTP request evidence; it never grants permission to POST."""

    execution_id: UUID
    request: GovernedInitialModelCallRequest
    exact_body: bytes
    body_sha256: str

    def __post_init__(self) -> None:
        _require_uuid("execution_id", self.execution_id)
        if not isinstance(self.request, GovernedInitialModelCallRequest):
            raise TypeError("request must be a GovernedInitialModelCallRequest")
        if self.request.model_call_id != stable_model_call_id(self.execution_id, 1):
            raise ValueError("modelCallId does not match the path execution id")
        if not isinstance(self.exact_body, bytes):
            raise TypeError("exact_body must be bytes")
        if self.exact_body != self.request.exact_body():
            raise ValueError("exact_body is not the canonical request body")
        expected_digest = hashlib.sha256(self.exact_body).hexdigest()
        if self.body_sha256 != expected_digest:
            raise ValueError("body_sha256 does not match exact_body")

    @classmethod
    def create(
        cls,
        execution_id: UUID,
        intent: GovernedInitialModelIntent,
        permit: ModelPermitReceipt,
    ) -> "GovernedInitialModelRequestReceipt":
        _require_uuid("execution_id", execution_id)
        if not isinstance(intent, GovernedInitialModelIntent):
            raise TypeError("intent must be a GovernedInitialModelIntent")
        if not isinstance(permit, ModelPermitReceipt):
            raise TypeError("permit must be a ModelPermitReceipt")
        _, request_hash = canonical_intent(intent.durable_payload())
        if intent.model_call_id != stable_model_call_id(execution_id, 1):
            raise ValueError("modelCallId does not match the path execution id")
        if (
            permit.runtime_run_id != execution_id
            or permit.operation_kind != ExternalOperation.MODEL_INVOKE
            or permit.intent_id != intent.model_call_id
            or permit.task_execution_generation != intent.execution_generation
            or permit.admission_snapshot_id != intent.admission_snapshot_id
            or permit.request_hash != request_hash
        ):
            raise ValueError("model intent, path and permit receipt do not match")
        request = GovernedInitialModelCallRequest.model_validate(
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
        exact_body = request.exact_body()
        return cls(
            execution_id=execution_id,
            request=request,
            exact_body=exact_body,
            body_sha256=hashlib.sha256(exact_body).hexdigest(),
        )

    @classmethod
    def restore(
        cls,
        execution_id: UUID,
        exact_body: bytes,
        body_sha256: str,
    ) -> "GovernedInitialModelRequestReceipt":
        _reject_duplicate_json_keys(exact_body)
        request = GovernedInitialModelCallRequest.model_validate_json(
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


class GovernedAfterToolModelCallRequest(BaseModel):
    """Frozen AFTER_TOOL model-call body for the dedicated call-two endpoint."""

    model_config = GovernedInitialModelCallRequest.model_config

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
    request_hash: LowerSha256
    dispatch_arm: GovernedModelDispatchArmEnvelope

    @model_validator(mode="after")
    def validate_frozen_after_tool_intent(
        self,
    ) -> "GovernedAfterToolModelCallRequest":
        GovernedAfterToolModelIntent.model_validate(
            self.model_dump(
                mode="python",
                by_alias=True,
                exclude={"request_hash", "dispatch_arm"},
            ),
            strict=True,
        )
        _, expected_hash = canonical_intent(self.logical_payload())
        if self.request_hash != expected_hash:
            raise ValueError("requestHash does not match the logical model intent")
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
class GovernedAfterToolModelRequestReceipt:
    """Exact call-two request history; it never grants permission to POST."""

    execution_id: UUID
    request: GovernedAfterToolModelCallRequest
    exact_body: bytes
    body_sha256: str

    def __post_init__(self) -> None:
        _require_uuid("execution_id", self.execution_id)
        if not isinstance(self.request, GovernedAfterToolModelCallRequest):
            raise TypeError("request must be a GovernedAfterToolModelCallRequest")
        if self.request.model_call_id != stable_model_call_id(self.execution_id, 2):
            raise ValueError("modelCallId does not match the path execution id")
        if not isinstance(self.exact_body, bytes):
            raise TypeError("exact_body must be bytes")
        if self.exact_body != self.request.exact_body():
            raise ValueError("exact_body is not the canonical request body")
        if self.body_sha256 != hashlib.sha256(self.exact_body).hexdigest():
            raise ValueError("body_sha256 does not match exact_body")

    @classmethod
    def create(
        cls,
        execution_id: UUID,
        intent: GovernedAfterToolModelIntent,
        permit: ModelPermitReceipt,
    ) -> "GovernedAfterToolModelRequestReceipt":
        _require_uuid("execution_id", execution_id)
        if not isinstance(intent, GovernedAfterToolModelIntent):
            raise TypeError("intent must be a GovernedAfterToolModelIntent")
        if not isinstance(permit, ModelPermitReceipt):
            raise TypeError("permit must be a ModelPermitReceipt")
        _, request_hash = canonical_intent(intent.durable_payload())
        if (
            intent.model_call_id != stable_model_call_id(execution_id, 2)
            or permit.runtime_run_id != execution_id
            or permit.operation_kind != ExternalOperation.MODEL_INVOKE
            or permit.intent_id != intent.model_call_id
            or permit.task_execution_generation != intent.execution_generation
            or permit.admission_snapshot_id != intent.admission_snapshot_id
            or permit.request_hash != request_hash
        ):
            raise ValueError("model intent, path and permit receipt do not match")
        request = GovernedAfterToolModelCallRequest.model_validate(
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
        exact_body = request.exact_body()
        return cls(
            execution_id,
            request,
            exact_body,
            hashlib.sha256(exact_body).hexdigest(),
        )

    @classmethod
    def restore(
        cls,
        execution_id: UUID,
        exact_body: bytes,
        body_sha256: str,
    ) -> "GovernedAfterToolModelRequestReceipt":
        _reject_duplicate_json_keys(exact_body)
        request = GovernedAfterToolModelCallRequest.model_validate_json(
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
                raise ValueError("exact request body contains a duplicate key")
            result[key] = nested
        return result

    json.loads(value, object_pairs_hook=reject)


def _require_uuid(name: str, value: UUID) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{name} must be a UUID")
    if value.int == 0:
        raise ValueError(f"{name} must not be the nil UUID")

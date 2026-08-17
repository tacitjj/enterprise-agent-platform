from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.alias_generators import to_camel

from dianlian_runtime.harness.structured_admission_manifest import (
    JAVA_LONG_MAX,
    JavaCapabilityStructuredAdmissionManifest,
    LowerSha256,
    NonNilUuid,
)
from dianlian_runtime.supervisor.contracts import ExternalOperation
from dianlian_runtime.supervisor.model_permit_issuer import ModelPermitReceipt


STRUCTURED_MODEL_CALL_CONTRACT_VERSION = "1.0"
STRUCTURED_MODEL_CALL_PHASE = "CAPABILITY_STRUCTURED"
MAX_STRUCTURED_MODEL_REQUEST_BYTES = 512 * 1024
_INTENT_SCHEMA_VERSION = "runtime-structured-model-intent-v1"

LeaseOwner = Annotated[
    str,
    StringConstraints(strip_whitespace=False, min_length=1, max_length=160),
]


class _StructuredModelWireContract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=False,
        validate_by_alias=True,
        validate_by_name=False,
        extra="forbid",
        frozen=True,
        strict=True,
    )


class StructuredDispatchArmEnvelope(_StructuredModelWireContract):
    """Java 无法从 Admission 与稳定模型意图派生的四项 Arm 信封。"""

    runtime_external_permit_id: NonNilUuid
    lease_owner: LeaseOwner
    lease_epoch: int = Field(ge=1, le=JAVA_LONG_MAX)
    arm_event_id: NonNilUuid

    @model_validator(mode="after")
    def reject_padded_owner(self) -> "StructuredDispatchArmEnvelope":
        if self.lease_owner != self.lease_owner.strip():
            raise ValueError("leaseOwner must not contain surrounding whitespace")
        return self


class StructuredModelCallRequest(_StructuredModelWireContract):
    """结构化 OneCall 的 exact Java 请求；不携带 Provider 配置或结果正文。"""

    contract_version: Literal["1.0"] = "1.0"
    model_call_id: NonNilUuid
    idempotency_key: Annotated[
        str,
        StringConstraints(strip_whitespace=False, min_length=1, max_length=200),
    ]
    model_request_hash: LowerSha256
    admission: JavaCapabilityStructuredAdmissionManifest
    dispatch_arm: StructuredDispatchArmEnvelope

    @model_validator(mode="after")
    def validate_stable_identity(self) -> "StructuredModelCallRequest":
        execution_id = self.admission.runtime_run_id
        if self.idempotency_key != self.idempotency_key.strip():
            raise ValueError("idempotencyKey must not contain surrounding whitespace")
        if self.model_call_id != stable_structured_model_call_id(execution_id):
            raise ValueError("modelCallId does not match the execution")
        if self.idempotency_key != structured_model_idempotency_key(execution_id):
            raise ValueError("idempotencyKey does not match the execution")
        expected_hash = structured_model_request_hash(
            execution_id,
            self.admission.admission_snapshot_id,
            self.admission.admission_snapshot_hash,
        )
        if self.model_request_hash != expected_hash:
            raise ValueError("modelRequestHash does not match the logical intent")
        return self

    def exact_body(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json", by_alias=True),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class StructuredModelRequestReceipt:
    """可持久化的 exact request 历史；Receipt 本身不授予再次 POST 权限。"""

    execution_id: UUID
    request: StructuredModelCallRequest
    exact_body: bytes
    body_sha256: str

    def __post_init__(self) -> None:
        _require_uuid("execution_id", self.execution_id)
        if not isinstance(self.request, StructuredModelCallRequest):
            raise TypeError("request must be a StructuredModelCallRequest")
        if self.request.admission.runtime_run_id != self.execution_id:
            raise ValueError("request Admission does not match the execution path")
        if not isinstance(self.exact_body, bytes):
            raise TypeError("exact_body must be bytes")
        if len(self.exact_body) > MAX_STRUCTURED_MODEL_REQUEST_BYTES:
            raise ValueError("structured model request exceeds the Java request limit")
        if self.exact_body != self.request.exact_body():
            raise ValueError("exact_body is not the canonical request body")
        expected = hashlib.sha256(self.exact_body).hexdigest()
        if self.body_sha256 != expected:
            raise ValueError("body_sha256 does not match exact_body")

    @classmethod
    def create(
        cls,
        execution_id: UUID,
        admission: JavaCapabilityStructuredAdmissionManifest,
        permit: ModelPermitReceipt,
    ) -> "StructuredModelRequestReceipt":
        _require_uuid("execution_id", execution_id)
        if not isinstance(admission, JavaCapabilityStructuredAdmissionManifest):
            raise TypeError(
                "admission must be a JavaCapabilityStructuredAdmissionManifest"
            )
        if not isinstance(permit, ModelPermitReceipt):
            raise TypeError("permit must be a ModelPermitReceipt")
        model_call_id = stable_structured_model_call_id(execution_id)
        request_hash = structured_model_request_hash(
            execution_id,
            admission.admission_snapshot_id,
            admission.admission_snapshot_hash,
        )
        if (
            admission.runtime_run_id != execution_id
            or permit.tenant_id != admission.tenant_id
            or permit.runtime_run_id != execution_id
            or permit.task_execution_generation != admission.execution_generation
            or permit.admission_snapshot_id != admission.admission_snapshot_id
            or permit.admission_snapshot_hash != admission.admission_snapshot_hash
            or permit.operation_kind != ExternalOperation.MODEL_INVOKE
            or permit.intent_id != model_call_id
            or permit.request_hash != request_hash
        ):
            raise ValueError("Admission, execution and model permit do not match")
        request = StructuredModelCallRequest.model_validate(
            {
                "contractVersion": STRUCTURED_MODEL_CALL_CONTRACT_VERSION,
                "modelCallId": model_call_id,
                "idempotencyKey": structured_model_idempotency_key(execution_id),
                "modelRequestHash": request_hash,
                "admission": admission.model_dump(mode="python", by_alias=True),
                "dispatchArm": {
                    "runtimeExternalPermitId": permit.runtime_external_permit_id,
                    "leaseOwner": permit.lease_owner,
                    "leaseEpoch": permit.lease_epoch,
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
    ) -> "StructuredModelRequestReceipt":
        reject_duplicate_json_keys(exact_body)
        request = StructuredModelCallRequest.model_validate_json(
            exact_body,
            strict=True,
        )
        return cls(execution_id, request, exact_body, body_sha256)


def stable_structured_model_call_id(execution_id: UUID) -> UUID:
    """与 Java RuntimeStructuredModelCallContract 相同的用途隔离 UUIDv5。"""

    _require_uuid("execution_id", execution_id)
    return uuid5(NAMESPACE_URL, f"dianlian:structured:{execution_id}:model-call:1")


def structured_model_idempotency_key(execution_id: UUID) -> str:
    return f"structured-model-call:{stable_structured_model_call_id(execution_id)}"


def structured_model_request_hash(
    execution_id: UUID,
    admission_snapshot_id: UUID,
    admission_snapshot_hash: str,
) -> str:
    """计算不含 Permit/lease/Arm 的稳定结构化模型业务意图哈希。"""

    _require_uuid("execution_id", execution_id)
    _require_uuid("admission_snapshot_id", admission_snapshot_id)
    if (
        not isinstance(admission_snapshot_hash, str)
        or len(admission_snapshot_hash) != 64
        or any(character not in "0123456789abcdef" for character in admission_snapshot_hash)
    ):
        raise ValueError("admission_snapshot_hash must be a lowercase SHA-256")
    model_call_id = stable_structured_model_call_id(execution_id)
    payload = {
        "admissionSnapshotHash": admission_snapshot_hash,
        "admissionSnapshotId": str(admission_snapshot_id),
        "callIndex": 1,
        "callPhase": STRUCTURED_MODEL_CALL_PHASE,
        "contractVersion": STRUCTURED_MODEL_CALL_CONTRACT_VERSION,
        "executionId": str(execution_id),
        "idempotencyKey": structured_model_idempotency_key(execution_id),
        "modelCallId": str(model_call_id),
        "schemaVersion": _INTENT_SCHEMA_VERSION,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def reject_duplicate_json_keys(payload: bytes) -> None:
    """拒绝任何层级的重复 JSON key，避免代理与 Java 对同一请求解释不同。"""

    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")

    def pairs_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    json.loads(payload, object_pairs_hook=pairs_hook)


def _require_uuid(name: str, value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError(f"{name} must be a non-nil UUID")

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)
from pydantic.alias_generators import to_camel


# Java wire contract 中对应字段均为 long，Python 不得接受 Java 无法反序列化的整数。
JAVA_LONG_MAX = 9_223_372_036_854_775_807


def _require_non_nil_uuid(value: UUID) -> UUID:
    if value.int == 0:
        raise ValueError("UUID must not be the nil UUID")
    return value


NonNilUuid = Annotated[UUID, AfterValidator(_require_non_nil_uuid)]
LowerSha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
TrimmedText64 = Annotated[
    str,
    StringConstraints(strip_whitespace=False, min_length=1, max_length=64),
]
UpperStableCode = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z][A-Z0-9._-]{0,63}$"),
]
UpperContractCode = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z][A-Z0-9_.-]{1,127}$"),
]
LowerSchemaId = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{1,127}$"),
]


class _StructuredAdmissionContract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=False,
        validate_by_alias=True,
        validate_by_name=False,
        extra="forbid",
        frozen=True,
        strict=True,
    )


class CapabilityPackVersionReference(_StructuredAdmissionContract):
    pack_code: UpperContractCode
    pack_version: TrimmedText64
    manifest_hash: LowerSha256

    @model_validator(mode="after")
    def validate_text(self) -> "CapabilityPackVersionReference":
        _require_trimmed("packVersion", self.pack_version)
        return self


class CapabilityPackContractReference(_StructuredAdmissionContract):
    kind: Literal[
        "INPUT_SCHEMA",
        "OUTPUT_SCHEMA",
        "RULE_SET",
        "MODEL_RESPONSE_SCHEMA",
    ]
    contract_code: UpperContractCode
    version: TrimmedText64
    contract_hash: LowerSha256

    @model_validator(mode="after")
    def validate_text(self) -> "CapabilityPackContractReference":
        _require_trimmed("version", self.version)
        return self


class ExecutionModelRequirement(_StructuredAdmissionContract):
    required_capability_codes: list[UpperStableCode] = Field(min_length=1, max_length=16)
    required_feature_codes: list[UpperStableCode] = Field(min_length=1, max_length=32)
    response_contract_code: LowerSchemaId
    response_contract_version: Annotated[
        str,
        StringConstraints(strip_whitespace=False, min_length=1, max_length=32),
    ]

    @model_validator(mode="after")
    def validate_requirement(self) -> "ExecutionModelRequirement":
        _require_sorted_unique(
            "requiredCapabilityCodes", self.required_capability_codes
        )
        _require_sorted_unique("requiredFeatureCodes", self.required_feature_codes)
        if "JSON_SCHEMA_STRUCTURED_OUTPUT" not in self.required_feature_codes:
            raise ValueError(
                "requiredFeatureCodes must include JSON_SCHEMA_STRUCTURED_OUTPUT"
            )
        _require_trimmed(
            "responseContractVersion", self.response_contract_version
        )
        return self


class ModelInferenceOutputSchemaContract(_StructuredAdmissionContract):
    reference: CapabilityPackContractReference
    provider_schema_name: Annotated[
        str,
        StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"),
    ]
    json_schema: Annotated[
        str,
        StringConstraints(strip_whitespace=False, min_length=1, max_length=100_000),
    ]

    @model_validator(mode="after")
    def validate_schema(self) -> "ModelInferenceOutputSchemaContract":
        if self.reference.kind != "MODEL_RESPONSE_SCHEMA":
            raise ValueError("model response reference kind is invalid")
        _require_trimmed("jsonSchema", self.json_schema)
        return self


class StructuredModelRouteReceipt(_StructuredAdmissionContract):
    route_binding_id: NonNilUuid
    route_state_version: int = Field(ge=1, le=JAVA_LONG_MAX)
    model_definition_id: NonNilUuid
    model_configuration_version: int = Field(ge=1, le=JAVA_LONG_MAX)
    reservation_ceiling_micro_credit: int = Field(ge=1, le=JAVA_LONG_MAX)


class StructuredModelQualificationReceipt(_StructuredAdmissionContract):
    policy_id: NonNilUuid
    policy_version: int = Field(ge=1, le=JAVA_LONG_MAX)
    policy_hash: LowerSha256
    data_sensitivity_code: Literal[
        "PUBLIC_IN_TENANT",
        "INTERNAL",
        "PERSONAL",
        "SENSITIVE",
    ]
    selection_reason_code: UpperStableCode
    sensitivity_evidence_hash: LowerSha256


class StructuredSnapshotReceipt(_StructuredAdmissionContract):
    snapshot_id: NonNilUuid
    hash: LowerSha256


class StructuredOneCallPolicyReceipt(_StructuredAdmissionContract):
    policy_snapshot_id: NonNilUuid
    max_model_calls: Literal[1]
    max_tool_calls: Literal[0]
    model_call_reservation_ceiling: int = Field(ge=1, le=JAVA_LONG_MAX)
    total_model_reservation_ceiling: int = Field(ge=1, le=JAVA_LONG_MAX)
    hash: LowerSha256

    @model_validator(mode="after")
    def validate_policy(self) -> "StructuredOneCallPolicyReceipt":
        if self.total_model_reservation_ceiling != self.model_call_reservation_ceiling:
            raise ValueError("one-call reservation ceilings differ")
        expected = structured_one_call_policy_hash(
            self.model_call_reservation_ceiling
        )
        if self.hash != expected:
            raise ValueError("one-call policy hash does not match its payload")
        return self


class JavaCapabilityStructuredAdmissionManifest(_StructuredAdmissionContract):
    """Java 权威产生的 3.0 Admission；Python 只能校验和转发。"""

    runtime_run_id: NonNilUuid
    tenant_id: NonNilUuid
    task_id: NonNilUuid
    task_step_id: NonNilUuid
    execution_generation: int = Field(ge=1, le=JAVA_LONG_MAX)
    actor_user_id: NonNilUuid
    admission_contract_version: Literal["3.0"]
    runtime_profile: Literal["JAVA_CAPABILITY_STRUCTURED"]
    admission_snapshot_id: NonNilUuid
    admission_snapshot_hash: LowerSha256
    request_hash: LowerSha256
    idempotency_key: Annotated[
        str,
        StringConstraints(strip_whitespace=False, min_length=1, max_length=200),
    ]
    input_snapshot_id: NonNilUuid
    enterprise_agent_id: NonNilUuid
    agent_version_id: NonNilUuid
    configuration_version_id: NonNilUuid
    point_reservation_id: NonNilUuid
    capability_pack: CapabilityPackVersionReference
    model_requirement: ExecutionModelRequirement
    model_response_contract: ModelInferenceOutputSchemaContract
    candidate_output_contract: CapabilityPackContractReference
    candidate_schema_id: LowerSchemaId
    candidate_schema_version: TrimmedText64
    model_route: StructuredModelRouteReceipt
    model_qualification: StructuredModelQualificationReceipt
    prompt: StructuredSnapshotReceipt
    context: StructuredSnapshotReceipt
    one_call_policy: StructuredOneCallPolicyReceipt

    @model_validator(mode="after")
    def validate_cross_references(self) -> "JavaCapabilityStructuredAdmissionManifest":
        _require_trimmed("idempotencyKey", self.idempotency_key)
        _require_trimmed("candidateSchemaVersion", self.candidate_schema_version)
        response = self.model_response_contract.reference
        requirement = self.model_requirement
        if (
            requirement.response_contract_code.upper() != response.contract_code
            or requirement.response_contract_version != response.version
        ):
            raise ValueError("model requirement and response contract differ")
        candidate = self.candidate_output_contract
        if candidate.kind != "OUTPUT_SCHEMA":
            raise ValueError("candidateOutputContract must be OUTPUT_SCHEMA")
        if (
            self.candidate_schema_id.upper() != candidate.contract_code
            or self.candidate_schema_version != candidate.version
        ):
            raise ValueError("candidate schema and output contract differ")
        if (
            self.model_route.reservation_ceiling_micro_credit
            != self.one_call_policy.model_call_reservation_ceiling
        ):
            raise ValueError("model route and one-call ceilings differ")
        return self


def structured_one_call_policy_hash(model_call_reservation_ceiling: int) -> str:
    """与 Java/数据库共同冻结的一次调用策略哈希。"""

    if isinstance(model_call_reservation_ceiling, bool) or not isinstance(
        model_call_reservation_ceiling, int
    ):
        raise TypeError("model_call_reservation_ceiling must be an integer")
    if not 1 <= model_call_reservation_ceiling <= JAVA_LONG_MAX:
        raise ValueError("model_call_reservation_ceiling must fit a positive Java long")
    payload = {
        "schemaVersion": "capability-structured-one-call-policy-v1",
        "maxModelCalls": 1,
        "maxToolCalls": 0,
        "modelCallReservationCeiling": model_call_reservation_ceiling,
        "totalModelReservationCeiling": model_call_reservation_ceiling,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_trimmed(name: str, value: str) -> None:
    if value != value.strip():
        raise ValueError(f"{name} must not contain surrounding whitespace")


def _require_sorted_unique(name: str, values: list[str]) -> None:
    if values != sorted(values) or len(values) != len(set(values)):
        raise ValueError(f"{name} must be sorted and unique")

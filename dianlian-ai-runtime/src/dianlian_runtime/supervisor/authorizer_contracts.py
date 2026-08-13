from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
)
from pydantic.alias_generators import to_camel


_MAX_BIGINT = 9_223_372_036_854_775_807


def _require_non_nil_uuid(value: UUID) -> UUID:
    if value.int == 0:
        raise ValueError("UUID must not be the nil UUID")
    return value


NonNilUuid = Annotated[UUID, AfterValidator(_require_non_nil_uuid)]
LowerSha256 = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]


class _PermitAuthorizationContract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_alias=True,
        validate_by_name=False,
        extra="forbid",
        frozen=True,
    )


class PermitAuthorizationRequest(_PermitAuthorizationContract):
    tenant_id: NonNilUuid
    runtime_external_permit_id: NonNilUuid
    runtime_run_id: NonNilUuid
    task_execution_generation: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    lease_owner: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=160),
    ]
    lease_epoch: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    admission_snapshot_id: NonNilUuid
    admission_snapshot_hash: LowerSha256
    operation_kind: Literal["ADMISSION_RESOLVE"]
    intent_id: NonNilUuid
    request_hash: LowerSha256
    consume_event_id: NonNilUuid

    @field_validator("lease_owner")
    @classmethod
    def require_trimmed_lease_owner(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("leaseOwner must be non-blank and trimmed")
        return value


class PermitAuthorizationOutcome(StrEnum):
    APPLIED = "APPLIED"
    NOT_APPLIED = "NOT_APPLIED"


class PermitAuthorizationResponse(_PermitAuthorizationContract):
    outcome: PermitAuthorizationOutcome


class PermitAuthorizationProblem(_PermitAuthorizationContract):
    code: str
    message: str

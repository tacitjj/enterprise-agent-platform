from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


CONTRACT_VERSION = "1.0"
MAX_CONTENT_LENGTH = 100 * 1024 * 1024
ALLOWED_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "text/plain",
        "text/markdown",
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
)

Sha256Hex = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]
BoundedText = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=256),
]
MediaType = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=200),
]
RejectionCode = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[A-Z][A-Z0-9_]{0,63}$"),
]


class StrictInspectionModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_by_alias=True,
        validate_by_name=False,
    )


class UploadInspectionOutcome(StrEnum):
    CLEAN = "CLEAN"
    REJECTED = "REJECTED"


class UploadInspectionRequest(StrictInspectionModel):
    """Java 上传状态机冻结的精确对象版本检查请求。"""

    contract_version: Literal[CONTRACT_VERSION] = Field(alias="contractVersion")
    inspection_request_id: UUID = Field(alias="inspectionRequestId")
    provider_object_version: BoundedText = Field(alias="providerObjectVersion")
    provider_checksum: BoundedText = Field(alias="providerChecksum")
    declared_media_type: MediaType = Field(alias="declaredMediaType")
    declared_content_length: int = Field(
        alias="declaredContentLength",
        strict=True,
        ge=1,
        le=MAX_CONTENT_LENGTH,
    )
    declared_content_sha256: Sha256Hex = Field(alias="declaredContentSha256")
    source_read_url: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=4096),
    ] = Field(alias="sourceReadUrl", repr=False)
    source_expires_at: datetime = Field(alias="sourceExpiresAt")
    requested_at: datetime = Field(alias="requestedAt")

    @field_validator("declared_media_type")
    @classmethod
    def require_allowed_media_type(cls, value: str) -> str:
        if value not in ALLOWED_MEDIA_TYPES:
            raise ValueError("declaredMediaType is outside upload-policy-v1")
        return value

    @field_validator("source_expires_at", "requested_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("inspection timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def require_non_nil_and_live_capability(self) -> "UploadInspectionRequest":
        if self.inspection_request_id.int == 0:
            raise ValueError("inspectionRequestId must not be nil")
        if self.source_expires_at <= self.requested_at:
            raise ValueError("source read capability must outlive requestedAt")
        return self


class UploadInspectionResponse(StrictInspectionModel):
    """可由 Java 严格回验并转为上传终态事实的 ClamAV 回执。"""

    contract_version: Literal[CONTRACT_VERSION] = Field(alias="contractVersion")
    inspection_request_id: UUID = Field(alias="inspectionRequestId")
    provider_object_version: BoundedText = Field(alias="providerObjectVersion")
    provider_checksum: BoundedText = Field(alias="providerChecksum")
    scanner_fact_id: UUID = Field(alias="scannerFactId")
    outcome: UploadInspectionOutcome
    detected_media_type: MediaType = Field(alias="detectedMediaType")
    content_length: int = Field(alias="contentLength", strict=True, ge=1, le=MAX_CONTENT_LENGTH)
    content_sha256: Sha256Hex = Field(alias="contentSha256")
    inspection_profile_version: Annotated[
        str,
        StringConstraints(strict=True, pattern=r"^[a-z0-9][a-z0-9._-]{0,159}$"),
    ] = Field(alias="inspectionProfileVersion")
    rejection_code: RejectionCode | None = Field(alias="rejectionCode", default=None)
    scanner_id: Literal["clamav"] = Field(alias="scannerId")
    requested_at: datetime = Field(alias="requestedAt")
    observed_at: datetime = Field(alias="observedAt")

    @field_validator("detected_media_type")
    @classmethod
    def require_allowed_detected_media_type(cls, value: str) -> str:
        if value not in ALLOWED_MEDIA_TYPES:
            raise ValueError("detectedMediaType is outside upload-policy-v1")
        return value

    @field_validator("requested_at", "observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("inspection timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def require_terminal_shape(self) -> "UploadInspectionResponse":
        if self.scanner_fact_id.int == 0:
            raise ValueError("scannerFactId must not be nil")
        if (self.outcome == UploadInspectionOutcome.REJECTED) != (
            self.rejection_code is not None
        ):
            raise ValueError("rejectionCode must exist exactly for REJECTED")
        return self


class UploadInspectionProblem(StrictInspectionModel):
    code: str
    message: str

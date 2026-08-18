from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator


CONTRACT_VERSION = "1.0"
MAX_CONTENT_LENGTH = 100 * 1024 * 1024
MAX_NORMALIZED_TEXT_LENGTH = 2_000_000
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

Sha256Hex = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
BoundedText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]


class ParserEngine(StrEnum):
    DOCLING = "DOCLING"
    TIKA = "TIKA"


class StrictNormalizationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_by_alias=True, validate_by_name=False)


class NormalizationSourceRequest(StrictNormalizationModel):
    """Java 权威层派生的已验证对象快照与短时读取能力。"""

    tenant_id: UUID = Field(alias="tenantId")
    relation_type: Literal[
        "KNOWLEDGE_DOCUMENT_VERSION",
        "TASK_INPUT_ATTACHMENT",
        "CONVERSATION_MESSAGE_ATTACHMENT",
    ] = Field(alias="relationType")
    relation_id: UUID = Field(alias="relationId")
    upload_receipt_id: UUID = Field(alias="uploadReceiptId")
    upload_id: UUID = Field(alias="uploadId")
    upload_purpose: Literal[
        "KNOWLEDGE_SOURCE", "TASK_INPUT", "CONVERSATION_ATTACHMENT"
    ] = Field(alias="uploadPurpose")
    provider_object_version: BoundedText = Field(alias="providerObjectVersion")
    media_type: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=200)
    ] = Field(alias="mediaType")
    content_length: int = Field(
        alias="contentLength", strict=True, ge=1, le=MAX_CONTENT_LENGTH
    )
    content_sha256: Sha256Hex = Field(alias="contentSha256")
    normalization_profile_version: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=100)
    ] = Field(alias="normalizationProfileVersion")
    source_read_url: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=4096)
    ] = Field(alias="sourceReadUrl", repr=False)
    source_expires_at: datetime = Field(alias="sourceExpiresAt")

    @field_validator("media_type")
    @classmethod
    def require_allowed_media_type(cls, value: str) -> str:
        if value not in ALLOWED_MEDIA_TYPES:
            raise ValueError("mediaType is outside upload-policy-v1")
        return value

    @field_validator("source_expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("sourceExpiresAt must include a timezone")
        return value

    @model_validator(mode="after")
    def require_relation_purpose(self) -> "NormalizationSourceRequest":
        expected = {
            "KNOWLEDGE_DOCUMENT_VERSION": "KNOWLEDGE_SOURCE",
            "TASK_INPUT_ATTACHMENT": "TASK_INPUT",
            "CONVERSATION_MESSAGE_ATTACHMENT": "CONVERSATION_ATTACHMENT",
        }[self.relation_type]
        if self.upload_purpose != expected:
            raise ValueError("uploadPurpose does not match relationType")
        return self


class ContentNormalizationRequest(StrictNormalizationModel):
    contract_version: Literal[CONTRACT_VERSION] = Field(alias="contractVersion")
    request_id: UUID = Field(alias="requestId")
    engine: ParserEngine
    requested_at: datetime = Field(alias="requestedAt")
    source: NormalizationSourceRequest

    @field_validator("requested_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("requestedAt must include a timezone")
        return value

    @model_validator(mode="after")
    def require_live_non_nil_request(self) -> "ContentNormalizationRequest":
        if self.request_id.int == 0:
            raise ValueError("requestId must not be nil")
        if self.source.source_expires_at <= self.requested_at:
            raise ValueError("source read capability must outlive requestedAt")
        return self


class NormalizedSegmentResponse(StrictNormalizationModel):
    ordinal: int = Field(strict=True, ge=0, le=19_999)
    kind: Literal["TEXT", "TABLE_CELL", "IMAGE_REGION"]
    normalized_text: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=1_000_000)
    ] = Field(alias="normalizedText")
    locator_schema_id: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=160)
    ] | None = Field(alias="locatorSchemaId", default=None)
    locator_schema_version: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=100)
    ] | None = Field(alias="locatorSchemaVersion", default=None)
    locator_payload: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=100_000)
    ] | None = Field(alias="locatorPayload", default=None)

    @model_validator(mode="after")
    def require_locator_shape(self) -> "NormalizedSegmentResponse":
        fields = (
            self.locator_schema_id,
            self.locator_schema_version,
            self.locator_payload,
        )
        if any(value is not None for value in fields) and not all(
            value is not None for value in fields
        ):
            raise ValueError("locator fields must be all null or all present")
        return self


class ContentNormalizationResponse(StrictNormalizationModel):
    contract_version: Literal[CONTRACT_VERSION] = Field(alias="contractVersion")
    request_id: UUID = Field(alias="requestId")
    engine: ParserEngine
    provider_object_version: BoundedText = Field(alias="providerObjectVersion")
    content_sha256: Sha256Hex = Field(alias="contentSha256")
    normalization_profile_version: Annotated[
        str, StringConstraints(strict=True, min_length=1, max_length=100)
    ] = Field(alias="normalizationProfileVersion")
    segments: list[NormalizedSegmentResponse] = Field(min_length=1, max_length=20_000)


class ContentNormalizationProblem(StrictNormalizationModel):
    code: str
    message: str

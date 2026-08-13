from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from dianlian_runtime.context.contracts import (
    MemoryScopeType,
    NonBlankText,
    Sha256Hex,
    StrictInternalModel,
)


IndexProfileName = Annotated[
    str,
    StringConstraints(
        strict=True,
        strip_whitespace=True,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,99}$",
    ),
]
NormalizedText = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=2_000_000,
    ),
]
SourceContentHash = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64,128}$"),
]


class AuthorityScope(StrEnum):
    PLATFORM = "PLATFORM"
    TENANT = "TENANT"


class IndexResourceType(StrEnum):
    KNOWLEDGE_DOCUMENT_VERSION = "KNOWLEDGE_DOCUMENT_VERSION"
    MEMORY_ITEM_VERSION = "MEMORY_ITEM_VERSION"


class IndexTarget(StrEnum):
    LEXICAL = "LEXICAL"
    VECTOR = "VECTOR"


class IndexOperation(StrEnum):
    UPSERT = "UPSERT"
    DELETE = "DELETE"


class IndexApplyResult(StrEnum):
    APPLIED = "APPLIED"
    NOOP_IDEMPOTENT = "NOOP_IDEMPOTENT"
    NOOP_STALE = "NOOP_STALE"


class MemoryProjectionScope(StrictInternalModel):
    enterprise_agent_id: UUID = Field(alias="enterpriseAgentId")
    scope_type: MemoryScopeType = Field(alias="scopeType")
    scope_id: UUID = Field(alias="scopeId")
    source_message_sequence_no: int | None = Field(
        alias="sourceMessageSequenceNo",
        default=None,
        strict=True,
        ge=0,
    )


class ContextIndexingRequest(StrictInternalModel):
    contract_version: Literal["1.0"] = Field(alias="contractVersion")
    request_id: UUID = Field(alias="requestId")
    trace_id: UUID = Field(alias="traceId")
    job_id: UUID = Field(alias="jobId")
    lease_epoch: int = Field(alias="leaseEpoch", strict=True, ge=1)
    target: IndexTarget
    operation: IndexOperation
    authority_scope: AuthorityScope = Field(alias="authorityScope")
    tenant_id: UUID | None = Field(alias="tenantId", default=None)
    resource_type: IndexResourceType = Field(alias="resourceType")
    resource_id: UUID = Field(alias="resourceId")
    source_id: UUID | None = Field(alias="sourceId", default=None)
    source_version: NonBlankText | None = Field(
        alias="sourceVersion",
        default=None,
        max_length=200,
    )
    event_sequence: int = Field(alias="eventSequence", strict=True, ge=1)
    index_profile: IndexProfileName = Field(alias="indexProfile")
    title: NonBlankText | None = Field(default=None, max_length=500)
    normalized_text: NormalizedText | None = Field(
        alias="normalizedText",
        default=None,
    )
    source_content_hash: SourceContentHash | None = Field(alias="sourceContentHash", default=None)
    normalized_text_hash: Sha256Hex | None = Field(alias="normalizedTextHash", default=None)
    normalization_profile_version: IndexProfileName | None = Field(
        alias="normalizationProfileVersion",
        default=None,
    )
    citation: NonBlankText | None = Field(default=None, max_length=1_000)
    memory_scope: MemoryProjectionScope | None = Field(alias="memoryScope", default=None)

    @model_validator(mode="after")
    def validate_index_write(self) -> "ContextIndexingRequest":
        if self.authority_scope == AuthorityScope.PLATFORM:
            if self.tenant_id is not None:
                raise ValueError("PLATFORM projection must not include tenantId")
            if self.resource_type != IndexResourceType.KNOWLEDGE_DOCUMENT_VERSION:
                raise ValueError("PLATFORM projection only supports knowledge resources")
        elif self.tenant_id is None:
            raise ValueError("TENANT projection requires tenantId")

        if self.operation == IndexOperation.DELETE:
            if any(
                value is not None
                for value in (
                    self.title,
                    self.source_id,
                    self.source_version,
                    self.normalized_text,
                    self.source_content_hash,
                    self.normalized_text_hash,
                    self.normalization_profile_version,
                    self.citation,
                    self.memory_scope,
                )
            ):
                raise ValueError("DELETE projection must not include content fields")
            return self

        if any(
            value is None
            for value in (
                self.source_id,
                self.source_version,
                self.title,
                self.normalized_text,
                self.normalized_text_hash,
                self.normalization_profile_version,
                self.citation,
            )
        ):
            raise ValueError(
                "UPSERT projection requires source identity, title, normalized text, normalized hash, "
                "normalization profile and citation"
            )

        assert self.normalized_text is not None
        assert self.normalized_text_hash is not None
        if not self.normalized_text.strip():
            raise ValueError("normalizedText must not be blank")
        actual_hash = sha256(self.normalized_text.encode("utf-8")).hexdigest()
        if actual_hash != self.normalized_text_hash:
            raise ValueError(
                "normalizedTextHash must be the SHA-256 of the exact normalizedText UTF-8 bytes"
            )

        if self.resource_type == IndexResourceType.MEMORY_ITEM_VERSION:
            if self.memory_scope is None:
                raise ValueError("memory projection requires memoryScope")
            if self.source_id != self.resource_id:
                raise ValueError("memory sourceId must equal projection resourceId")
            try:
                if int(self.source_version or "0") <= 0:
                    raise ValueError
            except ValueError as exception:
                raise ValueError("memory sourceVersion must be a positive integer") from exception
        else:
            if self.source_content_hash is None:
                raise ValueError("knowledge projection requires sourceContentHash")
            if self.memory_scope is not None:
                raise ValueError("knowledge projection must not include memoryScope")
            try:
                UUID(self.source_version or "")
            except ValueError as exception:
                raise ValueError("knowledge sourceVersion must be a UUID") from exception
        return self


class ChunkManifestEntry(StrictInternalModel):
    chunk_id: Sha256Hex = Field(alias="chunkId")
    chunk_content_hash: Sha256Hex = Field(alias="chunkContentHash")
    ordinal: int = Field(strict=True, ge=0)


class ContextIndexingReceipt(StrictInternalModel):
    contract_version: Literal["1.0"] = Field(alias="contractVersion")
    request_id: UUID = Field(alias="requestId")
    job_id: UUID = Field(alias="jobId")
    lease_epoch: int = Field(alias="leaseEpoch", strict=True, ge=1)
    target: IndexTarget
    operation: IndexOperation
    result: IndexApplyResult
    event_sequence: int = Field(alias="eventSequence", strict=True, ge=1)
    indexed_chunk_count: int = Field(alias="indexedChunkCount", strict=True, ge=0)
    index_profile: IndexProfileName = Field(alias="indexProfile")
    resource_type: IndexResourceType = Field(alias="resourceType")
    resource_id: UUID = Field(alias="resourceId")
    source_id: UUID | None = Field(alias="sourceId")
    source_version: NonBlankText | None = Field(alias="sourceVersion", max_length=200)
    projection_manifest_hash: Sha256Hex = Field(alias="projectionManifestHash")
    chunk_manifest: list[ChunkManifestEntry] = Field(alias="chunkManifest", max_length=8_192)

    @model_validator(mode="after")
    def validate_manifest_shape(self) -> "ContextIndexingReceipt":
        if self.indexed_chunk_count != len(self.chunk_manifest):
            raise ValueError("indexedChunkCount must equal chunkManifest size")
        if [item.ordinal for item in self.chunk_manifest] != list(range(len(self.chunk_manifest))):
            raise ValueError("chunkManifest ordinals must be contiguous and canonical")
        if len({item.chunk_id for item in self.chunk_manifest}) != len(self.chunk_manifest):
            raise ValueError("chunkManifest chunkId values must be unique")
        canonical = "".join(
            f"{item.ordinal}\0{item.chunk_id}\0{item.chunk_content_hash}\n"
            for item in self.chunk_manifest
        )
        if sha256(canonical.encode("utf-8")).hexdigest() != self.projection_manifest_hash:
            raise ValueError("projectionManifestHash must identify chunkManifest")
        if self.operation == IndexOperation.UPSERT:
            if self.source_id is None or self.source_version is None or not self.chunk_manifest:
                raise ValueError("UPSERT receipt requires source identity and chunk manifest")
        elif self.source_id is not None or self.source_version is not None or self.chunk_manifest:
            raise ValueError("DELETE receipt cannot contain source identity or chunks")
        return self

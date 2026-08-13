from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


NonBlankText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
]
Sha256Hex = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$"),
]


class StrictInternalModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_by_alias=True,
        validate_by_name=False,
    )


class RequestedSource(StrEnum):
    KNOWLEDGE = "KNOWLEDGE"
    MEMORY = "MEMORY"


class MemoryScopeType(StrEnum):
    AGENT = "AGENT"
    USER_AGENT = "USER_AGENT"
    GROUP_AGENT = "GROUP_AGENT"


class ContextSourceState(StrEnum):
    READY = "READY"
    EMPTY = "EMPTY"
    UNAVAILABLE = "UNAVAILABLE"
    FORBIDDEN = "FORBIDDEN"


class AuthorizedKnowledgeResource(StrictInternalModel):
    tenant_id: UUID = Field(alias="tenantId")
    resource_id: UUID = Field(alias="resourceId")
    resource_version_id: UUID = Field(alias="resourceVersionId")


class AllowedMemoryScope(StrictInternalModel):
    tenant_id: UUID = Field(alias="tenantId")
    scope_type: MemoryScopeType = Field(alias="scopeType")
    scope_id: UUID = Field(alias="scopeId")
    enterprise_agent_id: UUID = Field(alias="enterpriseAgentId")
    history_floor_sequence_no: int = Field(
        alias="historyFloorSequenceNo",
        strict=True,
        ge=0,
    )


class RetrievalPolicy(StrictInternalModel):
    lexical_top_k: int = Field(alias="lexicalTopK", strict=True, ge=1, le=100)
    vector_top_k: int = Field(alias="vectorTopK", strict=True, ge=1, le=100)
    rerank_top_k: int = Field(alias="rerankTopK", strict=True, ge=1, le=100)
    max_evidence: int = Field(alias="maxEvidence", strict=True, ge=1, le=100)
    max_context_tokens: int = Field(
        alias="maxContextTokens",
        strict=True,
        ge=128,
        le=131_072,
    )

    @model_validator(mode="after")
    def validate_result_limits(self) -> "RetrievalPolicy":
        if self.rerank_top_k > self.lexical_top_k + self.vector_top_k:
            raise ValueError("rerankTopK cannot exceed the combined candidate limit")
        if self.max_evidence > self.rerank_top_k:
            raise ValueError("maxEvidence cannot exceed rerankTopK")
        return self


class ContextRetrievalRequest(StrictInternalModel):
    contract_version: Annotated[
        str,
        StringConstraints(strict=True, pattern=r"^1\.[0-9]+$"),
    ] = Field(
        alias="contractVersion"
    )
    request_id: UUID = Field(alias="requestId")
    trace_id: UUID = Field(alias="traceId")
    deadline_at: datetime = Field(alias="deadlineAt")
    tenant_id: UUID = Field(alias="tenantId")
    actor_user_id: UUID = Field(alias="actorUserId")
    enterprise_agent_id: UUID = Field(alias="enterpriseAgentId")
    conversation_id: UUID = Field(alias="conversationId")
    query: Annotated[NonBlankText, StringConstraints(max_length=20_000)]
    audience_user_ids: list[UUID] = Field(alias="audienceUserIds", min_length=1, max_length=500)
    authorized_knowledge_resources: list[AuthorizedKnowledgeResource] = Field(
        alias="authorizedKnowledgeResources",
        max_length=2_000,
    )
    allowed_memory_scopes: list[AllowedMemoryScope] = Field(
        alias="allowedMemoryScopes",
        max_length=100,
    )
    requested_sources: list[RequestedSource] = Field(
        alias="requestedSources",
        min_length=1,
        max_length=2,
    )
    policy: RetrievalPolicy
    authorization_snapshot_hash: Sha256Hex = Field(alias="authorizationSnapshotHash")

    @field_validator("deadline_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("deadlineAt must include a timezone")
        return value

    @field_validator("audience_user_ids")
    @classmethod
    def require_unique_audience(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("audienceUserIds must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_authorized_scope(self) -> "ContextRetrievalRequest":
        requested = set(self.requested_sources)
        if len(requested) != len(self.requested_sources):
            raise ValueError("requestedSources must not contain duplicates")
        if RequestedSource.KNOWLEDGE in requested and not self.authorized_knowledge_resources:
            raise ValueError("KNOWLEDGE retrieval requires an explicit resource allowlist")
        if RequestedSource.MEMORY in requested and not self.allowed_memory_scopes:
            raise ValueError("MEMORY retrieval requires an explicit scope allowlist")

        knowledge_keys = set()
        for resource in self.authorized_knowledge_resources:
            if resource.tenant_id != self.tenant_id:
                raise ValueError("authorized knowledge resource tenant does not match request tenant")
            key = (resource.resource_id, resource.resource_version_id)
            if key in knowledge_keys:
                raise ValueError("authorizedKnowledgeResources must not contain duplicates")
            knowledge_keys.add(key)

        memory_keys = set()
        for scope in self.allowed_memory_scopes:
            if scope.tenant_id != self.tenant_id:
                raise ValueError("allowed memory scope tenant does not match request tenant")
            if scope.enterprise_agent_id != self.enterprise_agent_id:
                raise ValueError("allowed memory scope agent does not match request agent")
            key = (scope.scope_type, scope.scope_id, scope.history_floor_sequence_no)
            if key in memory_keys:
                raise ValueError("allowedMemoryScopes must not contain duplicates")
            memory_keys.add(key)
        return self


class ContextEvidence(StrictInternalModel):
    evidence_id: NonBlankText = Field(alias="evidenceId", max_length=200)
    source_type: RequestedSource = Field(alias="sourceType")
    source_id: UUID = Field(alias="sourceId")
    source_version: NonBlankText = Field(alias="sourceVersion", max_length=200)
    chunk_id: NonBlankText = Field(alias="chunkId", max_length=200)
    title: NonBlankText = Field(max_length=500)
    excerpt: NonBlankText = Field(max_length=2_000)
    content_hash: Sha256Hex = Field(alias="contentHash")
    score: float = Field(strict=True, ge=0, le=1)
    citation: NonBlankText = Field(max_length=1_000)

    @model_validator(mode="after")
    def require_exact_chunk_content_hash(self) -> "ContextEvidence":
        from hashlib import sha256

        if sha256(self.excerpt.encode("utf-8")).hexdigest() != self.content_hash:
            raise ValueError("contentHash must identify the exact excerpt bytes")
        return self


class ContextSourceBundle(StrictInternalModel):
    state: ContextSourceState
    reason_code: NonBlankText | None = Field(
        alias="reasonCode",
        default=None,
        max_length=128,
    )
    evidence: list[ContextEvidence] = Field(max_length=100)

    @model_validator(mode="after")
    def validate_state(self) -> "ContextSourceBundle":
        if self.state == ContextSourceState.READY:
            if not self.evidence:
                raise ValueError("READY context source must include evidence")
            if self.reason_code is not None:
                raise ValueError("READY context source cannot include reasonCode")
        else:
            if self.evidence:
                raise ValueError("non-ready context source cannot include evidence")
            if self.reason_code is None or not self.reason_code.strip():
                raise ValueError("non-ready context source must include reasonCode")
        return self


class RetrievalTrace(StrictInternalModel):
    strategies: list[NonBlankText] = Field(min_length=1, max_length=10)
    candidate_count: int = Field(alias="candidateCount", strict=True, ge=0)
    reranked_count: int = Field(alias="rerankedCount", strict=True, ge=0)
    index_version: NonBlankText = Field(alias="indexVersion", max_length=200)
    elapsed_ms: int = Field(alias="elapsedMs", strict=True, ge=0)


class ContextBundle(StrictInternalModel):
    contract_version: Annotated[
        str,
        StringConstraints(strict=True, pattern=r"^1\.[0-9]+$"),
    ] = Field(
        alias="contractVersion"
    )
    request_id: UUID = Field(alias="requestId")
    retrieval_snapshot_id: NonBlankText = Field(alias="retrievalSnapshotId", max_length=200)
    generated_at: datetime = Field(alias="generatedAt")
    knowledge: ContextSourceBundle
    memory: ContextSourceBundle
    retrieval_trace: RetrievalTrace = Field(alias="retrievalTrace")

    @model_validator(mode="after")
    def validate_evidence_layout(self) -> "ContextBundle":
        knowledge = self.knowledge.evidence
        memory = self.memory.evidence
        if any(item.source_type != RequestedSource.KNOWLEDGE for item in knowledge):
            raise ValueError("knowledge bundle contains a non-knowledge evidence source")
        if any(item.source_type != RequestedSource.MEMORY for item in memory):
            raise ValueError("memory bundle contains a non-memory evidence source")
        evidence_ids = [item.evidence_id for item in knowledge + memory]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidenceId must be globally unique within ContextBundle")
        return self


class ServiceUnavailableResponse(StrictInternalModel):
    code: NonBlankText = Field(max_length=128)
    message: NonBlankText = Field(max_length=500)

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json

from llama_index.core.node_parser import SentenceSplitter

from dianlian_runtime.context.indexing_contracts import (
    ContextIndexingRequest,
    IndexOperation,
)


@dataclass(frozen=True, slots=True)
class LexicalIndexProfile:
    name: str
    chunk_size: int
    chunk_overlap: int


LEXICAL_V1_PROFILE = LexicalIndexProfile(
    name="context-default-v1",
    chunk_size=512,
    chunk_overlap=64,
)


@dataclass(frozen=True, slots=True)
class LexicalChunk:
    chunk_id: str
    ordinal: int
    content: str


class FenceDecision(StrEnum):
    APPLY = "APPLY"
    NOOP_IDEMPOTENT = "NOOP_IDEMPOTENT"
    NOOP_STALE = "NOOP_STALE"
    CONFLICT = "CONFLICT"


def resolve_index_profile(name: str) -> LexicalIndexProfile:
    if name != LEXICAL_V1_PROFILE.name:
        raise ValueError(f"Unsupported context index profile: {name}")
    return LEXICAL_V1_PROFILE


def projection_payload_hash(request: ContextIndexingRequest) -> str | None:
    if request.operation == IndexOperation.DELETE:
        return None
    memory_scope = request.memory_scope
    canonical = {
        "citation": request.citation,
        "normalizedTextHash": request.normalized_text_hash,
        "sourceContentHash": request.source_content_hash,
        "normalizationProfileVersion": request.normalization_profile_version,
        "memoryScope": None
        if memory_scope is None
        else {
            "enterpriseAgentId": str(memory_scope.enterprise_agent_id),
            "scopeId": str(memory_scope.scope_id),
            "scopeType": memory_scope.scope_type.value,
            "sourceMessageSequenceNo": memory_scope.source_message_sequence_no,
        },
        "sourceId": str(request.source_id),
        "sourceVersion": request.source_version,
        "title": request.title,
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def decide_fence_write(
    *,
    previous_event_sequence: int,
    previous_operation: IndexOperation,
    previous_payload_hash: str | None,
    event_sequence: int,
    operation: IndexOperation,
    payload_hash: str | None,
) -> FenceDecision:
    if event_sequence < previous_event_sequence:
        return FenceDecision.NOOP_STALE
    if event_sequence > previous_event_sequence:
        return FenceDecision.APPLY

    if previous_operation == IndexOperation.DELETE:
        if operation == IndexOperation.DELETE:
            return FenceDecision.NOOP_IDEMPOTENT
        return FenceDecision.NOOP_STALE
    if operation == IndexOperation.DELETE:
        return FenceDecision.APPLY
    if previous_payload_hash == payload_hash:
        return FenceDecision.NOOP_IDEMPOTENT
    return FenceDecision.CONFLICT


def split_lexical_chunks(
    request: ContextIndexingRequest,
    profile: LexicalIndexProfile,
) -> list[LexicalChunk]:
    if request.operation != IndexOperation.UPSERT or request.normalized_text is None:
        return []
    splitter = SentenceSplitter(
        chunk_size=profile.chunk_size,
        chunk_overlap=profile.chunk_overlap,
    )
    chunks = []
    for ordinal, content in enumerate(splitter.split_text(request.normalized_text)):
        normalized = content.strip()
        if not normalized:
            continue
        identity = "\0".join(
            (
                profile.name,
                request.authority_scope.value,
                str(request.tenant_id or "PLATFORM"),
                request.resource_type.value,
                str(request.resource_id),
                str(request.source_id or ""),
                request.source_version or "",
                request.normalized_text_hash or "",
                str(ordinal),
                sha256(normalized.encode("utf-8")).hexdigest(),
            )
        )
        chunks.append(
            LexicalChunk(
                chunk_id=sha256(identity.encode("utf-8")).hexdigest(),
                ordinal=ordinal,
                content=normalized,
            )
        )
    return chunks

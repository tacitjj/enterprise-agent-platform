package com.dianlian.platform.memory.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record MemoryCandidateSnapshot(
        UUID candidateId,
        UUID enterpriseAgentId,
        MemoryScopeRef scope,
        String content,
        String semanticKey,
        MemoryCandidateStatus status,
        UUID proposedBy,
        Instant proposedAt,
        UUID decidedBy,
        Instant decidedAt,
        String decisionReason,
        UUID confirmedMemoryId
) {
    public MemoryCandidateSnapshot {
        Objects.requireNonNull(candidateId, "candidateId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(scope, "scope must not be null");
        Objects.requireNonNull(content, "content must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(proposedBy, "proposedBy must not be null");
        Objects.requireNonNull(proposedAt, "proposedAt must not be null");
    }
}

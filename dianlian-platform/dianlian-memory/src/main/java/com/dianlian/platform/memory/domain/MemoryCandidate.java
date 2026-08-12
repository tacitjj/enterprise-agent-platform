package com.dianlian.platform.memory.domain;

import com.dianlian.platform.memory.api.MemoryCandidateSnapshot;
import com.dianlian.platform.memory.api.MemoryCandidateStatus;
import com.dianlian.platform.memory.api.MemoryScopeRef;
import com.dianlian.platform.memory.api.MemoryScopeType;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record MemoryCandidate(
        UUID candidateId,
        UUID tenantId,
        UUID enterpriseAgentId,
        MemoryScopeRef scope,
        String content,
        String semanticKey,
        UUID sourceConversationId,
        UUID sourceMessageId,
        MemoryCandidateStatus status,
        String requestHash,
        String idempotencyKey,
        UUID proposedBy,
        Instant proposedAt,
        UUID decidedBy,
        Instant decidedAt,
        String decisionReason,
        String decisionRequestHash,
        String decisionIdempotencyKey,
        UUID confirmedMemoryId
) {
    public MemoryCandidate {
        Objects.requireNonNull(candidateId, "candidateId must not be null");
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(scope, "scope must not be null");
        if (scope.scopeType() == MemoryScopeType.AGENT
                && !scope.scopeId().equals(enterpriseAgentId)) {
            throw new IllegalArgumentException("AGENT scopeId must equal enterpriseAgentId");
        }
        Objects.requireNonNull(content, "content must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(requestHash, "requestHash must not be null");
        Objects.requireNonNull(idempotencyKey, "idempotencyKey must not be null");
        Objects.requireNonNull(proposedBy, "proposedBy must not be null");
        Objects.requireNonNull(proposedAt, "proposedAt must not be null");
    }

    public MemoryCandidateSnapshot toSnapshot() {
        return new MemoryCandidateSnapshot(
                candidateId,
                enterpriseAgentId,
                scope,
                content,
                semanticKey,
                status,
                proposedBy,
                proposedAt,
                decidedBy,
                decidedAt,
                decisionReason,
                confirmedMemoryId
        );
    }
}

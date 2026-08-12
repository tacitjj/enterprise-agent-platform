package com.dianlian.platform.memory.application;

import com.dianlian.platform.memory.api.InvocationMemoryAuthoritySource.MemoryEvidenceKey;
import com.dianlian.platform.memory.api.MemoryItemStatus;
import com.dianlian.platform.memory.api.MemoryScopeRef;
import com.dianlian.platform.memory.domain.MemoryCandidate;
import com.dianlian.platform.memory.domain.MemoryEvent;
import com.dianlian.platform.memory.domain.MemoryItem;
import com.dianlian.platform.memory.domain.MemoryVersion;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface MemoryRepository {

    Optional<MemoryCandidate> findCandidateByProposeIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    );

    Optional<MemoryCandidate> findCandidateByDecisionIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    );

    Optional<MemoryCandidate> lockCandidate(UUID tenantId, UUID candidateId);

    boolean insertCandidateIfAbsent(MemoryCandidate candidate);

    boolean markCandidateConfirmed(
            UUID tenantId,
            UUID candidateId,
            UUID memoryId,
            UUID actorId,
            Instant decidedAt,
            String reason,
            String requestHash,
            String idempotencyKey
    );

    boolean markCandidateRejected(
            UUID tenantId,
            UUID candidateId,
            UUID actorId,
            Instant decidedAt,
            String reason,
            String requestHash,
            String idempotencyKey
    );

    Optional<MemoryItem> lockMemory(UUID tenantId, UUID memoryId);

    Optional<MemoryItem> findMemory(UUID tenantId, UUID memoryId);

    Optional<MemoryVersion> findCorrectionByIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    );

    Optional<MemoryItem> findForgetByIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    );

    void insertMemory(MemoryItem memory);

    void insertVersion(MemoryVersion version);

    boolean advanceMemoryVersion(
            UUID tenantId,
            UUID memoryId,
            long expectedVersion,
            String content,
            String semanticKey,
            Instant updatedAt
    );

    boolean forgetMemory(
            UUID tenantId,
            UUID memoryId,
            long expectedVersion,
            UUID actorId,
            Instant forgottenAt,
            String reason,
            String requestHash,
            String idempotencyKey
    );

    long insertEvent(MemoryEvent event);

    void insertIndexJob(MemoryIndexJobWrite write);

    List<MemoryItem> recallConfirmed(
            UUID tenantId,
            UUID enterpriseAgentId,
            List<MemoryScopeRef> scopes,
            String query,
            int limit
    );

    List<MemoryAuthoritySnapshot> findAuthoritySnapshots(
            UUID tenantId,
            List<MemoryEvidenceKey> evidenceKeys
    );

    record MemoryAuthoritySnapshot(
            MemoryEvidenceKey key,
            UUID enterpriseAgentId,
            MemoryScopeRef scope,
            MemoryItemStatus status,
            long currentVersion,
            Long sourceMessageSequenceNo
    ) {
    }
}

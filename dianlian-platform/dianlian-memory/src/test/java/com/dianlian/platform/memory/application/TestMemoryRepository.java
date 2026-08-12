package com.dianlian.platform.memory.application;

import com.dianlian.platform.memory.api.MemoryCandidateStatus;
import com.dianlian.platform.memory.api.MemoryItemStatus;
import com.dianlian.platform.memory.api.MemoryScopeRef;
import com.dianlian.platform.memory.api.InvocationMemoryAuthoritySource.MemoryEvidenceKey;
import com.dianlian.platform.memory.domain.MemoryCandidate;
import com.dianlian.platform.memory.domain.MemoryEvent;
import com.dianlian.platform.memory.domain.MemoryItem;
import com.dianlian.platform.memory.domain.MemoryVersion;
import com.dianlian.platform.memory.domain.MemoryVersionChangeType;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

final class TestMemoryRepository implements MemoryRepository {

    final Map<UUID, MemoryCandidate> candidates = new LinkedHashMap<>();
    final Map<UUID, MemoryItem> memories = new LinkedHashMap<>();
    final List<MemoryVersion> versions = new ArrayList<>();
    final List<MemoryEvent> events = new ArrayList<>();
    final List<MemoryIndexJobWrite> indexJobs = new ArrayList<>();
    final Map<UUID, Long> authoritySourceSequences = new LinkedHashMap<>();
    private long nextEventSequence = 1;

    @Override
    public Optional<MemoryCandidate> findCandidateByProposeIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        return candidates.values().stream()
                .filter(value -> value.tenantId().equals(tenantId))
                .filter(value -> value.proposedBy().equals(actorId))
                .filter(value -> value.idempotencyKey().equals(idempotencyKey))
                .findFirst();
    }

    @Override
    public Optional<MemoryCandidate> findCandidateByDecisionIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        return candidates.values().stream()
                .filter(value -> value.tenantId().equals(tenantId))
                .filter(value -> actorId.equals(value.decidedBy()))
                .filter(value -> idempotencyKey.equals(value.decisionIdempotencyKey()))
                .findFirst();
    }

    @Override
    public Optional<MemoryCandidate> lockCandidate(UUID tenantId, UUID candidateId) {
        return Optional.ofNullable(candidates.get(candidateId))
                .filter(value -> value.tenantId().equals(tenantId));
    }

    @Override
    public boolean insertCandidateIfAbsent(MemoryCandidate candidate) {
        if (findCandidateByProposeIdempotency(
                candidate.tenantId(), candidate.proposedBy(), candidate.idempotencyKey()
        ).isPresent()) {
            return false;
        }
        candidates.put(candidate.candidateId(), candidate);
        return true;
    }

    @Override
    public boolean markCandidateConfirmed(
            UUID tenantId,
            UUID candidateId,
            UUID memoryId,
            UUID actorId,
            Instant decidedAt,
            String reason,
            String requestHash,
            String idempotencyKey
    ) {
        return decide(tenantId, candidateId, MemoryCandidateStatus.CONFIRMED, memoryId, actorId, decidedAt,
                reason, requestHash, idempotencyKey);
    }

    @Override
    public boolean markCandidateRejected(
            UUID tenantId,
            UUID candidateId,
            UUID actorId,
            Instant decidedAt,
            String reason,
            String requestHash,
            String idempotencyKey
    ) {
        return decide(tenantId, candidateId, MemoryCandidateStatus.REJECTED, null, actorId, decidedAt,
                reason, requestHash, idempotencyKey);
    }

    @Override
    public Optional<MemoryItem> lockMemory(UUID tenantId, UUID memoryId) {
        return findMemory(tenantId, memoryId);
    }

    @Override
    public Optional<MemoryItem> findMemory(UUID tenantId, UUID memoryId) {
        return Optional.ofNullable(memories.get(memoryId)).filter(value -> value.tenantId().equals(tenantId));
    }

    @Override
    public Optional<MemoryVersion> findCorrectionByIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        return versions.stream()
                .filter(value -> value.tenantId().equals(tenantId))
                .filter(value -> value.createdBy().equals(actorId))
                .filter(value -> value.changeType() == MemoryVersionChangeType.CORRECTED)
                .filter(value -> value.idempotencyKey().equals(idempotencyKey))
                .findFirst();
    }

    @Override
    public Optional<MemoryItem> findForgetByIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        return memories.values().stream()
                .filter(value -> value.tenantId().equals(tenantId))
                .filter(value -> actorId.equals(value.forgottenBy()))
                .filter(value -> idempotencyKey.equals(value.forgetIdempotencyKey()))
                .findFirst();
    }

    @Override
    public void insertMemory(MemoryItem memory) {
        memories.put(memory.memoryId(), memory);
    }

    @Override
    public void insertVersion(MemoryVersion version) {
        versions.add(version);
    }

    @Override
    public boolean advanceMemoryVersion(
            UUID tenantId,
            UUID memoryId,
            long expectedVersion,
            String content,
            String semanticKey,
            Instant updatedAt
    ) {
        var current = memories.get(memoryId);
        if (current == null || !current.tenantId().equals(tenantId)
                || current.status() != MemoryItemStatus.ACTIVE || current.currentVersion() != expectedVersion) {
            return false;
        }
        memories.put(memoryId, copyMemory(
                current, MemoryItemStatus.ACTIVE, expectedVersion + 1, content, semanticKey, updatedAt,
                null, null, null, null, null
        ));
        return true;
    }

    @Override
    public boolean forgetMemory(
            UUID tenantId,
            UUID memoryId,
            long expectedVersion,
            UUID actorId,
            Instant forgottenAt,
            String reason,
            String requestHash,
            String idempotencyKey
    ) {
        var current = memories.get(memoryId);
        if (current == null || !current.tenantId().equals(tenantId)
                || current.status() != MemoryItemStatus.ACTIVE || current.currentVersion() != expectedVersion) {
            return false;
        }
        memories.put(memoryId, copyMemory(
                current, MemoryItemStatus.FORGOTTEN, current.currentVersion(), current.content(),
                current.semanticKey(), forgottenAt, actorId, forgottenAt, reason, requestHash, idempotencyKey
        ));
        return true;
    }

    @Override
    public long insertEvent(MemoryEvent event) {
        events.add(event);
        return nextEventSequence++;
    }

    @Override
    public void insertIndexJob(MemoryIndexJobWrite write) {
        if (!indexJobs.contains(write)) {
            indexJobs.add(write);
        }
    }

    @Override
    public List<MemoryItem> recallConfirmed(
            UUID tenantId,
            UUID enterpriseAgentId,
            List<MemoryScopeRef> scopes,
            String query,
            int limit
    ) {
        return memories.values().stream()
                .filter(value -> value.tenantId().equals(tenantId))
                .filter(value -> value.enterpriseAgentId().equals(enterpriseAgentId))
                .filter(value -> value.status() == MemoryItemStatus.ACTIVE)
                .filter(value -> scopes.contains(value.scope()))
                .filter(value -> value.content().toLowerCase().contains(query.toLowerCase()))
                .limit(limit)
                .toList();
    }

    @Override
    public List<MemoryAuthoritySnapshot> findAuthoritySnapshots(
            UUID tenantId,
            List<MemoryEvidenceKey> evidenceKeys
    ) {
        return evidenceKeys.stream()
                .map(key -> {
                    var memory = memories.get(key.memoryId());
                    if (memory == null || !memory.tenantId().equals(tenantId)) return null;
                    return new MemoryAuthoritySnapshot(
                            key,
                            memory.enterpriseAgentId(),
                            memory.scope(),
                            memory.status(),
                            memory.currentVersion(),
                            authoritySourceSequences.get(memory.memoryId())
                    );
                })
                .filter(java.util.Objects::nonNull)
                .toList();
    }

    private boolean decide(
            UUID tenantId,
            UUID candidateId,
            MemoryCandidateStatus status,
            UUID memoryId,
            UUID actorId,
            Instant decidedAt,
            String reason,
            String requestHash,
            String idempotencyKey
    ) {
        var current = candidates.get(candidateId);
        if (current == null || !current.tenantId().equals(tenantId)
                || current.status() != MemoryCandidateStatus.PENDING) {
            return false;
        }
        candidates.put(candidateId, new MemoryCandidate(
                current.candidateId(), current.tenantId(), current.enterpriseAgentId(), current.scope(),
                current.content(), current.semanticKey(), current.sourceConversationId(), current.sourceMessageId(),
                status, current.requestHash(), current.idempotencyKey(), current.proposedBy(), current.proposedAt(),
                actorId, decidedAt, reason, requestHash, idempotencyKey, memoryId
        ));
        return true;
    }

    private static MemoryItem copyMemory(
            MemoryItem current,
            MemoryItemStatus status,
            long version,
            String content,
            String semanticKey,
            Instant updatedAt,
            UUID forgottenBy,
            Instant forgottenAt,
            String forgetReason,
            String forgetRequestHash,
            String forgetIdempotencyKey
    ) {
        return new MemoryItem(
                current.memoryId(), current.tenantId(), current.enterpriseAgentId(), current.scope(), status,
                version, content, semanticKey, current.createdBy(), current.createdAt(), updatedAt,
                forgottenBy, forgottenAt, forgetReason, forgetRequestHash, forgetIdempotencyKey
        );
    }
}

package com.dianlian.platform.context.application;

import com.dianlian.platform.context.api.ContextIndexDispatch.AuthorityScope;
import com.dianlian.platform.context.api.ContextIndexDispatch.FailureDisposition;
import com.dianlian.platform.context.api.ContextIndexDispatch.IndexOperation;
import com.dianlian.platform.context.api.ContextIndexDispatch.IndexTarget;
import com.dianlian.platform.context.api.ContextIndexDispatch.MemoryScopeType;
import com.dianlian.platform.context.api.ContextIndexDispatch.RemoteReceipt;
import com.dianlian.platform.context.api.ContextIndexDispatch.ResourceType;
import java.time.Instant;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/**
 * Internal persistence port for the rebuildable context projection queue.
 */
public interface ContextIndexDispatchRepository {

    void deadLetterExhausted(int maxAttempts, Instant now);

    Optional<ClaimedIndexJob> claimNext(
            String workerId,
            IndexTarget indexTarget,
            String indexProfileVersion,
            int maxAttempts,
            Instant now,
            Instant leaseExpiresAt
    );

    Optional<KnowledgeAuthoritySnapshot> findKnowledgeAuthority(
            UUID tenantId,
            AuthorityScope authorityScope,
            UUID documentVersionId
    );

    Optional<MemoryAuthoritySnapshot> findMemoryAuthority(
            UUID tenantId,
            UUID memoryId,
            long requestedVersion
    );

    Optional<Instant> heartbeat(
            UUID jobId,
            String workerId,
            int attempt,
            long leaseEpoch,
            Instant now,
            Instant newLeaseExpiresAt
    );

    boolean complete(
            UUID jobId,
            String workerId,
            int attempt,
            long leaseEpoch,
            Instant now,
            RemoteReceipt receipt
    );

    Optional<FailureDisposition> fail(
            UUID jobId,
            String workerId,
            int attempt,
            long leaseEpoch,
            Instant now,
            Instant nextAttemptAt,
            int maxAttempts,
            boolean retryable,
            String errorCode,
            String errorMessage
    );

    record ClaimedIndexJob(
            UUID jobId,
            UUID tenantId,
            AuthorityScope authorityScope,
            ResourceType resourceType,
            UUID resourceId,
            long resourceVersion,
            long eventSequence,
            IndexTarget indexTarget,
            String indexProfileVersion,
            IndexOperation operation,
            String workerId,
            int attempt,
            long leaseEpoch,
            Instant leaseExpiresAt
    ) {

        public ClaimedIndexJob {
            Objects.requireNonNull(jobId);
            Objects.requireNonNull(authorityScope);
            Objects.requireNonNull(resourceType);
            Objects.requireNonNull(resourceId);
            Objects.requireNonNull(indexTarget);
            Objects.requireNonNull(indexProfileVersion);
            Objects.requireNonNull(operation);
            Objects.requireNonNull(workerId);
            Objects.requireNonNull(leaseExpiresAt);
        }
    }

    record KnowledgeAuthoritySnapshot(
            UUID tenantId,
            AuthorityScope authorityScope,
            UUID documentVersionId,
            UUID documentId,
            UUID currentVersionId,
            UUID spaceId,
            String spaceStatus,
            String documentStatus,
            String versionStatus,
            String accessState,
            long versionResourceVersion,
            long authorityEventSequence,
            String title,
            String objectKey,
            String contentHash,
            String normalizedText,
            String normalizedTextHash,
            String normalizationProfileVersion,
            Instant normalizedAt,
            String mimeType,
            long byteSize,
            String metadataJson
    ) {
    }

    record MemoryAuthoritySnapshot(
            UUID tenantId,
            UUID memoryId,
            long currentVersion,
            String itemStatus,
            long authorityEventSequence,
            Long requestedVersion,
            UUID enterpriseAgentId,
            MemoryScopeType scopeType,
            UUID scopeId,
            String content,
            String semanticKey,
            Long sourceMessageSequenceNo
    ) {
    }
}

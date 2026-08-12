package com.dianlian.platform.context.api;

import java.time.Duration;
import java.time.Instant;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * Persistent context projection dispatch boundary.
 *
 * <p>The caller must finish {@link #claimNext(ClaimRequest)} before invoking any external
 * index runtime, then acknowledge with {@link #complete(CompleteCommand)} or
 * {@link #fail(FailCommand)}. No external callback is accepted by this API, keeping network I/O
 * outside the database transaction.</p>
 */
public interface ContextIndexDispatch {

    String PROJECTION_CONTRACT_VERSION = "1.0";
    String DEFAULT_INDEX_PROFILE_VERSION = "context-default-v1";

    Optional<ClaimedProjection> claimNext(ClaimRequest request);

    ContextIndexLease heartbeat(HeartbeatCommand command);

    void complete(CompleteCommand command);

    FailureDisposition fail(FailCommand command);

    enum AuthorityScope {
        PLATFORM,
        TENANT
    }

    enum ResourceType {
        KNOWLEDGE_DOCUMENT_VERSION,
        MEMORY_ITEM_VERSION
    }

    enum IndexTarget {
        LEXICAL,
        VECTOR,
        GRAPH,
        CACHE,
        EXTERNAL_PROVIDER
    }

    enum IndexOperation {
        UPSERT,
        DELETE,
        VERIFY
    }

    enum MemoryScopeType {
        AGENT,
        USER_AGENT,
        GROUP_AGENT
    }

    enum TombstoneReason {
        REQUESTED_DELETE,
        AUTHORITY_NOT_FOUND,
        AUTHORITY_SCOPE_MISMATCH,
        AUTHORITY_NOT_ACTIVE,
        AUTHORITY_NOT_READY,
        RESOURCE_VERSION_NOT_CURRENT
    }

    enum ReceiptOutcome {
        APPLIED,
        ALREADY_APPLIED,
        IGNORED_STALE
    }

    enum FailureDisposition {
        RETRY_SCHEDULED,
        DEAD_LETTERED
    }

    record ClaimRequest(
            String workerId,
            IndexTarget indexTarget,
            String indexProfileVersion,
            Duration leaseDuration
    ) {

        public ClaimRequest {
            workerId = requireText(workerId, "workerId", 160);
            Objects.requireNonNull(indexTarget, "indexTarget must not be null");
            indexProfileVersion = requireText(indexProfileVersion, "indexProfileVersion", 100);
            leaseDuration = requireLeaseDuration(leaseDuration);
        }
    }

    record ContextIndexLease(
            UUID jobId,
            String workerId,
            int attempt,
            long leaseEpoch,
            long projectionEventSequence,
            Instant leaseExpiresAt
    ) {

        public ContextIndexLease {
            Objects.requireNonNull(jobId, "jobId must not be null");
            workerId = requireText(workerId, "workerId", 160);
            if (attempt <= 0) {
                throw new IllegalArgumentException("attempt must be positive");
            }
            requirePositive(leaseEpoch, "leaseEpoch");
            requirePositive(projectionEventSequence, "projectionEventSequence");
            Objects.requireNonNull(leaseExpiresAt, "leaseExpiresAt must not be null");
        }
    }

    record HeartbeatCommand(ContextIndexLease lease, Duration leaseDuration) {

        public HeartbeatCommand {
            Objects.requireNonNull(lease, "lease must not be null");
            leaseDuration = requireLeaseDuration(leaseDuration);
        }
    }

    record ClaimedProjection(ContextIndexLease lease, ProjectionPayload payload) {

        public ClaimedProjection {
            Objects.requireNonNull(lease, "lease must not be null");
            Objects.requireNonNull(payload, "payload must not be null");
            if (!lease.jobId().equals(payload.jobId())) {
                throw new IllegalArgumentException("lease and payload job ids must match");
            }
            if (lease.projectionEventSequence() != payload.eventSequence()) {
                throw new IllegalArgumentException("lease and payload event sequences must match");
            }
        }
    }

    record ProjectionPayload(
            String contractVersion,
            UUID jobId,
            UUID tenantId,
            AuthorityScope authorityScope,
            ResourceType resourceType,
            UUID resourceId,
            long resourceVersion,
            long eventSequence,
            IndexTarget indexTarget,
            String indexProfileVersion,
            IndexOperation queuedOperation,
            IndexOperation operation,
            ProjectionBody body
    ) {

        /**
         * Projection stores must compare the authority event sequence atomically. A higher sequence
         * wins, an exact replay must preserve the same operation and payload, and DELETE wins an
         * UPSERT race at the same sequence. The resource version describes the authority snapshot;
         * it is not a second cursor.
         *
         * <p>{@code resourceId} is the stable projection-job identity. For knowledge, the source
         * identity used by retrieval authorization is carried separately as
         * {@code documentId + documentVersionId} in {@link KnowledgeDocumentProjection}.</p>
         */

        public ProjectionPayload {
            if (!PROJECTION_CONTRACT_VERSION.equals(contractVersion)) {
                throw new IllegalArgumentException("unsupported projection contract version");
            }
            Objects.requireNonNull(jobId, "jobId must not be null");
            Objects.requireNonNull(authorityScope, "authorityScope must not be null");
            Objects.requireNonNull(resourceType, "resourceType must not be null");
            Objects.requireNonNull(resourceId, "resourceId must not be null");
            requirePositive(resourceVersion, "resourceVersion");
            requirePositive(eventSequence, "eventSequence");
            Objects.requireNonNull(indexTarget, "indexTarget must not be null");
            indexProfileVersion = requireText(indexProfileVersion, "indexProfileVersion", 100);
            Objects.requireNonNull(queuedOperation, "queuedOperation must not be null");
            Objects.requireNonNull(operation, "operation must not be null");
            Objects.requireNonNull(body, "body must not be null");
            if ((authorityScope == AuthorityScope.PLATFORM && tenantId != null)
                    || (authorityScope == AuthorityScope.TENANT && tenantId == null)) {
                throw new IllegalArgumentException("authority scope and tenant id do not match");
            }
            if (queuedOperation == IndexOperation.DELETE && operation != IndexOperation.DELETE) {
                throw new IllegalArgumentException("a queued DELETE cannot become a non-delete projection");
            }
            if (operation == IndexOperation.DELETE && !(body instanceof TombstoneProjection)) {
                throw new IllegalArgumentException("DELETE projection requires a tombstone body");
            }
            if (operation == IndexOperation.UPSERT && body instanceof TombstoneProjection) {
                throw new IllegalArgumentException("UPSERT projection cannot contain a tombstone body");
            }
            if (body instanceof KnowledgeDocumentProjection knowledge) {
                if (resourceType != ResourceType.KNOWLEDGE_DOCUMENT_VERSION
                        || !resourceId.equals(knowledge.documentVersionId())) {
                    throw new IllegalArgumentException("knowledge body does not match the projection resource");
                }
            }
            if (body instanceof MemoryItemProjection memory) {
                if (resourceType != ResourceType.MEMORY_ITEM_VERSION
                        || !resourceId.equals(memory.memoryId())
                        || resourceVersion != memory.versionNo()) {
                    throw new IllegalArgumentException("memory body does not match the projection resource");
                }
            }
        }
    }

    sealed interface ProjectionBody
            permits KnowledgeDocumentProjection, MemoryItemProjection, TombstoneProjection {
    }

    record KnowledgeDocumentProjection(
            UUID documentVersionId,
            UUID documentId,
            UUID spaceId,
            String title,
            String objectKey,
            String sourceContentHash,
            String normalizedText,
            String normalizedTextHash,
            String normalizationProfileVersion,
            Instant normalizedAt,
            String mimeType,
            long byteSize,
            String metadataJson
    ) implements ProjectionBody {

        private static final Pattern HASH = Pattern.compile("^[0-9a-f]{64,128}$");

        public KnowledgeDocumentProjection {
            Objects.requireNonNull(documentVersionId, "documentVersionId must not be null");
            Objects.requireNonNull(documentId, "documentId must not be null");
            Objects.requireNonNull(spaceId, "spaceId must not be null");
            title = requireText(title, "title", 500);
            objectKey = requireText(objectKey, "objectKey", 1_024);
            sourceContentHash = requireText(sourceContentHash, "sourceContentHash", 128);
            if (!HASH.matcher(sourceContentHash).matches()) {
                throw new IllegalArgumentException("sourceContentHash is invalid");
            }
            normalizedText = requireText(normalizedText, "normalizedText", Integer.MAX_VALUE);
            normalizedTextHash = requireText(normalizedTextHash, "normalizedTextHash", 64);
            if (!Pattern.compile("^[0-9a-f]{64}$").matcher(normalizedTextHash).matches()) {
                throw new IllegalArgumentException("normalizedTextHash must be lowercase SHA-256");
            }
            normalizationProfileVersion = requireText(
                    normalizationProfileVersion,
                    "normalizationProfileVersion",
                    100
            );
            Objects.requireNonNull(normalizedAt, "normalizedAt must not be null");
            mimeType = requireText(mimeType, "mimeType", 200);
            if (byteSize < 0) {
                throw new IllegalArgumentException("byteSize cannot be negative");
            }
            metadataJson = requireText(metadataJson, "metadataJson", Integer.MAX_VALUE);
        }
    }

    record MemoryItemProjection(
            UUID memoryId,
            long versionNo,
            UUID enterpriseAgentId,
            MemoryScopeType scopeType,
            UUID scopeId,
            String content,
            String semanticKey,
            Long sourceMessageSequenceNo
    ) implements ProjectionBody {

        public MemoryItemProjection {
            Objects.requireNonNull(memoryId, "memoryId must not be null");
            requirePositive(versionNo, "versionNo");
            Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
            Objects.requireNonNull(scopeType, "scopeType must not be null");
            Objects.requireNonNull(scopeId, "scopeId must not be null");
            content = requireText(content, "content", 8_000);
            semanticKey = normalizeNullable(semanticKey, 200, "semanticKey");
            if (sourceMessageSequenceNo != null && sourceMessageSequenceNo < 0) {
                throw new IllegalArgumentException("sourceMessageSequenceNo cannot be negative");
            }
        }
    }

    record TombstoneProjection(TombstoneReason reason) implements ProjectionBody {

        public TombstoneProjection {
            Objects.requireNonNull(reason, "reason must not be null");
        }
    }

    record RemoteReceipt(
            String receiptId,
            ReceiptOutcome outcome,
            long appliedEventSequence,
            String contentHash
    ) {

        private static final Pattern CONTENT_HASH = Pattern.compile("^[0-9a-f]{64,128}$");

        public RemoteReceipt {
            receiptId = requireText(receiptId, "receiptId", 200);
            Objects.requireNonNull(outcome, "outcome must not be null");
            requirePositive(appliedEventSequence, "appliedEventSequence");
            contentHash = normalizeNullable(contentHash, 128, "contentHash");
            if (contentHash != null && !CONTENT_HASH.matcher(contentHash).matches()) {
                throw new IllegalArgumentException("contentHash must be lowercase hexadecimal");
            }
        }
    }

    record CompleteCommand(ContextIndexLease lease, RemoteReceipt receipt) {

        public CompleteCommand {
            Objects.requireNonNull(lease, "lease must not be null");
            Objects.requireNonNull(receipt, "receipt must not be null");
            if (receipt.appliedEventSequence() < lease.projectionEventSequence()) {
                throw new IllegalArgumentException("receipt cursor cannot be older than the projected event");
            }
        }
    }

    record FailCommand(
            ContextIndexLease lease,
            String errorCode,
            String errorMessage,
            boolean retryable
    ) {

        public FailCommand {
            Objects.requireNonNull(lease, "lease must not be null");
            errorCode = requireText(errorCode, "errorCode", 100);
            errorMessage = requireText(errorMessage, "errorMessage", 2_000);
        }
    }

    private static Duration requireLeaseDuration(Duration duration) {
        Objects.requireNonNull(duration, "leaseDuration must not be null");
        if (duration.compareTo(Duration.ofSeconds(5)) < 0 || duration.compareTo(Duration.ofMinutes(15)) > 0) {
            throw new IllegalArgumentException("leaseDuration must be between 5 seconds and 15 minutes");
        }
        return duration;
    }

    private static String requireText(String value, String fieldName, int maxLength) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        var normalized = value.trim();
        if (normalized.isEmpty() || normalized.length() > maxLength) {
            throw new IllegalArgumentException(fieldName + " is invalid");
        }
        return normalized;
    }

    private static String normalizeNullable(String value, int maxLength, String fieldName) {
        if (value == null) {
            return null;
        }
        var normalized = value.trim();
        if (normalized.isEmpty()) {
            return null;
        }
        if (normalized.length() > maxLength) {
            throw new IllegalArgumentException(fieldName + " is too long");
        }
        return normalized;
    }

    private static void requirePositive(long value, String fieldName) {
        if (value <= 0) {
            throw new IllegalArgumentException(fieldName + " must be positive");
        }
    }
}

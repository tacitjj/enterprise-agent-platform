package com.dianlian.platform.context.api;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScope;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AuthorizedKnowledgeResource;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/**
 * Current Java authority boundary used by asynchronous context retrieval.
 *
 * <p>Implementations may consult knowledge and memory modules, but this API deliberately contains
 * no interactive access context and never returns resource content.</p>
 */
public interface ContextAuthorityPort {

    Authorization authorize(AuthorizationRequest request);

    Reauthorization reauthorize(ReauthorizationRequest request);

    record InvocationBoundary(
            UUID tenantId,
            UUID actorUserId,
            UUID enterpriseAgentId,
            UUID agentVersionId,
            UUID configurationVersionId,
            UUID conversationId,
            boolean groupConversation,
            UUID sourceMessageId,
            long sourceSequenceNo,
            long membershipVersion,
            String policyVersion,
            List<UUID> audienceUserIds,
            long historyFloorSequenceNo,
            Instant observedAt
    ) {
        public InvocationBoundary {
            Objects.requireNonNull(tenantId, "tenantId must not be null");
            Objects.requireNonNull(actorUserId, "actorUserId must not be null");
            Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
            Objects.requireNonNull(agentVersionId, "agentVersionId must not be null");
            Objects.requireNonNull(configurationVersionId, "configurationVersionId must not be null");
            Objects.requireNonNull(conversationId, "conversationId must not be null");
            Objects.requireNonNull(sourceMessageId, "sourceMessageId must not be null");
            if (sourceSequenceNo <= 0) {
                throw new IllegalArgumentException("sourceSequenceNo must be positive");
            }
            if (membershipVersion <= 0) {
                throw new IllegalArgumentException("membershipVersion must be positive");
            }
            policyVersion = requireText(policyVersion, "policyVersion", 64);
            audienceUserIds = List.copyOf(Objects.requireNonNull(
                    audienceUserIds,
                    "audienceUserIds must not be null"
            ));
            if (audienceUserIds.isEmpty() || audienceUserIds.size() > 500
                    || audienceUserIds.stream().anyMatch(Objects::isNull)
                    || audienceUserIds.stream().distinct().count() != audienceUserIds.size()
                    || !audienceUserIds.contains(actorUserId)) {
                throw new IllegalArgumentException("audienceUserIds must be unique and include actorUserId");
            }
            audienceUserIds = audienceUserIds.stream().sorted().toList();
            if (historyFloorSequenceNo < 0) {
                throw new IllegalArgumentException("historyFloorSequenceNo cannot be negative");
            }
            Objects.requireNonNull(observedAt, "observedAt must not be null");
        }
    }

    record AuthorizationRequest(
            InvocationBoundary invocation,
            boolean knowledgeEnabled,
            boolean memoryEnabled,
            int knowledgeLimit
    ) {
        public AuthorizationRequest {
            Objects.requireNonNull(invocation, "invocation must not be null");
            if (knowledgeLimit <= 0 || knowledgeLimit > 2_000) {
                throw new IllegalArgumentException("knowledgeLimit must be between 1 and 2000");
            }
        }
    }

    record Authorization(
            boolean accepted,
            String rejectionCode,
            List<AuthorizedKnowledgeResource> knowledgeResources,
            List<AllowedMemoryScope> memoryScopes
    ) {
        public Authorization {
            knowledgeResources = List.copyOf(Objects.requireNonNull(
                    knowledgeResources,
                    "knowledgeResources must not be null"
            ));
            memoryScopes = List.copyOf(Objects.requireNonNull(memoryScopes, "memoryScopes must not be null"));
            if (accepted == (rejectionCode != null)) {
                throw new IllegalArgumentException("authorization state is invalid");
            }
            if (!accepted && (!knowledgeResources.isEmpty() || !memoryScopes.isEmpty())) {
                throw new IllegalArgumentException("rejected authorization cannot contain authority data");
            }
        }
    }

    record ReauthorizationRequest(
            InvocationBoundary invocation,
            List<EvidenceIdentity> actualEvidence
    ) {
        public ReauthorizationRequest {
            Objects.requireNonNull(invocation, "invocation must not be null");
            actualEvidence = List.copyOf(Objects.requireNonNull(actualEvidence, "actualEvidence must not be null"));
            if (actualEvidence.size() > 100 || actualEvidence.stream().anyMatch(Objects::isNull)) {
                throw new IllegalArgumentException("actualEvidence size is invalid");
            }
        }
    }

    record Reauthorization(
            boolean contractAccepted,
            String rejectionCode,
            List<EvidenceIdentity> allowedEvidence,
            List<EvidenceRejection> rejectedEvidence
    ) {
        public Reauthorization {
            allowedEvidence = List.copyOf(Objects.requireNonNull(allowedEvidence, "allowedEvidence must not be null"));
            rejectedEvidence = List.copyOf(Objects.requireNonNull(
                    rejectedEvidence,
                    "rejectedEvidence must not be null"
            ));
            if (contractAccepted == (rejectionCode != null)) {
                throw new IllegalArgumentException("reauthorization state is invalid");
            }
            if (!contractAccepted && (!allowedEvidence.isEmpty() || !rejectedEvidence.isEmpty())) {
                throw new IllegalArgumentException("rejected contract cannot contain evidence results");
            }
        }
    }

    record EvidenceIdentity(
            String evidenceId,
            RequestedSource sourceType,
            UUID sourceId,
            String sourceVersion,
            String chunkId,
            String contentHash,
            String citation
    ) {
        public EvidenceIdentity {
            evidenceId = requireText(evidenceId, "evidenceId", 200);
            Objects.requireNonNull(sourceType, "sourceType must not be null");
            Objects.requireNonNull(sourceId, "sourceId must not be null");
            sourceVersion = requireText(sourceVersion, "sourceVersion", 200);
            chunkId = requireText(chunkId, "chunkId", 200);
            contentHash = requireText(contentHash, "contentHash", 64);
            if (!contentHash.matches("^[0-9a-f]{64}$")) {
                throw new IllegalArgumentException("contentHash must be lowercase SHA-256");
            }
            citation = requireText(citation, "citation", 1_000);
        }
    }

    record EvidenceRejection(String evidenceId, String reasonCode) {
        public EvidenceRejection {
            evidenceId = requireText(evidenceId, "evidenceId", 200);
            reasonCode = requireText(reasonCode, "reasonCode", 128);
        }
    }

    private static String requireText(String value, String fieldName, int maxLength) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        var normalized = value.trim();
        if (normalized.isEmpty() || normalized.length() > maxLength) {
            throw new IllegalArgumentException(fieldName + " is invalid");
        }
        return normalized;
    }
}

package com.dianlian.platform.memory.api;

import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/**
 * Current memory authority for an already accepted asynchronous AI invocation.
 *
 * <p>This boundary never accepts or manufactures an authenticated user context. Callers must
 * pass the frozen invocation audience and execution identity, which are checked again against
 * current business authority before scopes or evidence are returned.</p>
 */
public interface InvocationMemoryAuthoritySource {

    AuthorizeScopesResult authorizeScopes(AuthorizeScopesQuery query);

    ReauthorizationResult reauthorize(ReauthorizeQuery query);

    enum RejectionCode {
        AUTHORITY_BOUNDARY_UNAVAILABLE,
        INVOCATION_BOUNDARY_DENIED,
        GROUP_PRIVATE_SCOPE_CONTRACT_VIOLATION,
        MEMORY_NOT_FOUND,
        MEMORY_NOT_ACTIVE,
        MEMORY_VERSION_NOT_CURRENT,
        MEMORY_AGENT_MISMATCH,
        MEMORY_SCOPE_NOT_ALLOWED,
        GROUP_MEMORY_SOURCE_SEQUENCE_MISSING,
        GROUP_MEMORY_BEFORE_HISTORY_FLOOR
    }

    record AuthorizeScopesQuery(
            UUID tenantId,
            UUID actorUserId,
            UUID enterpriseAgentId,
            UUID conversationId,
            boolean groupConversation,
            List<UUID> audienceUserIds,
            long historyFloorSequenceNo,
            Instant observedAt
    ) {
        public AuthorizeScopesQuery {
            Objects.requireNonNull(tenantId, "tenantId must not be null");
            Objects.requireNonNull(actorUserId, "actorUserId must not be null");
            Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
            Objects.requireNonNull(conversationId, "conversationId must not be null");
            audienceUserIds = List.copyOf(Objects.requireNonNull(
                    audienceUserIds,
                    "audienceUserIds must not be null"
            ));
            if (audienceUserIds.isEmpty() || audienceUserIds.size() > 500) {
                throw new IllegalArgumentException("audienceUserIds must contain between 1 and 500 entries");
            }
            if (audienceUserIds.stream().anyMatch(Objects::isNull)
                    || new HashSet<>(audienceUserIds).size() != audienceUserIds.size()) {
                throw new IllegalArgumentException("audienceUserIds must contain unique non-null entries");
            }
            if (!audienceUserIds.contains(actorUserId)) {
                throw new IllegalArgumentException("audienceUserIds must include actorUserId");
            }
            if (historyFloorSequenceNo < 0) {
                throw new IllegalArgumentException("historyFloorSequenceNo cannot be negative");
            }
            Objects.requireNonNull(observedAt, "observedAt must not be null");
        }
    }

    record AuthorizedMemoryScope(
            UUID tenantId,
            MemoryScopeType scopeType,
            UUID scopeId,
            UUID enterpriseAgentId,
            long historyFloorSequenceNo
    ) {
        public AuthorizedMemoryScope {
            Objects.requireNonNull(tenantId, "tenantId must not be null");
            Objects.requireNonNull(scopeType, "scopeType must not be null");
            Objects.requireNonNull(scopeId, "scopeId must not be null");
            Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
            if (historyFloorSequenceNo < 0) {
                throw new IllegalArgumentException("historyFloorSequenceNo cannot be negative");
            }
        }
    }

    record AuthorizeScopesResult(
            boolean authorized,
            List<AuthorizedMemoryScope> scopes,
            RejectionCode rejectionCode
    ) {
        public AuthorizeScopesResult {
            scopes = List.copyOf(Objects.requireNonNull(scopes, "scopes must not be null"));
            if (authorized == scopes.isEmpty()) {
                throw new IllegalArgumentException("authorized scope result has an invalid state");
            }
            if (authorized == (rejectionCode != null)) {
                throw new IllegalArgumentException("authorized scope result has an invalid rejection code");
            }
        }

        public static AuthorizeScopesResult allowed(List<AuthorizedMemoryScope> scopes) {
            return new AuthorizeScopesResult(true, scopes, null);
        }

        public static AuthorizeScopesResult denied(RejectionCode code) {
            return new AuthorizeScopesResult(false, List.of(), Objects.requireNonNull(code));
        }
    }

    record MemoryEvidenceKey(UUID memoryId, long versionNo) {
        public MemoryEvidenceKey {
            Objects.requireNonNull(memoryId, "memoryId must not be null");
            if (versionNo <= 0) {
                throw new IllegalArgumentException("versionNo must be positive");
            }
        }
    }

    record ReauthorizeQuery(
            AuthorizeScopesQuery invocation,
            List<MemoryEvidenceKey> evidenceKeys
    ) {
        public ReauthorizeQuery {
            Objects.requireNonNull(invocation, "invocation must not be null");
            evidenceKeys = List.copyOf(Objects.requireNonNull(evidenceKeys, "evidenceKeys must not be null"));
            if (evidenceKeys.isEmpty() || evidenceKeys.size() > 100) {
                throw new IllegalArgumentException("evidenceKeys must contain between 1 and 100 entries");
            }
            if (new HashSet<>(evidenceKeys).size() != evidenceKeys.size()) {
                throw new IllegalArgumentException("evidenceKeys must not contain duplicates");
            }
        }
    }

    record AuthorizedMemoryEvidence(MemoryEvidenceKey key, MemoryScopeRef scope) {
        public AuthorizedMemoryEvidence {
            Objects.requireNonNull(key, "key must not be null");
            Objects.requireNonNull(scope, "scope must not be null");
        }
    }

    record RejectedMemoryEvidence(MemoryEvidenceKey key, RejectionCode rejectionCode) {
        public RejectedMemoryEvidence {
            Objects.requireNonNull(key, "key must not be null");
            Objects.requireNonNull(rejectionCode, "rejectionCode must not be null");
        }
    }

    record ReauthorizationResult(
            boolean contractAccepted,
            RejectionCode contractRejectionCode,
            List<AuthorizedMemoryEvidence> allowed,
            List<RejectedMemoryEvidence> rejected
    ) {
        public ReauthorizationResult {
            allowed = List.copyOf(Objects.requireNonNull(allowed, "allowed must not be null"));
            rejected = List.copyOf(Objects.requireNonNull(rejected, "rejected must not be null"));
            if (contractAccepted == (contractRejectionCode != null)) {
                throw new IllegalArgumentException("reauthorization contract state is invalid");
            }
            if (!contractAccepted && (!allowed.isEmpty() || !rejected.isEmpty())) {
                throw new IllegalArgumentException("rejected contract cannot contain evidence results");
            }
        }
    }
}

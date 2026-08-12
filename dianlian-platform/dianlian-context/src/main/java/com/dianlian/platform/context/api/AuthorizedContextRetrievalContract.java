package com.dianlian.platform.context.api;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * Stable anti-corruption contract between Java authorization and the Python retrieval runtime.
 */
public final class AuthorizedContextRetrievalContract {

    public static final String B0_CONTRACT_VERSION = "1.0";

    private static final Pattern CONTRACT_VERSION = Pattern.compile("^1\\.[0-9]+$");
    private static final Pattern SHA_256 = Pattern.compile("^[0-9a-f]{64}$");

    private AuthorizedContextRetrievalContract() {
    }

    public enum RequestedSource {
        KNOWLEDGE,
        MEMORY
    }

    /**
     * Memory scopes authorized for the B0 runtime boundary. Future scopes require a contract revision.
     */
    public enum AllowedMemoryScopeType {
        AGENT,
        USER_AGENT,
        GROUP_AGENT
    }

    public enum ContextSourceState {
        READY,
        EMPTY,
        UNAVAILABLE,
        FORBIDDEN
    }

    public record AuthorizedKnowledgeResource(
            UUID tenantId,
            UUID resourceId,
            UUID resourceVersionId
    ) {
        public AuthorizedKnowledgeResource {
            Objects.requireNonNull(tenantId, "tenantId must not be null");
            Objects.requireNonNull(resourceId, "resourceId must not be null");
            Objects.requireNonNull(resourceVersionId, "resourceVersionId must not be null");
        }
    }

    public record AllowedMemoryScope(
            UUID tenantId,
            AllowedMemoryScopeType scopeType,
            UUID scopeId,
            UUID enterpriseAgentId,
            long historyFloorSequenceNo
    ) {
        public AllowedMemoryScope {
            Objects.requireNonNull(tenantId, "tenantId must not be null");
            Objects.requireNonNull(scopeType, "scopeType must not be null");
            Objects.requireNonNull(scopeId, "scopeId must not be null");
            Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
            if (historyFloorSequenceNo < 0) {
                throw new IllegalArgumentException("historyFloorSequenceNo cannot be negative");
            }
        }
    }

    public record RetrievalPolicy(
            int lexicalTopK,
            int vectorTopK,
            int rerankTopK,
            int maxEvidence,
            int maxContextTokens
    ) {
        public RetrievalPolicy {
            requireRange(lexicalTopK, 1, 100, "lexicalTopK");
            requireRange(vectorTopK, 1, 100, "vectorTopK");
            requireRange(rerankTopK, 1, 100, "rerankTopK");
            requireRange(maxEvidence, 1, 100, "maxEvidence");
            requireRange(maxContextTokens, 128, 131_072, "maxContextTokens");
            if (rerankTopK > lexicalTopK + vectorTopK) {
                throw new IllegalArgumentException("rerankTopK cannot exceed the combined candidate limit");
            }
            if (maxEvidence > rerankTopK) {
                throw new IllegalArgumentException("maxEvidence cannot exceed rerankTopK");
            }
        }
    }

    public record ContextRetrievalRequest(
            String contractVersion,
            UUID requestId,
            UUID traceId,
            Instant deadlineAt,
            UUID tenantId,
            UUID actorUserId,
            UUID enterpriseAgentId,
            UUID conversationId,
            String query,
            List<UUID> audienceUserIds,
            List<AuthorizedKnowledgeResource> authorizedKnowledgeResources,
            List<AllowedMemoryScope> allowedMemoryScopes,
            List<RequestedSource> requestedSources,
            RetrievalPolicy policy,
            String authorizationSnapshotHash
    ) {
        public ContextRetrievalRequest {
            contractVersion = requireContractVersion(contractVersion);
            Objects.requireNonNull(requestId, "requestId must not be null");
            Objects.requireNonNull(traceId, "traceId must not be null");
            Objects.requireNonNull(deadlineAt, "deadlineAt must not be null");
            Objects.requireNonNull(tenantId, "tenantId must not be null");
            Objects.requireNonNull(actorUserId, "actorUserId must not be null");
            Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
            Objects.requireNonNull(conversationId, "conversationId must not be null");
            query = requireText(query, "query", 20_000);
            audienceUserIds = requireList(audienceUserIds, "audienceUserIds", 1, 500);
            requireUnique(audienceUserIds, "audienceUserIds must not contain duplicates");
            authorizedKnowledgeResources = requireList(
                    authorizedKnowledgeResources,
                    "authorizedKnowledgeResources",
                    0,
                    2_000
            );
            allowedMemoryScopes = requireList(allowedMemoryScopes, "allowedMemoryScopes", 0, 100);
            requestedSources = requireList(requestedSources, "requestedSources", 1, 2);
            requireUnique(requestedSources, "requestedSources must not contain duplicates");
            Objects.requireNonNull(policy, "policy must not be null");
            authorizationSnapshotHash = requireSha256(authorizationSnapshotHash, "authorizationSnapshotHash");

            Set<RequestedSource> requested = Set.copyOf(requestedSources);
            if (requested.contains(RequestedSource.KNOWLEDGE) && authorizedKnowledgeResources.isEmpty()) {
                throw new IllegalArgumentException("KNOWLEDGE retrieval requires an explicit resource allowlist");
            }
            if (requested.contains(RequestedSource.MEMORY) && allowedMemoryScopes.isEmpty()) {
                throw new IllegalArgumentException("MEMORY retrieval requires an explicit scope allowlist");
            }

            var knowledgeKeys = new HashSet<KnowledgeResourceKey>();
            for (var resource : authorizedKnowledgeResources) {
                if (!tenantId.equals(resource.tenantId())) {
                    throw new IllegalArgumentException(
                            "authorized knowledge resource tenant does not match request tenant"
                    );
                }
                if (!knowledgeKeys.add(new KnowledgeResourceKey(resource.resourceId(), resource.resourceVersionId()))) {
                    throw new IllegalArgumentException("authorizedKnowledgeResources must not contain duplicates");
                }
            }

            var memoryKeys = new HashSet<MemoryScopeKey>();
            for (var scope : allowedMemoryScopes) {
                if (!tenantId.equals(scope.tenantId())) {
                    throw new IllegalArgumentException("allowed memory scope tenant does not match request tenant");
                }
                if (!enterpriseAgentId.equals(scope.enterpriseAgentId())) {
                    throw new IllegalArgumentException("allowed memory scope agent does not match request agent");
                }
                if (!memoryKeys.add(new MemoryScopeKey(
                        scope.scopeType(),
                        scope.scopeId(),
                        scope.historyFloorSequenceNo()
                ))) {
                    throw new IllegalArgumentException("allowedMemoryScopes must not contain duplicates");
                }
            }
        }
    }

    public record ContextEvidence(
            String evidenceId,
            RequestedSource sourceType,
            UUID sourceId,
            String sourceVersion,
            String chunkId,
            String title,
            String excerpt,
            String contentHash,
            double score,
            String citation
    ) {
        public ContextEvidence {
            evidenceId = requireText(evidenceId, "evidenceId", 200);
            Objects.requireNonNull(sourceType, "sourceType must not be null");
            Objects.requireNonNull(sourceId, "sourceId must not be null");
            sourceVersion = requireText(sourceVersion, "sourceVersion", 200);
            chunkId = requireText(chunkId, "chunkId", 200);
            title = requireText(title, "title", 500);
            excerpt = requireText(excerpt, "excerpt", 2_000);
            contentHash = requireSha256(contentHash, "contentHash");
            if (!Double.isFinite(score) || score < 0 || score > 1) {
                throw new IllegalArgumentException("score must be between 0 and 1");
            }
            citation = requireText(citation, "citation", 1_000);
        }
    }

    public record ContextSourceBundle(
            ContextSourceState state,
            String reasonCode,
            List<ContextEvidence> evidence
    ) {
        public ContextSourceBundle {
            Objects.requireNonNull(state, "state must not be null");
            evidence = requireList(evidence, "evidence", 0, 100);
            if (state == ContextSourceState.READY) {
                if (evidence.isEmpty()) {
                    throw new IllegalArgumentException("READY context source must include evidence");
                }
                if (reasonCode != null) {
                    throw new IllegalArgumentException("READY context source cannot include reasonCode");
                }
            } else {
                if (!evidence.isEmpty()) {
                    throw new IllegalArgumentException("non-ready context source cannot include evidence");
                }
                reasonCode = requireText(reasonCode, "reasonCode", 128);
            }
        }
    }

    public record RetrievalTrace(
            List<String> strategies,
            long candidateCount,
            long rerankedCount,
            String indexVersion,
            long elapsedMs
    ) {
        public RetrievalTrace {
            strategies = requireTextList(strategies, "strategies", 1, 10);
            requireNonNegative(candidateCount, "candidateCount");
            requireNonNegative(rerankedCount, "rerankedCount");
            indexVersion = requireText(indexVersion, "indexVersion", 200);
            requireNonNegative(elapsedMs, "elapsedMs");
        }
    }

    public record ContextBundle(
            String contractVersion,
            UUID requestId,
            String retrievalSnapshotId,
            Instant generatedAt,
            ContextSourceBundle knowledge,
            ContextSourceBundle memory,
            RetrievalTrace retrievalTrace
    ) {
        public ContextBundle {
            contractVersion = requireContractVersion(contractVersion);
            Objects.requireNonNull(requestId, "requestId must not be null");
            retrievalSnapshotId = requireText(retrievalSnapshotId, "retrievalSnapshotId", 200);
            Objects.requireNonNull(generatedAt, "generatedAt must not be null");
            Objects.requireNonNull(knowledge, "knowledge must not be null");
            Objects.requireNonNull(memory, "memory must not be null");
            Objects.requireNonNull(retrievalTrace, "retrievalTrace must not be null");
        }
    }

    private record KnowledgeResourceKey(UUID resourceId, UUID resourceVersionId) {
    }

    private record MemoryScopeKey(
            AllowedMemoryScopeType scopeType,
            UUID scopeId,
            long historyFloorSequenceNo
    ) {
    }

    private static String requireContractVersion(String value) {
        var normalized = requireText(value, "contractVersion", 20);
        if (!CONTRACT_VERSION.matcher(normalized).matches()) {
            throw new IllegalArgumentException("contractVersion must be a 1.x version");
        }
        return normalized;
    }

    private static String requireSha256(String value, String fieldName) {
        var normalized = requireText(value, fieldName, 64);
        if (!SHA_256.matcher(normalized).matches()) {
            throw new IllegalArgumentException(fieldName + " must be a lowercase SHA-256 hex value");
        }
        return normalized;
    }

    private static String requireText(String value, String fieldName, int maxLength) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        var normalized = value.trim();
        if (normalized.isEmpty() || normalized.length() > maxLength) {
            throw new IllegalArgumentException(fieldName + " is invalid");
        }
        return normalized;
    }

    private static <T> List<T> requireList(List<T> value, String fieldName, int minSize, int maxSize) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        var copy = List.copyOf(value);
        if (copy.size() < minSize || copy.size() > maxSize) {
            throw new IllegalArgumentException(fieldName + " size is invalid");
        }
        return copy;
    }

    private static List<String> requireTextList(
            List<String> value,
            String fieldName,
            int minSize,
            int maxSize
    ) {
        var copy = requireList(value, fieldName, minSize, maxSize);
        var normalized = new ArrayList<String>(copy.size());
        for (var item : copy) {
            normalized.add(requireText(item, fieldName + " item", Integer.MAX_VALUE));
        }
        return List.copyOf(normalized);
    }

    private static <T> void requireUnique(List<T> value, String message) {
        if (new HashSet<>(value).size() != value.size()) {
            throw new IllegalArgumentException(message);
        }
    }

    private static void requireRange(int value, int min, int max, String fieldName) {
        if (value < min || value > max) {
            throw new IllegalArgumentException(fieldName + " is outside the supported range");
        }
    }

    private static void requireNonNegative(long value, String fieldName) {
        if (value < 0) {
            throw new IllegalArgumentException(fieldName + " cannot be negative");
        }
    }
}

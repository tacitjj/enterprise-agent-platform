package com.dianlian.platform.integration.infrastructure.context;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScope;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScopeType;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AuthorizedKnowledgeResource;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextBundle;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextEvidence;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextRetrievalRequest;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextSourceBundle;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextSourceState;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RetrievalTrace;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

final class ContextRetrievalHttpContract {

    private ContextRetrievalHttpContract() {
    }

    static HttpContextRetrievalRequest request(ContextRetrievalRequest request) {
        Objects.requireNonNull(request, "request must not be null");
        return new HttpContextRetrievalRequest(
                request.contractVersion(),
                request.requestId(),
                request.traceId(),
                request.deadlineAt(),
                request.tenantId(),
                request.actorUserId(),
                request.enterpriseAgentId(),
                request.conversationId(),
                request.query(),
                request.audienceUserIds(),
                request.authorizedKnowledgeResources().stream()
                        .map(ContextRetrievalHttpContract::knowledgeResource)
                        .toList(),
                request.allowedMemoryScopes().stream()
                        .map(ContextRetrievalHttpContract::memoryScope)
                        .toList(),
                request.requestedSources(),
                new HttpRetrievalPolicy(
                        request.policy().lexicalTopK(),
                        request.policy().vectorTopK(),
                        request.policy().rerankTopK(),
                        request.policy().maxEvidence(),
                        request.policy().maxContextTokens()
                ),
                request.authorizationSnapshotHash()
        );
    }

    static ContextBundle response(HttpContextBundle response) {
        Objects.requireNonNull(response, "response must not be null");
        return new ContextBundle(
                response.contractVersion(),
                response.requestId(),
                response.retrievalSnapshotId(),
                response.generatedAt(),
                sourceBundle(response.knowledge()),
                sourceBundle(response.memory()),
                retrievalTrace(response.retrievalTrace())
        );
    }

    private static HttpAuthorizedKnowledgeResource knowledgeResource(AuthorizedKnowledgeResource resource) {
        return new HttpAuthorizedKnowledgeResource(
                resource.tenantId(),
                resource.resourceId(),
                resource.resourceVersionId()
        );
    }

    private static HttpAllowedMemoryScope memoryScope(AllowedMemoryScope scope) {
        return new HttpAllowedMemoryScope(
                scope.tenantId(),
                scope.scopeType(),
                scope.scopeId(),
                scope.enterpriseAgentId(),
                scope.historyFloorSequenceNo()
        );
    }

    private static ContextSourceBundle sourceBundle(HttpContextSourceBundle source) {
        Objects.requireNonNull(source, "context source bundle must not be null");
        Objects.requireNonNull(source.evidence(), "context evidence must not be null");
        return new ContextSourceBundle(
                source.state(),
                source.reasonCode(),
                source.evidence().stream().map(ContextRetrievalHttpContract::evidence).toList()
        );
    }

    private static ContextEvidence evidence(HttpContextEvidence evidence) {
        Objects.requireNonNull(evidence, "context evidence must not be null");
        Objects.requireNonNull(evidence.score(), "context evidence score must not be null");
        return new ContextEvidence(
                evidence.evidenceId(),
                evidence.sourceType(),
                evidence.sourceId(),
                evidence.sourceVersion(),
                evidence.chunkId(),
                evidence.title(),
                evidence.excerpt(),
                evidence.contentHash(),
                evidence.score(),
                evidence.citation()
        );
    }

    private static RetrievalTrace retrievalTrace(HttpRetrievalTrace trace) {
        Objects.requireNonNull(trace, "retrieval trace must not be null");
        Objects.requireNonNull(trace.candidateCount(), "candidateCount must not be null");
        Objects.requireNonNull(trace.rerankedCount(), "rerankedCount must not be null");
        Objects.requireNonNull(trace.elapsedMs(), "elapsedMs must not be null");
        return new RetrievalTrace(
                trace.strategies(),
                trace.candidateCount(),
                trace.rerankedCount(),
                trace.indexVersion(),
                trace.elapsedMs()
        );
    }

    record HttpContextRetrievalRequest(
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
            List<HttpAuthorizedKnowledgeResource> authorizedKnowledgeResources,
            List<HttpAllowedMemoryScope> allowedMemoryScopes,
            List<RequestedSource> requestedSources,
            HttpRetrievalPolicy policy,
            String authorizationSnapshotHash
    ) {
    }

    record HttpAuthorizedKnowledgeResource(
            UUID tenantId,
            UUID resourceId,
            UUID resourceVersionId
    ) {
    }

    record HttpAllowedMemoryScope(
            UUID tenantId,
            AllowedMemoryScopeType scopeType,
            UUID scopeId,
            UUID enterpriseAgentId,
            long historyFloorSequenceNo
    ) {
    }

    record HttpRetrievalPolicy(
            int lexicalTopK,
            int vectorTopK,
            int rerankTopK,
            int maxEvidence,
            int maxContextTokens
    ) {
    }

    record HttpContextBundle(
            String contractVersion,
            UUID requestId,
            String retrievalSnapshotId,
            Instant generatedAt,
            HttpContextSourceBundle knowledge,
            HttpContextSourceBundle memory,
            HttpRetrievalTrace retrievalTrace
    ) {
    }

    record HttpContextSourceBundle(
            ContextSourceState state,
            String reasonCode,
            List<HttpContextEvidence> evidence
    ) {
    }

    record HttpContextEvidence(
            String evidenceId,
            RequestedSource sourceType,
            UUID sourceId,
            String sourceVersion,
            String chunkId,
            String title,
            String excerpt,
            String contentHash,
            Double score,
            String citation
    ) {
    }

    record HttpRetrievalTrace(
            List<String> strategies,
            Long candidateCount,
            Long rerankedCount,
            String indexVersion,
            Long elapsedMs
    ) {
    }
}

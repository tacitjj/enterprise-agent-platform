package com.dianlian.platform.context.api;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RetrievalTrace;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record FencedAgentContext(
        AgentContextBundle context,
        String authorizationSnapshotHash,
        UUID retrievalRequestId,
        String retrievalSnapshotId,
        RetrievalTrace retrievalTrace,
        List<ContextAuthorityPort.EvidenceIdentity> evidence,
        String knowledgeReasonCode,
        String memoryReasonCode,
        Instant fencedAt
) {
    public FencedAgentContext {
        Objects.requireNonNull(context, "context must not be null");
        authorizationSnapshotHash = Objects.requireNonNull(authorizationSnapshotHash);
        Objects.requireNonNull(retrievalRequestId, "retrievalRequestId must not be null");
        retrievalSnapshotId = Objects.requireNonNull(retrievalSnapshotId).trim();
        Objects.requireNonNull(retrievalTrace, "retrievalTrace must not be null");
        evidence = List.copyOf(Objects.requireNonNull(evidence, "evidence must not be null"));
        Objects.requireNonNull(fencedAt, "fencedAt must not be null");
    }
}

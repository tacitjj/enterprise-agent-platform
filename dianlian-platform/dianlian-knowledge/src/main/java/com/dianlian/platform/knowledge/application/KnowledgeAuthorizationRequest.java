package com.dianlian.platform.knowledge.application;

import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record KnowledgeAuthorizationRequest(
        UUID tenantId,
        UUID agentVersionId,
        UUID enterpriseAgentId,
        UUID configurationVersionId,
        List<UUID> audienceUserIds,
        int limit,
        Instant observedAt
) {
    public KnowledgeAuthorizationRequest {
        Objects.requireNonNull(tenantId);
        Objects.requireNonNull(agentVersionId);
        Objects.requireNonNull(enterpriseAgentId);
        Objects.requireNonNull(configurationVersionId);
        audienceUserIds = List.copyOf(audienceUserIds);
        Objects.requireNonNull(observedAt);
    }
}

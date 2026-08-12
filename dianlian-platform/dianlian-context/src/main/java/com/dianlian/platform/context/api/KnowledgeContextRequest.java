package com.dianlian.platform.context.api;

import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record KnowledgeContextRequest(
        UUID tenantId,
        UUID enterpriseAgentId,
        UUID conversationId,
        List<UUID> audienceUserIds,
        String query
) {
    public KnowledgeContextRequest {
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(conversationId, "conversationId must not be null");
        audienceUserIds = List.copyOf(Objects.requireNonNull(audienceUserIds, "audienceUserIds must not be null"));
        query = Objects.requireNonNull(query, "query must not be null").trim();
        if (query.isEmpty()) {
            throw new IllegalArgumentException("query must not be blank");
        }
    }
}

package com.dianlian.platform.knowledge.api;

import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record ResolveAuthorizedKnowledgeResourcesQuery(
        UUID agentVersionId,
        UUID enterpriseAgentId,
        UUID configurationVersionId,
        List<UUID> audienceUserIds,
        int limit
) {
    public ResolveAuthorizedKnowledgeResourcesQuery {
        Objects.requireNonNull(agentVersionId, "agentVersionId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(configurationVersionId, "configurationVersionId must not be null");
        audienceUserIds = List.copyOf(Objects.requireNonNull(audienceUserIds, "audienceUserIds must not be null"));
        if (audienceUserIds.isEmpty() || audienceUserIds.size() > 500) {
            throw new IllegalArgumentException("audienceUserIds must contain between 1 and 500 entries");
        }
        if (audienceUserIds.stream().anyMatch(Objects::isNull)) {
            throw new IllegalArgumentException("audienceUserIds must not contain null");
        }
        if (new HashSet<>(audienceUserIds).size() != audienceUserIds.size()) {
            throw new IllegalArgumentException("audienceUserIds must not contain duplicates");
        }
        if (limit <= 0 || limit > 2000) {
            throw new IllegalArgumentException("limit must be between 1 and 2000");
        }
    }
}

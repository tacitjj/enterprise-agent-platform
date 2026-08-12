package com.dianlian.platform.context.api;

import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record MemoryContextRequest(
        UUID tenantId,
        UUID actorUserId,
        UUID enterpriseAgentId,
        UUID conversationId,
        boolean groupConversation,
        long historyFloorSequenceNo,
        List<UUID> audienceUserIds,
        List<MemoryScopeRef> allowedScopes,
        String query
) {
    public MemoryContextRequest {
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(actorUserId, "actorUserId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(conversationId, "conversationId must not be null");
        if (historyFloorSequenceNo < 0) {
            throw new IllegalArgumentException("historyFloorSequenceNo cannot be negative");
        }
        audienceUserIds = List.copyOf(Objects.requireNonNull(audienceUserIds, "audienceUserIds must not be null"));
        if (audienceUserIds.isEmpty()) {
            throw new IllegalArgumentException("audienceUserIds must not be empty");
        }
        allowedScopes = List.copyOf(Objects.requireNonNull(allowedScopes, "allowedScopes must not be null"));
        if (allowedScopes.isEmpty()) {
            throw new IllegalArgumentException("allowedScopes must not be empty");
        }
        query = Objects.requireNonNull(query, "query must not be null").trim();
        if (query.isEmpty()) {
            throw new IllegalArgumentException("query must not be blank");
        }
    }
}

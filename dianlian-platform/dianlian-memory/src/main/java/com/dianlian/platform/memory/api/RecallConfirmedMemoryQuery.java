package com.dianlian.platform.memory.api;

import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record RecallConfirmedMemoryQuery(
        UUID enterpriseAgentId,
        List<MemoryScopeRef> scopes,
        String query,
        int limit
) {
    public RecallConfirmedMemoryQuery {
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        scopes = List.copyOf(Objects.requireNonNull(scopes, "scopes must not be null"));
        if (scopes.isEmpty() || scopes.size() > 16) {
            throw new IllegalArgumentException("scopes must contain between 1 and 16 entries");
        }
        if (new HashSet<>(scopes).size() != scopes.size()) {
            throw new IllegalArgumentException("scopes must not contain duplicates");
        }
        if (scopes.stream().anyMatch(scope -> scope.scopeType() == MemoryScopeType.AGENT
                && !scope.scopeId().equals(enterpriseAgentId))) {
            throw new IllegalArgumentException("AGENT scopeId must equal enterpriseAgentId");
        }
        query = MemoryValueChecks.nonBlank(query, "query", 2000);
        if (limit <= 0 || limit > 50) {
            throw new IllegalArgumentException("limit must be between 1 and 50");
        }
    }
}

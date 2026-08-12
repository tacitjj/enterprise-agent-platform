package com.dianlian.platform.memory.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record ConfirmedMemory(
        UUID memoryId,
        UUID enterpriseAgentId,
        MemoryScopeRef scope,
        long version,
        String content,
        String semanticKey,
        MemoryItemStatus status,
        Instant updatedAt
) {
    public ConfirmedMemory {
        Objects.requireNonNull(memoryId, "memoryId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(scope, "scope must not be null");
        if (version <= 0) {
            throw new IllegalArgumentException("version must be positive");
        }
        Objects.requireNonNull(content, "content must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(updatedAt, "updatedAt must not be null");
    }
}

package com.dianlian.platform.memory.domain;

import com.dianlian.platform.memory.api.ConfirmedMemory;
import com.dianlian.platform.memory.api.MemoryItemStatus;
import com.dianlian.platform.memory.api.MemoryScopeRef;
import com.dianlian.platform.memory.api.MemoryScopeType;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record MemoryItem(
        UUID memoryId,
        UUID tenantId,
        UUID enterpriseAgentId,
        MemoryScopeRef scope,
        MemoryItemStatus status,
        long currentVersion,
        String content,
        String semanticKey,
        UUID createdBy,
        Instant createdAt,
        Instant updatedAt,
        UUID forgottenBy,
        Instant forgottenAt,
        String forgetReason,
        String forgetRequestHash,
        String forgetIdempotencyKey
) {
    public MemoryItem {
        Objects.requireNonNull(memoryId, "memoryId must not be null");
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(scope, "scope must not be null");
        if (scope.scopeType() == MemoryScopeType.AGENT
                && !scope.scopeId().equals(enterpriseAgentId)) {
            throw new IllegalArgumentException("AGENT scopeId must equal enterpriseAgentId");
        }
        Objects.requireNonNull(status, "status must not be null");
        if (currentVersion <= 0) {
            throw new IllegalArgumentException("currentVersion must be positive");
        }
        Objects.requireNonNull(content, "content must not be null");
        Objects.requireNonNull(createdBy, "createdBy must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
        Objects.requireNonNull(updatedAt, "updatedAt must not be null");
    }

    public ConfirmedMemory toView() {
        return new ConfirmedMemory(
                memoryId,
                enterpriseAgentId,
                scope,
                currentVersion,
                content,
                semanticKey,
                status,
                updatedAt
        );
    }
}

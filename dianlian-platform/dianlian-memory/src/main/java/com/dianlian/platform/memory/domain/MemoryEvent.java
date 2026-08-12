package com.dianlian.platform.memory.domain;

import com.dianlian.platform.memory.api.MemoryScopeRef;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record MemoryEvent(
        UUID eventId,
        UUID tenantId,
        UUID enterpriseAgentId,
        MemoryScopeRef scope,
        MemoryEventType eventType,
        UUID candidateId,
        UUID memoryId,
        Long resultingVersion,
        String fromStatus,
        String toStatus,
        String reason,
        String requestHash,
        String idempotencyKey,
        UUID actorId,
        Instant occurredAt
) {
    public MemoryEvent {
        Objects.requireNonNull(eventId, "eventId must not be null");
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(scope, "scope must not be null");
        Objects.requireNonNull(eventType, "eventType must not be null");
        Objects.requireNonNull(requestHash, "requestHash must not be null");
        Objects.requireNonNull(idempotencyKey, "idempotencyKey must not be null");
        Objects.requireNonNull(actorId, "actorId must not be null");
        Objects.requireNonNull(occurredAt, "occurredAt must not be null");
    }
}

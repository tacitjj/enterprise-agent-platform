package com.dianlian.platform.memory.domain;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record MemoryVersion(
        UUID memoryId,
        UUID tenantId,
        long version,
        String content,
        String semanticKey,
        UUID sourceCandidateId,
        MemoryVersionChangeType changeType,
        String reason,
        String requestHash,
        String idempotencyKey,
        UUID createdBy,
        Instant createdAt
) {
    public MemoryVersion {
        Objects.requireNonNull(memoryId, "memoryId must not be null");
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        if (version <= 0) {
            throw new IllegalArgumentException("version must be positive");
        }
        Objects.requireNonNull(content, "content must not be null");
        Objects.requireNonNull(changeType, "changeType must not be null");
        Objects.requireNonNull(requestHash, "requestHash must not be null");
        Objects.requireNonNull(idempotencyKey, "idempotencyKey must not be null");
        Objects.requireNonNull(createdBy, "createdBy must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }
}

package com.dianlian.platform.memory.application;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

/**
 * MEMORY_ITEM_VERSION uses the stable memory_id as resourceId and version_no as resourceVersion.
 */
public record MemoryIndexJobWrite(
        UUID jobId,
        UUID tenantId,
        UUID resourceId,
        long resourceVersion,
        long eventSequence,
        IndexTarget indexTarget,
        Operation operation,
        Instant occurredAt
) {
    public MemoryIndexJobWrite {
        Objects.requireNonNull(jobId, "jobId must not be null");
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(resourceId, "resourceId must not be null");
        if (resourceVersion <= 0) {
            throw new IllegalArgumentException("resourceVersion must be positive");
        }
        if (eventSequence <= 0) {
            throw new IllegalArgumentException("eventSequence must be positive");
        }
        Objects.requireNonNull(indexTarget, "indexTarget must not be null");
        Objects.requireNonNull(operation, "operation must not be null");
        Objects.requireNonNull(occurredAt, "occurredAt must not be null");
    }

    public enum IndexTarget {
        LEXICAL,
        VECTOR
    }

    public enum Operation {
        UPSERT,
        DELETE
    }
}

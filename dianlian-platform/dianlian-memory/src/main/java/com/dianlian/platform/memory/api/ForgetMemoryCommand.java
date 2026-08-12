package com.dianlian.platform.memory.api;

import java.util.Objects;
import java.util.UUID;

public record ForgetMemoryCommand(
        UUID memoryId,
        String reason,
        String idempotencyKey,
        String requestHash
) {
    public ForgetMemoryCommand {
        Objects.requireNonNull(memoryId, "memoryId must not be null");
        reason = MemoryValueChecks.nonBlank(reason, "reason", 1000);
        idempotencyKey = MemoryValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 160);
        requestHash = MemoryValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

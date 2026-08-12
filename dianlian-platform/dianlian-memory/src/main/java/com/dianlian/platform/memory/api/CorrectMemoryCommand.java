package com.dianlian.platform.memory.api;

import java.util.Objects;
import java.util.UUID;

public record CorrectMemoryCommand(
        UUID memoryId,
        String correctedContent,
        String semanticKey,
        String reason,
        String idempotencyKey,
        String requestHash
) {
    public CorrectMemoryCommand {
        Objects.requireNonNull(memoryId, "memoryId must not be null");
        correctedContent = MemoryValueChecks.nonBlank(correctedContent, "correctedContent", 8000);
        semanticKey = MemoryValueChecks.optional(semanticKey, "semanticKey", 200);
        reason = MemoryValueChecks.nonBlank(reason, "reason", 1000);
        idempotencyKey = MemoryValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 160);
        requestHash = MemoryValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

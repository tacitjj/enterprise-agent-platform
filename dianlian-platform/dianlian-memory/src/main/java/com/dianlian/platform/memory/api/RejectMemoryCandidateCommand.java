package com.dianlian.platform.memory.api;

import java.util.Objects;
import java.util.UUID;

public record RejectMemoryCandidateCommand(
        UUID candidateId,
        String reason,
        String idempotencyKey,
        String requestHash
) {
    public RejectMemoryCandidateCommand {
        Objects.requireNonNull(candidateId, "candidateId must not be null");
        reason = MemoryValueChecks.nonBlank(reason, "reason", 1000);
        idempotencyKey = MemoryValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 160);
        requestHash = MemoryValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

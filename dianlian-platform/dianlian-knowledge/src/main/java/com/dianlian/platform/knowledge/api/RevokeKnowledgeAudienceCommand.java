package com.dianlian.platform.knowledge.api;

import java.util.Objects;
import java.util.UUID;

public record RevokeKnowledgeAudienceCommand(
        UUID grantId,
        String reason,
        String idempotencyKey,
        String requestHash
) {
    public RevokeKnowledgeAudienceCommand {
        Objects.requireNonNull(grantId, "grantId must not be null");
        reason = KnowledgeValueChecks.nonBlank(reason, "reason", 1000);
        idempotencyKey = KnowledgeValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 200);
        requestHash = KnowledgeValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

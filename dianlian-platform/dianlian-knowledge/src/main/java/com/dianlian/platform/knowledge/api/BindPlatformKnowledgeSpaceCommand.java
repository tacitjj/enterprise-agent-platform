package com.dianlian.platform.knowledge.api;

import java.util.Objects;
import java.util.UUID;

public record BindPlatformKnowledgeSpaceCommand(
        UUID spaceId,
        UUID agentTemplateId,
        UUID agentVersionId,
        String idempotencyKey,
        String requestHash
) {
    public BindPlatformKnowledgeSpaceCommand {
        Objects.requireNonNull(spaceId, "spaceId must not be null");
        Objects.requireNonNull(agentTemplateId, "agentTemplateId must not be null");
        Objects.requireNonNull(agentVersionId, "agentVersionId must not be null");
        idempotencyKey = KnowledgeValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 200);
        requestHash = KnowledgeValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

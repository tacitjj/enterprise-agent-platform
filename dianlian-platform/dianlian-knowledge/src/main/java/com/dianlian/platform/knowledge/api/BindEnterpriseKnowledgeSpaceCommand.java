package com.dianlian.platform.knowledge.api;

import java.util.Objects;
import java.util.UUID;

public record BindEnterpriseKnowledgeSpaceCommand(
        UUID spaceId,
        UUID enterpriseAgentId,
        UUID configurationVersionId,
        String idempotencyKey,
        String requestHash
) {
    public BindEnterpriseKnowledgeSpaceCommand {
        Objects.requireNonNull(spaceId, "spaceId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(configurationVersionId, "configurationVersionId must not be null");
        idempotencyKey = KnowledgeValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 200);
        requestHash = KnowledgeValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

package com.dianlian.platform.knowledge.api;

import java.util.Objects;
import java.util.UUID;

public record GrantKnowledgeAudienceCommand(
        UUID spaceId,
        UUID audienceTenantId,
        KnowledgeAudienceType audienceType,
        UUID audienceUserId,
        String idempotencyKey,
        String requestHash
) {
    public GrantKnowledgeAudienceCommand {
        Objects.requireNonNull(spaceId, "spaceId must not be null");
        Objects.requireNonNull(audienceTenantId, "audienceTenantId must not be null");
        Objects.requireNonNull(audienceType, "audienceType must not be null");
        if ((audienceType == KnowledgeAudienceType.USER) != (audienceUserId != null)) {
            throw new IllegalArgumentException("audienceUserId is required only for USER grants");
        }
        idempotencyKey = KnowledgeValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 200);
        requestHash = KnowledgeValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

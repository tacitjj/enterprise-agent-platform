package com.dianlian.platform.knowledge.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record KnowledgeSpaceView(
        UUID spaceId,
        KnowledgeOwnerScope ownerScope,
        UUID tenantId,
        String spaceCode,
        String displayName,
        UUID createdBy,
        Instant createdAt
) {
    public KnowledgeSpaceView {
        Objects.requireNonNull(spaceId, "spaceId must not be null");
        Objects.requireNonNull(ownerScope, "ownerScope must not be null");
        if ((ownerScope == KnowledgeOwnerScope.PLATFORM) != (tenantId == null)) {
            throw new IllegalArgumentException("tenantId must be null only for platform knowledge");
        }
        spaceCode = KnowledgeValueChecks.spaceCode(spaceCode);
        displayName = KnowledgeValueChecks.nonBlank(displayName, "displayName", 200);
        Objects.requireNonNull(createdBy, "createdBy must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }
}

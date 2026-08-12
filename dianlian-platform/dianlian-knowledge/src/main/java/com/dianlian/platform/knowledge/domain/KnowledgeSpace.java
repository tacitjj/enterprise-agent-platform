package com.dianlian.platform.knowledge.domain;

import com.dianlian.platform.knowledge.api.KnowledgeOwnerScope;
import com.dianlian.platform.knowledge.api.KnowledgeSpaceView;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record KnowledgeSpace(
        UUID spaceId,
        KnowledgeOwnerScope ownerScope,
        UUID tenantId,
        String spaceCode,
        String displayName,
        String description,
        KnowledgeSpaceStatus status,
        UUID createdBy,
        Instant createdAt
) {
    public KnowledgeSpace {
        Objects.requireNonNull(spaceId, "spaceId must not be null");
        Objects.requireNonNull(ownerScope, "ownerScope must not be null");
        if ((ownerScope == KnowledgeOwnerScope.PLATFORM) != (tenantId == null)) {
            throw new IllegalArgumentException("tenantId must be null only for platform knowledge");
        }
        Objects.requireNonNull(spaceCode, "spaceCode must not be null");
        Objects.requireNonNull(displayName, "displayName must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(createdBy, "createdBy must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }

    public boolean active() {
        return status == KnowledgeSpaceStatus.ACTIVE;
    }

    public KnowledgeSpaceView toView() {
        return new KnowledgeSpaceView(
                spaceId,
                ownerScope,
                tenantId,
                spaceCode,
                displayName,
                createdBy,
                createdAt
        );
    }
}

package com.dianlian.platform.knowledge.domain;

import com.dianlian.platform.knowledge.api.KnowledgeBindingTargetType;
import com.dianlian.platform.knowledge.api.KnowledgeBindingView;
import com.dianlian.platform.knowledge.api.KnowledgeOwnerScope;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record KnowledgeBinding(
        UUID bindingId,
        UUID spaceId,
        KnowledgeOwnerScope spaceOwnerScope,
        UUID spaceTenantId,
        KnowledgeBindingTargetType targetType,
        UUID targetId,
        UUID createdBy,
        Instant createdAt
) {
    public KnowledgeBinding {
        Objects.requireNonNull(bindingId, "bindingId must not be null");
        Objects.requireNonNull(spaceId, "spaceId must not be null");
        Objects.requireNonNull(spaceOwnerScope, "spaceOwnerScope must not be null");
        Objects.requireNonNull(targetType, "targetType must not be null");
        Objects.requireNonNull(targetId, "targetId must not be null");
        Objects.requireNonNull(createdBy, "createdBy must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }

    public KnowledgeBindingView toView() {
        return new KnowledgeBindingView(bindingId, spaceId, targetType, targetId, createdBy, createdAt);
    }
}

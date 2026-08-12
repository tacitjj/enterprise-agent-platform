package com.dianlian.platform.knowledge.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record KnowledgeBindingView(
        UUID bindingId,
        UUID spaceId,
        KnowledgeBindingTargetType targetType,
        UUID targetId,
        UUID createdBy,
        Instant createdAt
) {
    public KnowledgeBindingView {
        Objects.requireNonNull(bindingId, "bindingId must not be null");
        Objects.requireNonNull(spaceId, "spaceId must not be null");
        Objects.requireNonNull(targetType, "targetType must not be null");
        Objects.requireNonNull(targetId, "targetId must not be null");
        Objects.requireNonNull(createdBy, "createdBy must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }
}

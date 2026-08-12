package com.dianlian.platform.interaction.application;

import com.dianlian.platform.context.api.ContextAuthorityPort;
import com.dianlian.platform.context.api.FencedAgentContext;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record InvocationContextSnapshot(
        FencedAgentContext fencedContext,
        ContextAuthorityPort.InvocationBoundary invocationBoundary,
        String contextHash,
        Instant createdAt
) {
    public InvocationContextSnapshot {
        Objects.requireNonNull(fencedContext, "fencedContext must not be null");
        Objects.requireNonNull(invocationBoundary, "invocationBoundary must not be null");
        contextHash = Objects.requireNonNull(contextHash, "contextHash must not be null");
        if (!contextHash.matches("^[0-9a-f]{64}$")) {
            throw new IllegalArgumentException("contextHash must be lowercase SHA-256");
        }
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }

    public UUID retrievalRequestId() {
        return fencedContext.retrievalRequestId();
    }
}

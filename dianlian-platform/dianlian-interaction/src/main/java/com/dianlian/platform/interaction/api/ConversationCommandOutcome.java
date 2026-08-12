package com.dianlian.platform.interaction.api;

import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record ConversationCommandOutcome<T>(T resource, List<UUID> queuedInvocationIds, boolean replayed) {
    public ConversationCommandOutcome {
        Objects.requireNonNull(resource, "resource must not be null");
        queuedInvocationIds = List.copyOf(Objects.requireNonNull(queuedInvocationIds, "queuedInvocationIds must not be null"));
    }
}

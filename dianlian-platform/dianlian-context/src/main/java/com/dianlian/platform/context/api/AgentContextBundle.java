package com.dianlian.platform.context.api;

import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record AgentContextBundle(
        UUID agentVersionId,
        UUID configurationVersionId,
        String systemInstruction,
        List<ContextMessage> recentMessages,
        ContextSourceResult knowledge,
        ContextSourceResult memory,
        List<MemoryScopeRef> memoryScopes,
        List<String> blockers
) {
    public AgentContextBundle {
        Objects.requireNonNull(agentVersionId, "agentVersionId must not be null");
        Objects.requireNonNull(configurationVersionId, "configurationVersionId must not be null");
        systemInstruction = Objects.requireNonNull(systemInstruction, "systemInstruction must not be null").trim();
        if (systemInstruction.isEmpty()) {
            throw new IllegalArgumentException("systemInstruction must not be blank");
        }
        recentMessages = List.copyOf(Objects.requireNonNull(recentMessages, "recentMessages must not be null"));
        Objects.requireNonNull(knowledge, "knowledge must not be null");
        Objects.requireNonNull(memory, "memory must not be null");
        memoryScopes = List.copyOf(Objects.requireNonNull(memoryScopes, "memoryScopes must not be null"));
        blockers = List.copyOf(Objects.requireNonNull(blockers, "blockers must not be null"));
    }

    public boolean ready() {
        return blockers.isEmpty();
    }
}

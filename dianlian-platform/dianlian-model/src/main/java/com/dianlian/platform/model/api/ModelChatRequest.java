package com.dianlian.platform.model.api;

import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record ModelChatRequest(
        UUID logicalInvocationId,
        String systemInstruction,
        List<ModelChatMessage> messages
) {
    public ModelChatRequest {
        Objects.requireNonNull(logicalInvocationId, "logicalInvocationId must not be null");
        systemInstruction = ModelValueChecks.text(systemInstruction, "systemInstruction", 60_000);
        messages = List.copyOf(Objects.requireNonNull(messages, "messages must not be null"));
        if (messages.isEmpty()) throw new IllegalArgumentException("messages must not be empty");
    }
}

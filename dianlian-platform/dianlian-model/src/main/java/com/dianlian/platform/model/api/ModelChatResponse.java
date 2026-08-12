package com.dianlian.platform.model.api;

import java.util.Objects;

public record ModelChatResponse(
        String text,
        int inputTokens,
        int outputTokens,
        boolean usageConfirmed,
        String providerRequestId,
        String finishReason
) {
    public ModelChatResponse {
        text = ModelValueChecks.text(text, "text", 100_000);
        if (inputTokens < 0 || outputTokens < 0) {
            throw new IllegalArgumentException("token usage cannot be negative");
        }
        if (!usageConfirmed && (inputTokens != 0 || outputTokens != 0)) {
            throw new IllegalArgumentException("unconfirmed token usage must not contain chargeable counts");
        }
        finishReason = Objects.requireNonNullElse(finishReason, "UNKNOWN");
    }
}

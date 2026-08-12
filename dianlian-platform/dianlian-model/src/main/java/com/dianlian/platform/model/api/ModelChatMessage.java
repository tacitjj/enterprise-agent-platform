package com.dianlian.platform.model.api;

import java.util.Objects;

public record ModelChatMessage(Role role, String text) {
    public enum Role {
        HUMAN,
        AGENT
    }

    public ModelChatMessage {
        Objects.requireNonNull(role, "role must not be null");
        text = ModelValueChecks.text(text, "text", 40_000);
    }
}

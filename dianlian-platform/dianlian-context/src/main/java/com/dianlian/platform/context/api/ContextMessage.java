package com.dianlian.platform.context.api;

import java.util.Objects;

public record ContextMessage(Role role, String actorLabel, String text) {

    public enum Role {
        HUMAN,
        AGENT
    }

    public ContextMessage {
        Objects.requireNonNull(role, "role must not be null");
        actorLabel = requireText(actorLabel, "actorLabel", 100);
        text = requireText(text, "text", 20_000);
    }

    private static String requireText(String value, String fieldName, int maxLength) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        var normalized = value.trim();
        if (normalized.isEmpty() || normalized.length() > maxLength) {
            throw new IllegalArgumentException(fieldName + " is invalid");
        }
        return normalized;
    }
}

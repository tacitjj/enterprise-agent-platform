package com.dianlian.platform.interaction.api;

import java.util.Objects;
import java.util.UUID;

public record ConversationMemberView(UUID userId, String displayName, String avatarUrl, String role) {
    public ConversationMemberView {
        Objects.requireNonNull(userId, "userId must not be null");
        displayName = InteractionValueChecks.text(displayName, "displayName", 100);
        role = InteractionValueChecks.text(role, "role", 32);
    }
}

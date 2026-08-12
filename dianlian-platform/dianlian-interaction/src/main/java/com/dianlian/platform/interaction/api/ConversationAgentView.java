package com.dianlian.platform.interaction.api;

import java.util.Objects;
import java.util.UUID;

public record ConversationAgentView(
        UUID enterpriseAgentId,
        String displayName,
        String roleName,
        String avatarUrl
) {
    public ConversationAgentView {
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        displayName = InteractionValueChecks.text(displayName, "displayName", 100);
        roleName = InteractionValueChecks.text(roleName, "roleName", 100);
    }
}

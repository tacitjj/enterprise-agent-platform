package com.dianlian.platform.interaction.api;

import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record ConversationSummary(
        UUID conversationId,
        ConversationType type,
        String title,
        ConversationStatus status,
        long membershipVersion,
        List<ConversationMemberView> humanMembers,
        List<ConversationAgentView> agents,
        String lastMessagePreview,
        Instant lastMessageAt,
        long unreadCount,
        List<String> allowedActions
) {
    public ConversationSummary {
        Objects.requireNonNull(conversationId, "conversationId must not be null");
        Objects.requireNonNull(type, "type must not be null");
        title = InteractionValueChecks.text(title, "title", 200);
        Objects.requireNonNull(status, "status must not be null");
        if (membershipVersion < 1 || unreadCount < 0) throw new IllegalArgumentException("conversation counters are invalid");
        humanMembers = List.copyOf(Objects.requireNonNull(humanMembers, "humanMembers must not be null"));
        agents = List.copyOf(Objects.requireNonNull(agents, "agents must not be null"));
        allowedActions = List.copyOf(Objects.requireNonNull(allowedActions, "allowedActions must not be null"));
    }
}

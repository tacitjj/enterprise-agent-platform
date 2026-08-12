package com.dianlian.platform.interaction.api;

import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record SendConversationMessageCommand(
        UUID conversationId,
        String clientMessageId,
        String text,
        List<MessageTargetInput> targets,
        ConversationCollaborationMode collaborationMode,
        UUID primaryAgentId,
        UUID replyToMessageId,
        long expectedMembershipVersion,
        String idempotencyKey,
        String requestHash
) {
    public SendConversationMessageCommand {
        Objects.requireNonNull(conversationId, "conversationId must not be null");
        clientMessageId = InteractionValueChecks.text(clientMessageId, "clientMessageId", 160);
        text = InteractionValueChecks.text(text, "text", 20_000);
        targets = List.copyOf(Objects.requireNonNull(targets, "targets must not be null"));
        if (targets.size() > 20) throw new IllegalArgumentException("targets exceeds 20 entries");
        Objects.requireNonNull(collaborationMode, "collaborationMode must not be null");
        if (expectedMembershipVersion < 1) {
            throw new IllegalArgumentException("expectedMembershipVersion must be positive");
        }
        idempotencyKey = InteractionValueChecks.text(idempotencyKey, "idempotencyKey", 160);
        requestHash = InteractionValueChecks.text(requestHash, "requestHash", 128);
    }
}

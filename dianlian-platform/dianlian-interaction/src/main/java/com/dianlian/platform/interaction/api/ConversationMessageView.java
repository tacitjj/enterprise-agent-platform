package com.dianlian.platform.interaction.api;

import com.dianlian.platform.context.api.ContextSourceState;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record ConversationMessageView(
        UUID messageId,
        UUID conversationId,
        long sequenceNo,
        MessageSenderType senderType,
        UUID senderUserId,
        UUID senderAgentId,
        String senderDisplayName,
        String senderAvatarUrl,
        String text,
        UUID replyToMessageId,
        List<UUID> targetAgentIds,
        String aiStatus,
        ContextSourceState knowledgeState,
        ContextSourceState memoryState,
        long chargedMicroCredit,
        Instant createdAt
) {
    public ConversationMessageView {
        Objects.requireNonNull(messageId, "messageId must not be null");
        Objects.requireNonNull(conversationId, "conversationId must not be null");
        if (sequenceNo < 1 || chargedMicroCredit < 0) throw new IllegalArgumentException("message counters are invalid");
        Objects.requireNonNull(senderType, "senderType must not be null");
        senderDisplayName = InteractionValueChecks.text(senderDisplayName, "senderDisplayName", 100);
        text = InteractionValueChecks.text(text, "text", 100_000);
        targetAgentIds = List.copyOf(Objects.requireNonNull(targetAgentIds, "targetAgentIds must not be null"));
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }
}

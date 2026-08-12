package com.dianlian.platform.interaction.api;

import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record CreateConversationCommand(
        ConversationType type,
        String title,
        List<UUID> participantUserIds,
        List<UUID> enterpriseAgentIds,
        String idempotencyKey,
        String requestHash
) {
    public CreateConversationCommand {
        Objects.requireNonNull(type, "type must not be null");
        title = InteractionValueChecks.text(title, "title", 200);
        participantUserIds = InteractionValueChecks.distinctIds(participantUserIds, "participantUserIds", 200);
        enterpriseAgentIds = InteractionValueChecks.distinctIds(enterpriseAgentIds, "enterpriseAgentIds", 20);
        idempotencyKey = InteractionValueChecks.text(idempotencyKey, "idempotencyKey", 160);
        requestHash = InteractionValueChecks.text(requestHash, "requestHash", 128);
    }
}

package com.dianlian.platform.interaction.api;

import java.util.Objects;
import java.util.UUID;

public record MessageTargetInput(
        UUID enterpriseAgentId,
        MessageTriggerType triggerType,
        UUID replyToMessageId
) {
    public MessageTargetInput {
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(triggerType, "triggerType must not be null");
        if (triggerType == MessageTriggerType.REPLY && replyToMessageId == null) {
            throw new IllegalArgumentException("REPLY target requires replyToMessageId");
        }
        if (triggerType != MessageTriggerType.REPLY && replyToMessageId != null) {
            throw new IllegalArgumentException("replyToMessageId is only valid for REPLY target");
        }
    }
}

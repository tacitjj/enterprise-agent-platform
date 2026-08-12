package com.dianlian.platform.memory.api;

import java.util.Objects;
import java.util.UUID;

public record ProposeMemoryCandidateCommand(
        UUID enterpriseAgentId,
        MemoryScopeRef scope,
        String content,
        String semanticKey,
        UUID sourceConversationId,
        UUID sourceMessageId,
        String idempotencyKey,
        String requestHash
) {
    public ProposeMemoryCandidateCommand {
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(scope, "scope must not be null");
        if (scope.scopeType() == MemoryScopeType.AGENT && !scope.scopeId().equals(enterpriseAgentId)) {
            throw new IllegalArgumentException("AGENT scopeId must equal enterpriseAgentId");
        }
        content = MemoryValueChecks.nonBlank(content, "content", 8000);
        semanticKey = MemoryValueChecks.optional(semanticKey, "semanticKey", 200);
        if (sourceMessageId != null && sourceConversationId == null) {
            throw new IllegalArgumentException("sourceConversationId is required when sourceMessageId is present");
        }
        idempotencyKey = MemoryValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 160);
        requestHash = MemoryValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

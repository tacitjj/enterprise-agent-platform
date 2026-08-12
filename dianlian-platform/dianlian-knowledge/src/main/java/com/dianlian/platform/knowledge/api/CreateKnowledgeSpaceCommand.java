package com.dianlian.platform.knowledge.api;

public record CreateKnowledgeSpaceCommand(
        String spaceCode,
        String displayName,
        String description,
        String idempotencyKey,
        String requestHash
) {
    public CreateKnowledgeSpaceCommand {
        spaceCode = KnowledgeValueChecks.spaceCode(spaceCode);
        displayName = KnowledgeValueChecks.nonBlank(displayName, "displayName", 200);
        description = KnowledgeValueChecks.optional(description, "description", 2000);
        idempotencyKey = KnowledgeValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 200);
        requestHash = KnowledgeValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

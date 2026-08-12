package com.dianlian.platform.knowledge.api;

import java.util.Objects;
import java.util.UUID;

public record AppendKnowledgeDocumentVersionCommand(
        UUID spaceId,
        UUID documentId,
        String title,
        KnowledgeSourceType sourceType,
        String externalSourceKey,
        String sourceRef,
        String contentHash,
        String mediaType,
        long contentLength,
        String idempotencyKey,
        String requestHash
) {
    public AppendKnowledgeDocumentVersionCommand {
        Objects.requireNonNull(spaceId, "spaceId must not be null");
        title = KnowledgeValueChecks.nonBlank(title, "title", 500);
        Objects.requireNonNull(sourceType, "sourceType must not be null");
        externalSourceKey = KnowledgeValueChecks.optional(externalSourceKey, "externalSourceKey", 500);
        sourceRef = KnowledgeValueChecks.nonBlank(sourceRef, "sourceRef", 1024);
        contentHash = KnowledgeValueChecks.contentHash(contentHash);
        mediaType = KnowledgeValueChecks.nonBlank(mediaType, "mediaType", 200);
        if (contentLength < 0) {
            throw new IllegalArgumentException("contentLength cannot be negative");
        }
        idempotencyKey = KnowledgeValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 200);
        requestHash = KnowledgeValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

package com.dianlian.platform.knowledge.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record KnowledgeDocumentVersionView(
        UUID documentId,
        UUID documentVersionId,
        UUID spaceId,
        long revision,
        String title,
        String sourceRef,
        String contentHash,
        String mediaType,
        long contentLength,
        KnowledgeDocumentVersionState state,
        UUID createdBy,
        Instant createdAt
) {
    public KnowledgeDocumentVersionView {
        Objects.requireNonNull(documentId, "documentId must not be null");
        Objects.requireNonNull(documentVersionId, "documentVersionId must not be null");
        Objects.requireNonNull(spaceId, "spaceId must not be null");
        if (revision <= 0) {
            throw new IllegalArgumentException("revision must be positive");
        }
        title = KnowledgeValueChecks.nonBlank(title, "title", 500);
        sourceRef = KnowledgeValueChecks.nonBlank(sourceRef, "sourceRef", 1024);
        contentHash = KnowledgeValueChecks.contentHash(contentHash);
        mediaType = KnowledgeValueChecks.nonBlank(mediaType, "mediaType", 200);
        if (contentLength < 0) {
            throw new IllegalArgumentException("contentLength cannot be negative");
        }
        Objects.requireNonNull(state, "state must not be null");
        Objects.requireNonNull(createdBy, "createdBy must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }
}

package com.dianlian.platform.knowledge.domain;

import com.dianlian.platform.knowledge.api.KnowledgeDocumentVersionState;
import com.dianlian.platform.knowledge.api.KnowledgeDocumentVersionView;
import com.dianlian.platform.knowledge.api.KnowledgeSourceType;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record KnowledgeDocumentVersion(
        UUID documentId,
        UUID documentVersionId,
        UUID spaceId,
        UUID tenantId,
        long revision,
        String title,
        KnowledgeSourceType sourceType,
        String externalSourceKey,
        String objectKey,
        String contentHash,
        String mediaType,
        long byteSize,
        KnowledgeDocumentVersionState state,
        UUID createdBy,
        Instant createdAt
) {
    public KnowledgeDocumentVersion {
        Objects.requireNonNull(documentId, "documentId must not be null");
        Objects.requireNonNull(documentVersionId, "documentVersionId must not be null");
        Objects.requireNonNull(spaceId, "spaceId must not be null");
        if (revision <= 0) {
            throw new IllegalArgumentException("revision must be positive");
        }
        Objects.requireNonNull(title, "title must not be null");
        Objects.requireNonNull(sourceType, "sourceType must not be null");
        Objects.requireNonNull(objectKey, "objectKey must not be null");
        Objects.requireNonNull(contentHash, "contentHash must not be null");
        Objects.requireNonNull(mediaType, "mediaType must not be null");
        if (byteSize < 0) {
            throw new IllegalArgumentException("byteSize cannot be negative");
        }
        Objects.requireNonNull(state, "state must not be null");
        Objects.requireNonNull(createdBy, "createdBy must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }

    public KnowledgeDocumentVersionView toView() {
        return new KnowledgeDocumentVersionView(
                documentId,
                documentVersionId,
                spaceId,
                revision,
                title,
                objectKey,
                contentHash,
                mediaType,
                byteSize,
                state,
                createdBy,
                createdAt
        );
    }

    public KnowledgeDocumentVersion asRegistered() {
        return withState(KnowledgeDocumentVersionState.REGISTERED);
    }

    public KnowledgeDocumentVersion withState(KnowledgeDocumentVersionState targetState) {
        Objects.requireNonNull(targetState, "targetState must not be null");
        if (state == targetState) {
            return this;
        }
        return new KnowledgeDocumentVersion(
                documentId,
                documentVersionId,
                spaceId,
                tenantId,
                revision,
                title,
                sourceType,
                externalSourceKey,
                objectKey,
                contentHash,
                mediaType,
                byteSize,
                targetState,
                createdBy,
                createdAt
        );
    }
}

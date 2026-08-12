package com.dianlian.platform.knowledge.api;

import java.util.Objects;
import java.util.UUID;

/** Exact document/version identity returned by a retriever; it contains no document content. */
public record InvocationKnowledgeEvidenceRef(
        UUID documentId,
        UUID documentVersionId
) implements Comparable<InvocationKnowledgeEvidenceRef> {
    public InvocationKnowledgeEvidenceRef {
        Objects.requireNonNull(documentId, "documentId must not be null");
        Objects.requireNonNull(documentVersionId, "documentVersionId must not be null");
    }

    @Override
    public int compareTo(InvocationKnowledgeEvidenceRef other) {
        int documentOrder = documentId.compareTo(other.documentId);
        return documentOrder != 0
                ? documentOrder
                : documentVersionId.compareTo(other.documentVersionId);
    }
}

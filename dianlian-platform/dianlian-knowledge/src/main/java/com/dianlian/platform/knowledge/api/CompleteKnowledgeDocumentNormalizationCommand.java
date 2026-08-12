package com.dianlian.platform.knowledge.api;

import java.util.Objects;
import java.util.UUID;

public record CompleteKnowledgeDocumentNormalizationCommand(
        UUID documentVersionId,
        String normalizedText,
        String normalizedTextHash,
        String normalizationProfileVersion,
        String indexProfileVersion,
        String idempotencyKey,
        String requestHash
) {
    public CompleteKnowledgeDocumentNormalizationCommand {
        Objects.requireNonNull(documentVersionId, "documentVersionId must not be null");
        normalizedText = KnowledgeValueChecks.nonBlankText(normalizedText, "normalizedText");
        normalizedTextHash = KnowledgeValueChecks.sha256(normalizedTextHash, "normalizedTextHash");
        normalizationProfileVersion = KnowledgeValueChecks.nonBlank(
                normalizationProfileVersion,
                "normalizationProfileVersion",
                100
        );
        indexProfileVersion = KnowledgeValueChecks.nonBlank(indexProfileVersion, "indexProfileVersion", 100);
        idempotencyKey = KnowledgeValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 200);
        requestHash = KnowledgeValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

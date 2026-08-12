package com.dianlian.platform.context.api;

import java.util.Objects;
import java.util.UUID;

public record ContextEvidence(
        String evidenceId,
        String sourceType,
        UUID sourceId,
        String sourceVersion,
        String chunkId,
        String title,
        String excerpt,
        String contentHash,
        double score,
        String citation
) {
    public ContextEvidence {
        evidenceId = requireText(evidenceId, "evidenceId", 200);
        sourceType = requireText(sourceType, "sourceType", 64);
        Objects.requireNonNull(sourceId, "sourceId must not be null");
        sourceVersion = requireText(sourceVersion, "sourceVersion", 200);
        chunkId = requireText(chunkId, "chunkId", 200);
        title = requireText(title, "title", 500);
        excerpt = requireText(excerpt, "excerpt", 2_000);
        contentHash = requireText(contentHash, "contentHash", 64);
        if (!contentHash.matches("^[0-9a-f]{64}$")) {
            throw new IllegalArgumentException("contentHash must be a lowercase SHA-256 value");
        }
        if (!Double.isFinite(score) || score < 0 || score > 1) {
            throw new IllegalArgumentException("score must be between 0 and 1");
        }
        citation = requireText(citation, "citation", 1_000);
    }

    private static String requireText(String value, String fieldName, int maxLength) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        var normalized = value.trim();
        if (normalized.isEmpty() || normalized.length() > maxLength) {
            throw new IllegalArgumentException(fieldName + " is invalid");
        }
        return normalized;
    }
}

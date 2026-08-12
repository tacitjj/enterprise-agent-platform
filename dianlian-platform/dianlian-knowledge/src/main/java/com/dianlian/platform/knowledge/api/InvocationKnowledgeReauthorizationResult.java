package com.dianlian.platform.knowledge.api;

import java.util.HashSet;
import java.util.List;
import java.util.Objects;

/** Canonically ordered exact-evidence reauthorization result with no document content. */
public record InvocationKnowledgeReauthorizationResult(
        List<AuthorizedKnowledgeResourceRef> allowed,
        List<RejectedInvocationKnowledgeEvidence> rejected
) {
    public InvocationKnowledgeReauthorizationResult {
        allowed = List.copyOf(Objects.requireNonNull(allowed, "allowed must not be null"));
        rejected = List.copyOf(Objects.requireNonNull(rejected, "rejected must not be null"));
        if (allowed.stream().anyMatch(Objects::isNull) || rejected.stream().anyMatch(Objects::isNull)) {
            throw new IllegalArgumentException("authority result entries must not contain null");
        }
        if (new HashSet<>(allowed).size() != allowed.size()
                || new HashSet<>(rejected).size() != rejected.size()) {
            throw new IllegalArgumentException("authority result entries must not contain duplicates");
        }
        allowed = allowed.stream()
                .sorted(java.util.Comparator.comparing(AuthorizedKnowledgeResourceRef::resourceId)
                        .thenComparing(AuthorizedKnowledgeResourceRef::resourceVersionId))
                .toList();
        rejected = rejected.stream().sorted().toList();
    }
}

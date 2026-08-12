package com.dianlian.platform.knowledge.api;

import java.util.Objects;

/** Exact evidence identity rejected by the current authority check, without document content. */
public record RejectedInvocationKnowledgeEvidence(
        InvocationKnowledgeEvidenceRef evidence,
        InvocationKnowledgeRejectionReason reason
) implements Comparable<RejectedInvocationKnowledgeEvidence> {
    public RejectedInvocationKnowledgeEvidence {
        Objects.requireNonNull(evidence, "evidence must not be null");
        Objects.requireNonNull(reason, "reason must not be null");
    }

    @Override
    public int compareTo(RejectedInvocationKnowledgeEvidence other) {
        return evidence.compareTo(other.evidence);
    }
}

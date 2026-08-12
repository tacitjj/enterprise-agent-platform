package com.dianlian.platform.knowledge.api;

import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/**
 * Trusted invocation identity and exact evidence set to reauthorize immediately before use.
 *
 * <p>The evidence list has set semantics and is canonicalized by document/version UUID. Its size
 * may not exceed {@code limit}, keeping the recheck bounded to one PostgreSQL batch.</p>
 */
public record InvocationKnowledgeReauthorizationQuery(
        UUID tenantId,
        UUID actorUserId,
        UUID agentVersionId,
        UUID enterpriseAgentId,
        UUID configurationVersionId,
        List<UUID> audienceUserIds,
        Instant observedAt,
        int limit,
        List<InvocationKnowledgeEvidenceRef> actualEvidence
) {
    public InvocationKnowledgeReauthorizationQuery {
        tenantId = Objects.requireNonNull(tenantId, "tenantId must not be null");
        actorUserId = Objects.requireNonNull(actorUserId, "actorUserId must not be null");
        agentVersionId = Objects.requireNonNull(agentVersionId, "agentVersionId must not be null");
        enterpriseAgentId = Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        configurationVersionId = Objects.requireNonNull(
                configurationVersionId,
                "configurationVersionId must not be null"
        );
        audienceUserIds = InvocationKnowledgeAuthorityInputs.canonicalAudience(
                actorUserId,
                audienceUserIds
        );
        observedAt = Objects.requireNonNull(observedAt, "observedAt must not be null");
        InvocationKnowledgeAuthorityInputs.requireLimit(limit);
        actualEvidence = List.copyOf(Objects.requireNonNull(
                actualEvidence,
                "actualEvidence must not be null"
        ));
        if (actualEvidence.isEmpty() || actualEvidence.size() > limit) {
            throw new IllegalArgumentException("actualEvidence must contain between 1 and limit entries");
        }
        if (actualEvidence.stream().anyMatch(Objects::isNull)) {
            throw new IllegalArgumentException("actualEvidence must not contain null");
        }
        if (new HashSet<>(actualEvidence).size() != actualEvidence.size()) {
            throw new IllegalArgumentException("actualEvidence must not contain duplicates");
        }
        actualEvidence = actualEvidence.stream().sorted().toList();
    }
}

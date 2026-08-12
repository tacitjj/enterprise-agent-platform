package com.dianlian.platform.knowledge.api;

import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/**
 * Trusted identity and audience snapshot used to authorize one asynchronous invocation.
 *
 * <p>Audience order has no authority meaning and is canonicalized by UUID. The actor must be one
 * of the audience members so a background invocation cannot authorize resources for an unrelated
 * audience.</p>
 */
public record InvocationKnowledgeAuthorizationQuery(
        UUID tenantId,
        UUID actorUserId,
        UUID agentVersionId,
        UUID enterpriseAgentId,
        UUID configurationVersionId,
        List<UUID> audienceUserIds,
        Instant observedAt,
        int limit
) {
    public InvocationKnowledgeAuthorizationQuery {
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
    }
}

final class InvocationKnowledgeAuthorityInputs {

    private static final int MAX_AUDIENCE_SIZE = 500;
    private static final int MAX_RESULT_LIMIT = 2000;

    private InvocationKnowledgeAuthorityInputs() {
    }

    static List<UUID> canonicalAudience(UUID actorUserId, List<UUID> audienceUserIds) {
        List<UUID> audience = List.copyOf(Objects.requireNonNull(
                audienceUserIds,
                "audienceUserIds must not be null"
        ));
        if (audience.isEmpty() || audience.size() > MAX_AUDIENCE_SIZE) {
            throw new IllegalArgumentException("audienceUserIds must contain between 1 and 500 entries");
        }
        if (audience.stream().anyMatch(Objects::isNull)) {
            throw new IllegalArgumentException("audienceUserIds must not contain null");
        }
        if (new HashSet<>(audience).size() != audience.size()) {
            throw new IllegalArgumentException("audienceUserIds must not contain duplicates");
        }
        if (!audience.contains(actorUserId)) {
            throw new IllegalArgumentException("audienceUserIds must include actorUserId");
        }
        return audience.stream().sorted().toList();
    }

    static void requireLimit(int limit) {
        if (limit <= 0 || limit > MAX_RESULT_LIMIT) {
            throw new IllegalArgumentException("limit must be between 1 and 2000");
        }
    }
}

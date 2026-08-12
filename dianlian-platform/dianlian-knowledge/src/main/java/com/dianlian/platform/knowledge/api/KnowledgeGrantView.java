package com.dianlian.platform.knowledge.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record KnowledgeGrantView(
        UUID grantId,
        UUID spaceId,
        UUID audienceTenantId,
        KnowledgeAudienceType audienceType,
        UUID audienceUserId,
        KnowledgeGrantStatus status,
        UUID grantedBy,
        Instant grantedAt,
        UUID revokedBy,
        Instant revokedAt,
        String revokeReason
) {
    public KnowledgeGrantView {
        Objects.requireNonNull(grantId, "grantId must not be null");
        Objects.requireNonNull(spaceId, "spaceId must not be null");
        Objects.requireNonNull(audienceTenantId, "audienceTenantId must not be null");
        Objects.requireNonNull(audienceType, "audienceType must not be null");
        if ((audienceType == KnowledgeAudienceType.USER) != (audienceUserId != null)) {
            throw new IllegalArgumentException("audienceUserId is required only for USER grants");
        }
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(grantedBy, "grantedBy must not be null");
        Objects.requireNonNull(grantedAt, "grantedAt must not be null");
        if (status == KnowledgeGrantStatus.ACTIVE
                && (revokedBy != null || revokedAt != null || revokeReason != null)) {
            throw new IllegalArgumentException("active grant cannot include revocation facts");
        }
        if (status == KnowledgeGrantStatus.REVOKED
                && (revokedBy == null || revokedAt == null || revokeReason == null)) {
            throw new IllegalArgumentException("revoked grant requires complete revocation facts");
        }
    }
}

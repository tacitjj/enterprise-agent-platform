package com.dianlian.platform.knowledge.domain;

import com.dianlian.platform.knowledge.api.KnowledgeAudienceType;
import com.dianlian.platform.knowledge.api.KnowledgeGrantStatus;
import com.dianlian.platform.knowledge.api.KnowledgeGrantView;
import com.dianlian.platform.knowledge.api.KnowledgeOwnerScope;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record KnowledgeGrant(
        UUID grantId,
        UUID spaceId,
        KnowledgeOwnerScope spaceOwnerScope,
        UUID spaceTenantId,
        UUID audienceTenantId,
        KnowledgeAudienceType audienceType,
        UUID audienceId,
        KnowledgeGrantStatus status,
        UUID grantedBy,
        Instant grantedAt,
        UUID revokedBy,
        Instant revokedAt,
        String revokeReason
) {
    public KnowledgeGrant {
        Objects.requireNonNull(grantId, "grantId must not be null");
        Objects.requireNonNull(spaceId, "spaceId must not be null");
        Objects.requireNonNull(spaceOwnerScope, "spaceOwnerScope must not be null");
        Objects.requireNonNull(audienceTenantId, "audienceTenantId must not be null");
        Objects.requireNonNull(audienceType, "audienceType must not be null");
        Objects.requireNonNull(audienceId, "audienceId must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(grantedBy, "grantedBy must not be null");
        Objects.requireNonNull(grantedAt, "grantedAt must not be null");
    }

    public KnowledgeGrantView toView() {
        return new KnowledgeGrantView(
                grantId,
                spaceId,
                audienceTenantId,
                audienceType,
                audienceType == KnowledgeAudienceType.USER ? audienceId : null,
                status,
                grantedBy,
                grantedAt,
                revokedBy,
                revokedAt,
                revokeReason
        );
    }
}

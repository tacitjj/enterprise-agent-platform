package com.dianlian.platform.knowledge.application;

import com.dianlian.platform.knowledge.api.KnowledgeAudienceType;
import com.dianlian.platform.knowledge.api.KnowledgeBindingTargetType;
import com.dianlian.platform.knowledge.api.KnowledgeOwnerScope;
import com.dianlian.platform.knowledge.api.KnowledgeSourceType;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public final class KnowledgeWrites {

    private KnowledgeWrites() {
    }

    public record CreateSpace(
            UUID spaceId,
            UUID eventId,
            KnowledgeOwnerScope ownerScope,
            UUID tenantId,
            String spaceCode,
            String displayName,
            String description,
            String requestHash,
            String idempotencyKey,
            UUID actorId,
            Instant occurredAt
    ) {
        public CreateSpace {
            Objects.requireNonNull(spaceId);
            Objects.requireNonNull(eventId);
            Objects.requireNonNull(ownerScope);
            Objects.requireNonNull(actorId);
            Objects.requireNonNull(occurredAt);
        }
    }

    public record AppendDocumentVersion(
            UUID documentId,
            boolean createDocument,
            UUID documentVersionId,
            UUID documentEventId,
            UUID documentVersionEventId,
            UUID spaceId,
            UUID tenantId,
            String title,
            KnowledgeSourceType sourceType,
            String externalSourceKey,
            String objectKey,
            String contentHash,
            String mediaType,
            long byteSize,
            String requestHash,
            String idempotencyKey,
            UUID actorId,
            Instant occurredAt
    ) {
        public AppendDocumentVersion {
            Objects.requireNonNull(documentId);
            Objects.requireNonNull(documentVersionId);
            Objects.requireNonNull(documentEventId);
            Objects.requireNonNull(documentVersionEventId);
            Objects.requireNonNull(spaceId);
            Objects.requireNonNull(actorId);
            Objects.requireNonNull(occurredAt);
        }
    }

    public record CompleteDocumentNormalization(
            UUID documentVersionId,
            UUID publishEventId,
            UUID lexicalIndexJobId,
            UUID vectorIndexJobId,
            UUID tenantId,
            String normalizedText,
            String normalizedTextHash,
            String normalizationProfileVersion,
            String indexProfileVersion,
            String requestHash,
            String idempotencyKey,
            UUID actorId,
            Instant occurredAt
    ) {
        public CompleteDocumentNormalization {
            Objects.requireNonNull(documentVersionId);
            Objects.requireNonNull(publishEventId);
            Objects.requireNonNull(lexicalIndexJobId);
            Objects.requireNonNull(vectorIndexJobId);
            Objects.requireNonNull(actorId);
            Objects.requireNonNull(occurredAt);
        }
    }

    public record GrantAudience(
            UUID grantId,
            UUID eventId,
            UUID spaceId,
            UUID spaceTenantId,
            UUID audienceTenantId,
            KnowledgeAudienceType audienceType,
            UUID audienceId,
            String requestHash,
            String idempotencyKey,
            UUID actorId,
            Instant occurredAt
    ) {
        public GrantAudience {
            Objects.requireNonNull(grantId);
            Objects.requireNonNull(eventId);
            Objects.requireNonNull(spaceId);
            Objects.requireNonNull(audienceTenantId);
            Objects.requireNonNull(audienceType);
            Objects.requireNonNull(audienceId);
            Objects.requireNonNull(actorId);
            Objects.requireNonNull(occurredAt);
        }
    }

    public record RevokeAudience(
            UUID grantId,
            UUID eventId,
            String reason,
            String requestHash,
            String idempotencyKey,
            UUID actorId,
            Instant occurredAt
    ) {
        public RevokeAudience {
            Objects.requireNonNull(grantId);
            Objects.requireNonNull(eventId);
            Objects.requireNonNull(actorId);
            Objects.requireNonNull(occurredAt);
        }
    }

    public record BindSpace(
            UUID bindingId,
            UUID eventId,
            UUID spaceId,
            UUID tenantId,
            KnowledgeBindingTargetType targetType,
            UUID agentTemplateId,
            UUID agentVersionId,
            UUID enterpriseAgentId,
            UUID configurationVersionId,
            String requestHash,
            String idempotencyKey,
            UUID actorId,
            Instant occurredAt
    ) {
        public BindSpace {
            Objects.requireNonNull(bindingId);
            Objects.requireNonNull(eventId);
            Objects.requireNonNull(spaceId);
            Objects.requireNonNull(targetType);
            Objects.requireNonNull(actorId);
            Objects.requireNonNull(occurredAt);
        }
    }
}

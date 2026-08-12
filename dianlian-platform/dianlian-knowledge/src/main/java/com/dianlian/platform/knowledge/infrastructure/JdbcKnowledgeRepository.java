package com.dianlian.platform.knowledge.infrastructure;

import com.dianlian.platform.knowledge.api.AuthorizedKnowledgeResourceRef;
import com.dianlian.platform.knowledge.api.KnowledgeAudienceType;
import com.dianlian.platform.knowledge.api.KnowledgeBindingTargetType;
import com.dianlian.platform.knowledge.api.KnowledgeCommandConflictException;
import com.dianlian.platform.knowledge.api.KnowledgeDocumentVersionState;
import com.dianlian.platform.knowledge.api.KnowledgeGrantStatus;
import com.dianlian.platform.knowledge.api.KnowledgeOwnerScope;
import com.dianlian.platform.knowledge.api.KnowledgeSourceType;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeEvidenceRef;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeReauthorizationQuery;
import com.dianlian.platform.knowledge.application.KnowledgeAuthorizationRequest;
import com.dianlian.platform.knowledge.application.KnowledgeRepository;
import com.dianlian.platform.knowledge.application.KnowledgeWriteResult;
import com.dianlian.platform.knowledge.application.KnowledgeWriteStatus;
import com.dianlian.platform.knowledge.application.KnowledgeWrites;
import com.dianlian.platform.knowledge.domain.KnowledgeBinding;
import com.dianlian.platform.knowledge.domain.KnowledgeDocumentVersion;
import com.dianlian.platform.knowledge.domain.KnowledgeGrant;
import com.dianlian.platform.knowledge.domain.KnowledgeSpace;
import com.dianlian.platform.knowledge.domain.KnowledgeSpaceStatus;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcKnowledgeRepository implements KnowledgeRepository {

    private static final String SPACE_COLUMNS = """
            space_id, owner_scope, tenant_id, space_code, name, description,
            status, created_by, created_at
            """;

    private static final String VERSION_COLUMNS = """
            v.document_id, v.document_version_id, v.space_id, v.tenant_id,
            v.version_no, d.title, d.source_type, d.external_source_key,
            v.object_key, v.content_hash, v.mime_type, v.byte_size,
            v.status, v.created_by, v.created_at
            """;

    private static final String GRANT_COLUMNS = """
            acl.acl_id, acl.space_id, space.owner_scope, space.tenant_id AS space_tenant_id,
            acl.tenant_id AS audience_tenant_id, acl.audience_type, acl.audience_id,
            acl.status, acl.granted_by, acl.granted_at, acl.revoked_by, acl.revoked_at,
            revoke_event.payload ->> 'reason' AS revoke_reason
            """;

    private final JdbcClient jdbcClient;

    public JdbcKnowledgeRepository(JdbcClient jdbcClient) {
        this.jdbcClient = Objects.requireNonNull(jdbcClient, "jdbcClient must not be null");
    }

    @Override
    public Optional<KnowledgeSpace> findSpace(UUID spaceId) {
        return jdbcClient.sql("""
                        SELECT %s
                          FROM dianlian_business.knowledge_space
                         WHERE space_id = :spaceId
                        """.formatted(SPACE_COLUMNS))
                .param("spaceId", spaceId)
                .query(this::mapSpace)
                .optional();
    }

    @Override
    public Optional<KnowledgeGrant> findGrant(UUID grantId) {
        return grantQuery("acl.acl_id = :grantId")
                .param("grantId", grantId)
                .query(this::mapGrant)
                .optional();
    }

    @Override
    public KnowledgeWriteResult<KnowledgeSpace> createSpace(KnowledgeWrites.CreateSpace write) {
        var replay = findSpaceByIdempotency(write.ownerScope(), write.tenantId(), write.actorId(), write.idempotencyKey());
        if (replay.isPresent()) {
            return sameRequest(replay.get().requestHash(), write.requestHash())
                    ? KnowledgeWriteResult.replayed(replay.get().space())
                    : KnowledgeWriteResult.failed(KnowledgeWriteStatus.IDEMPOTENCY_CONFLICT);
        }

        long sequence = nextEventSequence();
        int inserted = jdbcClient.sql("""
                        INSERT INTO dianlian_business.knowledge_space
                            (space_id, owner_scope, tenant_id, space_type, space_code, name, description,
                             status, state_version, resource_version, event_sequence, created_by,
                             request_hash, idempotency_key, created_at, updated_at)
                        VALUES
                            (:spaceId, :ownerScope, :tenantId, :spaceType, :spaceCode, :name, :description,
                             'ACTIVE', 1, 1, :eventSequence, :actorId,
                             :requestHash, :idempotencyKey, :occurredAt, :occurredAt)
                        ON CONFLICT DO NOTHING
                        """)
                .param("spaceId", write.spaceId())
                .param("ownerScope", write.ownerScope().name())
                .param("tenantId", write.tenantId())
                .param("spaceType", write.ownerScope() == KnowledgeOwnerScope.PLATFORM
                        ? "PLATFORM_TEMPLATE" : "ENTERPRISE")
                .param("spaceCode", write.spaceCode())
                .param("name", write.displayName())
                .param("description", write.description())
                .param("eventSequence", sequence)
                .param("actorId", write.actorId())
                .param("requestHash", write.requestHash())
                .param("idempotencyKey", write.idempotencyKey())
                .param("occurredAt", utc(write.occurredAt()))
                .update();
        if (inserted == 0) {
            replay = findSpaceByIdempotency(
                    write.ownerScope(), write.tenantId(), write.actorId(), write.idempotencyKey());
            if (replay.isPresent()) {
                return sameRequest(replay.get().requestHash(), write.requestHash())
                        ? KnowledgeWriteResult.replayed(replay.get().space())
                        : KnowledgeWriteResult.failed(KnowledgeWriteStatus.IDEMPOTENCY_CONFLICT);
            }
            return KnowledgeWriteResult.failed(KnowledgeWriteStatus.RESOURCE_CONFLICT);
        }

        insertEvent(
                sequence,
                write.eventId(),
                write.tenantId(),
                "SPACE",
                write.spaceId(),
                "KNOWLEDGE_SPACE_CREATED",
                1,
                write.actorId(),
                write.requestHash(),
                write.idempotencyKey(),
                "jsonb_build_object('ownerScope', :ownerScope, 'spaceCode', :spaceCode)",
                write.occurredAt(),
                statement -> statement
                        .param("ownerScope", write.ownerScope().name())
                        .param("spaceCode", write.spaceCode())
        );
        return KnowledgeWriteResult.created(new KnowledgeSpace(
                write.spaceId(),
                write.ownerScope(),
                write.tenantId(),
                write.spaceCode(),
                write.displayName(),
                write.description(),
                KnowledgeSpaceStatus.ACTIVE,
                write.actorId(),
                write.occurredAt()
        ));
    }

    @Override
    public KnowledgeWriteResult<KnowledgeDocumentVersion> appendDocumentVersion(
            KnowledgeWrites.AppendDocumentVersion write
    ) {
        var replay = findVersionByIdempotency(write.tenantId(), write.actorId(), write.idempotencyKey());
        if (replay.isPresent()) {
            return matchingVersionReplay(replay.get(), write);
        }

        DocumentState document;
        long documentSequence;
        if (write.createDocument()) {
            documentSequence = nextEventSequence();
            int inserted = jdbcClient.sql("""
                            INSERT INTO dianlian_business.knowledge_document
                                (document_id, space_id, tenant_id, title, source_type, external_source_key,
                                 status, current_version_id, state_version, resource_version, event_sequence,
                                 created_by, request_hash, idempotency_key, created_at, updated_at)
                            VALUES
                                (:documentId, :spaceId, :tenantId, :title, :sourceType, :externalSourceKey,
                                 'PROCESSING', :documentVersionId, 1, 1, :eventSequence,
                                 :actorId, :requestHash, :idempotencyKey, :occurredAt, :occurredAt)
                            ON CONFLICT DO NOTHING
                            """)
                    .param("documentId", write.documentId())
                    .param("spaceId", write.spaceId())
                    .param("tenantId", write.tenantId())
                    .param("title", write.title())
                    .param("sourceType", write.sourceType().name())
                    .param("externalSourceKey", write.externalSourceKey())
                    .param("documentVersionId", write.documentVersionId())
                    .param("eventSequence", documentSequence)
                    .param("actorId", write.actorId())
                    .param("requestHash", write.requestHash())
                    .param("idempotencyKey", write.idempotencyKey())
                    .param("occurredAt", utc(write.occurredAt()))
                    .update();
            if (inserted == 0) {
                replay = findVersionByIdempotency(write.tenantId(), write.actorId(), write.idempotencyKey());
                if (replay.isPresent()) {
                    return matchingVersionReplay(replay.get(), write);
                }
                return KnowledgeWriteResult.failed(KnowledgeWriteStatus.RESOURCE_CONFLICT);
            }
            document = new DocumentState(write.documentId(), 1, 1, 1);
        } else {
            var locked = lockDocument(write.spaceId(), write.documentId());
            if (locked.isEmpty()) {
                return KnowledgeWriteResult.failed(KnowledgeWriteStatus.NOT_FOUND);
            }
            document = locked.get();
            if (document.terminal()) {
                return KnowledgeWriteResult.failed(KnowledgeWriteStatus.NOT_ACTIVE);
            }
            documentSequence = nextEventSequence();
        }

        long revision = write.createDocument() ? 1 : nextDocumentRevision(write.documentId());
        long versionSequence = nextEventSequence();
        int versionInserted = jdbcClient.sql("""
                        INSERT INTO dianlian_business.knowledge_document_version
                            (document_version_id, document_id, space_id, tenant_id, version_no,
                             object_key, content_hash, normalized_text, mime_type, byte_size, metadata,
                             status, access_state, index_state, state_version, resource_version,
                             event_sequence, created_by, request_hash, idempotency_key, created_at, updated_at)
                        VALUES
                            (:documentVersionId, :documentId, :spaceId, :tenantId, :versionNo,
                             :objectKey, :contentHash, NULL, :mimeType, :byteSize, '{}'::JSONB,
                             'DRAFT', 'ACTIVE', 'PENDING', 1, 1,
                             :eventSequence, :actorId, :requestHash, :idempotencyKey, :occurredAt, :occurredAt)
                        ON CONFLICT DO NOTHING
                        """)
                .param("documentVersionId", write.documentVersionId())
                .param("documentId", write.documentId())
                .param("spaceId", write.spaceId())
                .param("tenantId", write.tenantId())
                .param("versionNo", revision)
                .param("objectKey", write.objectKey())
                .param("contentHash", write.contentHash())
                .param("mimeType", write.mediaType())
                .param("byteSize", write.byteSize())
                .param("eventSequence", versionSequence)
                .param("actorId", write.actorId())
                .param("requestHash", write.requestHash())
                .param("idempotencyKey", write.idempotencyKey())
                .param("occurredAt", utc(write.occurredAt()))
                .update();
        if (versionInserted == 0) {
            throw new KnowledgeCommandConflictException(
                    "KNOWLEDGE_DOCUMENT_CONCURRENT_CONFLICT",
                    "document version append lost a concurrent write"
            );
        }

        long documentResourceVersion = document.resourceVersion();
        String documentEventType = "KNOWLEDGE_DOCUMENT_CREATED";
        if (!write.createDocument()) {
            documentResourceVersion = Math.addExact(document.resourceVersion(), 1);
            int updated = jdbcClient.sql("""
                            UPDATE dianlian_business.knowledge_document
                               SET title = :title,
                                   source_type = :sourceType,
                                   external_source_key = :externalSourceKey,
                                   status = 'PROCESSING',
                                   current_version_id = :documentVersionId,
                                   state_version = state_version + 1,
                                   resource_version = resource_version + 1,
                                   event_sequence = :eventSequence,
                                   updated_at = :occurredAt
                             WHERE document_id = :documentId
                               AND space_id = :spaceId
                               AND state_version = :expectedStateVersion
                            """)
                    .param("title", write.title())
                    .param("sourceType", write.sourceType().name())
                    .param("externalSourceKey", write.externalSourceKey())
                    .param("documentVersionId", write.documentVersionId())
                    .param("eventSequence", documentSequence)
                    .param("occurredAt", utc(write.occurredAt()))
                    .param("documentId", write.documentId())
                    .param("spaceId", write.spaceId())
                    .param("expectedStateVersion", document.stateVersion())
                    .update();
            if (updated != 1) {
                throw new KnowledgeCommandConflictException(
                        "KNOWLEDGE_DOCUMENT_CONCURRENT_CONFLICT",
                        "document state changed during version append"
                );
            }
            documentEventType = "KNOWLEDGE_DOCUMENT_VERSION_SELECTED";
        }

        insertEvent(
                documentSequence,
                write.documentEventId(),
                write.tenantId(),
                "DOCUMENT",
                write.documentId(),
                documentEventType,
                documentResourceVersion,
                write.actorId(),
                write.requestHash(),
                write.idempotencyKey(),
                "jsonb_build_object('documentVersionId', :documentVersionId)",
                write.occurredAt(),
                statement -> statement.param("documentVersionId", write.documentVersionId())
        );
        insertEvent(
                versionSequence,
                write.documentVersionEventId(),
                write.tenantId(),
                "DOCUMENT_VERSION",
                write.documentVersionId(),
                "KNOWLEDGE_DOCUMENT_VERSION_REGISTERED",
                1,
                write.actorId(),
                write.requestHash(),
                write.idempotencyKey(),
                "jsonb_build_object('documentId', :documentId, 'state', 'REGISTERED')",
                write.occurredAt(),
                statement -> statement.param("documentId", write.documentId())
        );
        return KnowledgeWriteResult.created(new KnowledgeDocumentVersion(
                write.documentId(),
                write.documentVersionId(),
                write.spaceId(),
                write.tenantId(),
                revision,
                write.title(),
                write.sourceType(),
                write.externalSourceKey(),
                write.objectKey(),
                write.contentHash(),
                write.mediaType(),
                write.byteSize(),
                KnowledgeDocumentVersionState.REGISTERED,
                write.actorId(),
                write.occurredAt()
        ));
    }

    @Override
    public KnowledgeWriteResult<KnowledgeDocumentVersion> completeDocumentNormalization(
            KnowledgeWrites.CompleteDocumentNormalization write
    ) {
        var locked = lockNormalizationTarget(write.tenantId(), write.documentVersionId());
        if (locked.isEmpty()) {
            return KnowledgeWriteResult.failed(KnowledgeWriteStatus.NOT_FOUND);
        }
        NormalizationTarget target = locked.get();

        var replay = findPublicationEvent(write.tenantId(), write.actorId(), write.idempotencyKey());
        if (replay.isPresent()) {
            PublicationEvent event = replay.get();
            return event.aggregateId().equals(write.documentVersionId())
                    && sameRequest(event.requestHash(), write.requestHash())
                    ? KnowledgeWriteResult.replayed(target.version().withState(KnowledgeDocumentVersionState.PUBLISHED))
                    : KnowledgeWriteResult.failed(KnowledgeWriteStatus.IDEMPOTENCY_CONFLICT);
        }

        if (target.documentTerminal() || !"ACTIVE".equals(target.accessState())) {
            return KnowledgeWriteResult.failed(KnowledgeWriteStatus.NOT_ACTIVE);
        }
        if (!Objects.equals(target.currentVersionId(), write.documentVersionId())
                || !"DRAFT".equals(target.versionStatus())
                || !"PROCESSING".equals(target.documentStatus())
                || target.normalizedTextPresent()) {
            return KnowledgeWriteResult.failed(KnowledgeWriteStatus.RESOURCE_CONFLICT);
        }

        long eventSequence = nextEventSequence();
        long resourceVersion = Math.addExact(target.resourceVersion(), 1);
        String tenantPredicate = write.tenantId() == null ? "tenant_id IS NULL" : "tenant_id = :tenantId";
        JdbcClient.StatementSpec statement = jdbcClient.sql("""
                        UPDATE dianlian_business.knowledge_document_version
                           SET normalized_text = :normalizedText,
                               normalized_text_hash = :normalizedTextHash,
                               normalization_profile_version = :normalizationProfileVersion,
                               normalized_at = :occurredAt,
                               status = 'PUBLISHED',
                               index_state = 'PENDING',
                               state_version = state_version + 1,
                               resource_version = resource_version + 1,
                               event_sequence = :eventSequence,
                               updated_at = :occurredAt
                         WHERE document_version_id = :documentVersionId
                           AND %s
                           AND status = 'DRAFT'
                           AND access_state = 'ACTIVE'
                           AND normalized_text IS NULL
                           AND normalized_text_hash IS NULL
                           AND normalization_profile_version IS NULL
                           AND normalized_at IS NULL
                           AND state_version = :expectedStateVersion
                           AND resource_version = :expectedResourceVersion
                        """.formatted(tenantPredicate))
                .param("normalizedText", write.normalizedText())
                .param("normalizedTextHash", write.normalizedTextHash())
                .param("normalizationProfileVersion", write.normalizationProfileVersion())
                .param("occurredAt", utc(write.occurredAt()))
                .param("eventSequence", eventSequence)
                .param("documentVersionId", write.documentVersionId())
                .param("expectedStateVersion", target.stateVersion())
                .param("expectedResourceVersion", target.resourceVersion());
        if (write.tenantId() != null) {
            statement = statement.param("tenantId", write.tenantId());
        }
        if (statement.update() != 1) {
            throw new KnowledgeCommandConflictException(
                    "KNOWLEDGE_DOCUMENT_NORMALIZATION_CONCURRENT_CONFLICT",
                    "knowledge document version changed during normalization completion"
            );
        }

        insertEvent(
                eventSequence,
                write.publishEventId(),
                write.tenantId(),
                "DOCUMENT_VERSION",
                write.documentVersionId(),
                "KNOWLEDGE_DOCUMENT_VERSION_PUBLISHED",
                resourceVersion,
                write.actorId(),
                write.requestHash(),
                write.idempotencyKey(),
                "jsonb_build_object(" +
                        "'documentId', :documentId, " +
                        "'normalizedTextHash', :normalizedTextHash, " +
                        "'normalizationProfileVersion', :normalizationProfileVersion, " +
                        "'indexProfileVersion', :indexProfileVersion, " +
                        "'indexState', 'PENDING')",
                write.occurredAt(),
                eventStatement -> eventStatement
                        .param("documentId", target.version().documentId())
                        .param("normalizedTextHash", write.normalizedTextHash())
                        .param("normalizationProfileVersion", write.normalizationProfileVersion())
                        .param("indexProfileVersion", write.indexProfileVersion())
        );
        insertIndexJob(write, write.lexicalIndexJobId(), resourceVersion, eventSequence, "LEXICAL");
        insertIndexJob(write, write.vectorIndexJobId(), resourceVersion, eventSequence, "VECTOR");

        return KnowledgeWriteResult.created(target.version().withState(KnowledgeDocumentVersionState.PUBLISHED));
    }

    @Override
    public KnowledgeWriteResult<KnowledgeGrant> grantAudience(KnowledgeWrites.GrantAudience write) {
        var replay = findGrantByIdempotency(write.audienceTenantId(), write.actorId(), write.idempotencyKey());
        if (replay.isPresent()) {
            return matchingGrantReplay(replay.get(), write.spaceId(), write.requestHash());
        }

        long sequence = nextEventSequence();
        int inserted = jdbcClient.sql("""
                        INSERT INTO dianlian_business.knowledge_acl
                            (acl_id, space_id, tenant_id, audience_type, audience_id, access_level,
                             status, state_version, resource_version, event_sequence,
                             request_hash, idempotency_key, granted_by, granted_at)
                        VALUES
                            (:grantId, :spaceId, :tenantId, :audienceType, :audienceId, 'READ',
                             'ACTIVE', 1, 1, :eventSequence,
                             :requestHash, :idempotencyKey, :actorId, :occurredAt)
                        ON CONFLICT DO NOTHING
                        """)
                .param("grantId", write.grantId())
                .param("spaceId", write.spaceId())
                .param("tenantId", write.audienceTenantId())
                .param("audienceType", write.audienceType().name())
                .param("audienceId", write.audienceId())
                .param("eventSequence", sequence)
                .param("requestHash", write.requestHash())
                .param("idempotencyKey", write.idempotencyKey())
                .param("actorId", write.actorId())
                .param("occurredAt", utc(write.occurredAt()))
                .update();
        if (inserted == 0) {
            replay = findGrantByIdempotency(write.audienceTenantId(), write.actorId(), write.idempotencyKey());
            if (replay.isPresent()) {
                return matchingGrantReplay(replay.get(), write.spaceId(), write.requestHash());
            }
            return KnowledgeWriteResult.failed(KnowledgeWriteStatus.RESOURCE_CONFLICT);
        }

        insertEvent(
                sequence,
                write.eventId(),
                write.audienceTenantId(),
                "ACL",
                write.grantId(),
                "KNOWLEDGE_ACL_GRANTED",
                1,
                write.actorId(),
                write.requestHash(),
                write.idempotencyKey(),
                "jsonb_build_object('spaceId', :spaceId, 'audienceType', :audienceType, 'audienceId', :audienceId)",
                write.occurredAt(),
                statement -> statement
                        .param("spaceId", write.spaceId())
                        .param("audienceType", write.audienceType().name())
                        .param("audienceId", write.audienceId())
        );
        return KnowledgeWriteResult.created(new KnowledgeGrant(
                write.grantId(),
                write.spaceId(),
                write.spaceTenantId() == null ? KnowledgeOwnerScope.PLATFORM : KnowledgeOwnerScope.TENANT,
                write.spaceTenantId(),
                write.audienceTenantId(),
                write.audienceType(),
                write.audienceId(),
                KnowledgeGrantStatus.ACTIVE,
                write.actorId(),
                write.occurredAt(),
                null,
                null,
                null
        ));
    }

    @Override
    public KnowledgeWriteResult<KnowledgeGrant> revokeAudience(KnowledgeWrites.RevokeAudience write) {
        var locked = lockGrant(write.grantId());
        if (locked.isEmpty()) {
            return KnowledgeWriteResult.failed(KnowledgeWriteStatus.NOT_FOUND);
        }
        GrantState state = locked.get();
        var replay = findRevokeEvent(state.audienceTenantId(), write.actorId(), write.idempotencyKey());
        if (replay.isPresent()) {
            RevocationEvent event = replay.get();
            if (!event.aggregateId().equals(write.grantId()) || !sameRequest(event.requestHash(), write.requestHash())) {
                return KnowledgeWriteResult.failed(KnowledgeWriteStatus.IDEMPOTENCY_CONFLICT);
            }
            return KnowledgeWriteResult.replayed(findGrant(write.grantId()).orElseThrow());
        }
        if (state.status() != KnowledgeGrantStatus.ACTIVE) {
            return KnowledgeWriteResult.failed(KnowledgeWriteStatus.RESOURCE_CONFLICT);
        }

        long sequence = nextEventSequence();
        int updated = jdbcClient.sql("""
                        UPDATE dianlian_business.knowledge_acl
                           SET status = 'REVOKED',
                               state_version = state_version + 1,
                               resource_version = resource_version + 1,
                               event_sequence = :eventSequence,
                               revoked_by = :actorId,
                               revoked_at = :occurredAt
                         WHERE acl_id = :grantId
                           AND status = 'ACTIVE'
                           AND state_version = :expectedStateVersion
                        """)
                .param("eventSequence", sequence)
                .param("actorId", write.actorId())
                .param("occurredAt", utc(write.occurredAt()))
                .param("grantId", write.grantId())
                .param("expectedStateVersion", state.stateVersion())
                .update();
        if (updated != 1) {
            throw new KnowledgeCommandConflictException(
                    "KNOWLEDGE_GRANT_CONCURRENT_CONFLICT",
                    "knowledge grant changed during revocation"
            );
        }
        long resourceVersion = Math.addExact(state.resourceVersion(), 1);
        insertEvent(
                sequence,
                write.eventId(),
                state.audienceTenantId(),
                "ACL",
                write.grantId(),
                "KNOWLEDGE_ACL_REVOKED",
                resourceVersion,
                write.actorId(),
                write.requestHash(),
                write.idempotencyKey(),
                "jsonb_build_object('reason', :reason)",
                write.occurredAt(),
                statement -> statement.param("reason", write.reason())
        );
        return KnowledgeWriteResult.created(findGrant(write.grantId()).orElseThrow());
    }

    @Override
    public KnowledgeWriteResult<KnowledgeBinding> bindSpace(KnowledgeWrites.BindSpace write) {
        var replay = findBindingByIdempotency(write);
        if (replay.isPresent()) {
            StoredBinding stored = replay.get();
            return sameRequest(stored.requestHash(), write.requestHash()) && bindingMatches(stored.binding(), write)
                    ? KnowledgeWriteResult.replayed(stored.binding())
                    : KnowledgeWriteResult.failed(KnowledgeWriteStatus.IDEMPOTENCY_CONFLICT);
        }

        long sequence = nextEventSequence();
        int inserted = write.targetType() == KnowledgeBindingTargetType.AGENT_VERSION
                ? insertPlatformBinding(write, sequence)
                : insertEnterpriseBinding(write, sequence);
        if (inserted == 0) {
            replay = findBindingByIdempotency(write);
            if (replay.isPresent()) {
                StoredBinding stored = replay.get();
                return sameRequest(stored.requestHash(), write.requestHash()) && bindingMatches(stored.binding(), write)
                        ? KnowledgeWriteResult.replayed(stored.binding())
                        : KnowledgeWriteResult.failed(KnowledgeWriteStatus.IDEMPOTENCY_CONFLICT);
            }
            return KnowledgeWriteResult.failed(KnowledgeWriteStatus.RESOURCE_CONFLICT);
        }

        UUID targetId = write.targetType() == KnowledgeBindingTargetType.AGENT_VERSION
                ? write.agentVersionId() : write.configurationVersionId();
        String aggregateType = write.targetType() == KnowledgeBindingTargetType.AGENT_VERSION
                ? "AGENT_VERSION_BINDING" : "ENTERPRISE_CONFIGURATION_BINDING";
        String eventType = write.targetType() == KnowledgeBindingTargetType.AGENT_VERSION
                ? "KNOWLEDGE_AGENT_VERSION_BOUND" : "KNOWLEDGE_ENTERPRISE_CONFIGURATION_BOUND";
        insertEvent(
                sequence,
                write.eventId(),
                write.tenantId(),
                aggregateType,
                write.bindingId(),
                eventType,
                1,
                write.actorId(),
                write.requestHash(),
                write.idempotencyKey(),
                "jsonb_build_object('spaceId', :spaceId, 'targetId', :targetId)",
                write.occurredAt(),
                statement -> statement
                        .param("spaceId", write.spaceId())
                        .param("targetId", targetId)
        );
        return KnowledgeWriteResult.created(new KnowledgeBinding(
                write.bindingId(),
                write.spaceId(),
                write.tenantId() == null ? KnowledgeOwnerScope.PLATFORM : KnowledgeOwnerScope.TENANT,
                write.tenantId(),
                write.targetType(),
                targetId,
                write.actorId(),
                write.occurredAt()
        ));
    }

    @Override
    public List<AuthorizedKnowledgeResourceRef> resolveAuthorizedResources(
            KnowledgeAuthorizationRequest request
    ) {
        String sql = "WITH " + authorityCtes(audienceValues(request.audienceUserIds().size())) + """
                SELECT :tenantId AS tenant_id,
                       document.document_id AS resource_id,
                       version.document_version_id AS resource_version_id
                  FROM authorized_space authorized
                  JOIN dianlian_business.knowledge_space space
                    ON space.space_id = authorized.space_id
                   AND space.status = 'ACTIVE'
                  JOIN dianlian_business.knowledge_document document
                    ON document.space_id = space.space_id
                   AND document.status IN ('PROCESSING', 'READY')
                  JOIN dianlian_business.knowledge_document_version version
                    ON version.document_id = document.document_id
                   AND version.document_version_id = document.current_version_id
                   AND version.status = 'PUBLISHED'
                   AND version.access_state = 'ACTIVE'
                   AND version.index_state = 'READY'
                 ORDER BY document.document_id, version.document_version_id
                 LIMIT :limit
                """;
        JdbcClient.StatementSpec statement = jdbcClient.sql(sql)
                .param("agentVersionId", request.agentVersionId())
                .param("tenantId", request.tenantId())
                .param("enterpriseAgentId", request.enterpriseAgentId())
                .param("configurationVersionId", request.configurationVersionId())
                .param("observedAt", utc(request.observedAt()))
                .param("limit", request.limit());
        for (int index = 0; index < request.audienceUserIds().size(); index++) {
            statement = statement.param("audience" + index, request.audienceUserIds().get(index));
        }
        return statement.query((resultSet, rowNum) -> new AuthorizedKnowledgeResourceRef(
                resultSet.getObject("tenant_id", UUID.class),
                resultSet.getObject("resource_id", UUID.class),
                resultSet.getObject("resource_version_id", UUID.class)
        )).list();
    }

    @Override
    public List<InvocationKnowledgeEvidenceRef> reauthorizeExactEvidence(
            InvocationKnowledgeReauthorizationQuery query
    ) {
        StringBuilder evidenceValues = new StringBuilder();
        for (int index = 0; index < query.actualEvidence().size(); index++) {
            if (index > 0) evidenceValues.append(", ");
            evidenceValues.append("(CAST(:evidenceOrdinal").append(index).append(" AS INTEGER), ")
                    .append("CAST(:evidenceDocument").append(index).append(" AS UUID), ")
                    .append("CAST(:evidenceVersion").append(index).append(" AS UUID))");
        }
        String sql = """
                WITH requested_evidence(ordinal, document_id, document_version_id) AS (VALUES %s),
                """.formatted(evidenceValues)
                + authorityCtes(audienceValues(query.audienceUserIds().size())) + """
                SELECT requested.document_id,
                       requested.document_version_id
                  FROM requested_evidence requested
                  JOIN dianlian_business.knowledge_document document
                    ON document.document_id = requested.document_id
                   AND document.current_version_id = requested.document_version_id
                   AND document.status IN ('PROCESSING', 'READY')
                  JOIN dianlian_business.knowledge_document_version version
                    ON version.document_id = requested.document_id
                   AND version.document_version_id = requested.document_version_id
                   AND version.status = 'PUBLISHED'
                   AND version.access_state = 'ACTIVE'
                   AND version.index_state = 'READY'
                  JOIN authorized_space authorized
                    ON authorized.space_id = document.space_id
                  JOIN dianlian_business.knowledge_space space
                    ON space.space_id = authorized.space_id
                   AND space.status = 'ACTIVE'
                   AND (
                       (space.owner_scope = 'PLATFORM' AND space.tenant_id IS NULL)
                       OR
                       (space.owner_scope = 'TENANT' AND space.tenant_id = :tenantId)
                   )
                 ORDER BY requested.ordinal
                 LIMIT :limit
                """;
        JdbcClient.StatementSpec statement = jdbcClient.sql(sql)
                .param("agentVersionId", query.agentVersionId())
                .param("tenantId", query.tenantId())
                .param("enterpriseAgentId", query.enterpriseAgentId())
                .param("configurationVersionId", query.configurationVersionId())
                .param("observedAt", utc(query.observedAt()))
                .param("limit", query.limit());
        for (int index = 0; index < query.audienceUserIds().size(); index++) {
            statement = statement.param("audience" + index, query.audienceUserIds().get(index));
        }
        for (int index = 0; index < query.actualEvidence().size(); index++) {
            InvocationKnowledgeEvidenceRef evidence = query.actualEvidence().get(index);
            statement = statement
                    .param("evidenceOrdinal" + index, index)
                    .param("evidenceDocument" + index, evidence.documentId())
                    .param("evidenceVersion" + index, evidence.documentVersionId());
        }
        return statement.query((resultSet, rowNum) -> new InvocationKnowledgeEvidenceRef(
                resultSet.getObject("document_id", UUID.class),
                resultSet.getObject("document_version_id", UUID.class)
        )).list();
    }

    private static String audienceValues(int audienceSize) {
        StringBuilder values = new StringBuilder();
        for (int index = 0; index < audienceSize; index++) {
            if (index > 0) values.append(", ");
            values.append("(CAST(:audience").append(index).append(" AS UUID))");
        }
        return values.toString();
    }

    /** Shared current-execution, binding and full-audience ACL authority predicate. */
    private static String authorityCtes(String audienceValues) {
        return """
                audience(user_id) AS (VALUES %s),
                execution_identity AS (
                    SELECT agent.enterprise_agent_id,
                           configuration.knowledge_scope_mode
                      FROM dianlian_business.enterprise_agent agent
                      JOIN dianlian_business.enterprise_agent_configuration_version configuration
                        ON configuration.tenant_id = agent.tenant_id
                       AND configuration.enterprise_agent_id = agent.enterprise_agent_id
                       AND configuration.configuration_version_id = :configurationVersionId
                       AND configuration.status = 'ACTIVE'
                      JOIN dianlian_business.tenant tenant
                        ON tenant.tenant_id = agent.tenant_id
                       AND tenant.status = 'ACTIVE'
                     WHERE agent.tenant_id = :tenantId
                       AND agent.enterprise_agent_id = :enterpriseAgentId
                       AND agent.agent_version_id = :agentVersionId
                       AND agent.active_configuration_version_id = :configurationVersionId
                       AND agent.status IN ('ACTIVE', 'RESTRICTED')
                ),
                bound_space AS (
                    SELECT binding.space_id
                      FROM dianlian_business.agent_version_knowledge_space binding
                      JOIN execution_identity identity ON TRUE
                     WHERE binding.agent_version_id = :agentVersionId
                       AND binding.status = 'ACTIVE'
                    UNION
                    SELECT binding.space_id
                      FROM dianlian_business.enterprise_agent_configuration_knowledge_space binding
                      JOIN execution_identity identity
                        ON identity.knowledge_scope_mode IN ('ENTERPRISE_AUTHORIZED', 'ENTERPRISE_REQUIRED')
                     WHERE binding.tenant_id = :tenantId
                       AND binding.enterprise_agent_id = :enterpriseAgentId
                       AND binding.configuration_version_id = :configurationVersionId
                       AND binding.status = 'ACTIVE'
                ),
                authorized_space AS (
                    SELECT bound.space_id
                      FROM bound_space bound
                     WHERE (SELECT COUNT(*) FROM audience) = (
                         SELECT COUNT(*)
                           FROM audience
                           JOIN dianlian_business.tenant_member member
                             ON member.tenant_id = :tenantId
                            AND member.user_id = audience.user_id
                            AND member.status = 'ACTIVE'
                            AND (member.expires_at IS NULL OR member.expires_at > :observedAt)
                     )
                       AND NOT EXISTS (
                         SELECT 1
                           FROM audience
                          WHERE NOT EXISTS (
                              SELECT 1
                                FROM dianlian_business.knowledge_acl acl
                               WHERE acl.space_id = bound.space_id
                                 AND acl.tenant_id = :tenantId
                                 AND acl.status = 'ACTIVE'
                                 AND acl.access_level IN ('READ', 'MANAGE')
                                 AND (acl.valid_until IS NULL OR acl.valid_until > :observedAt)
                                 AND (
                                     (acl.audience_type = 'TENANT' AND acl.audience_id = :tenantId)
                                     OR
                                     (acl.audience_type = 'USER' AND acl.audience_id = audience.user_id)
                                 )
                          )
                     )
                )
                """.formatted(audienceValues);
    }

    private Optional<StoredSpace> findSpaceByIdempotency(
            KnowledgeOwnerScope ownerScope,
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        String tenantPredicate = ownerScope == KnowledgeOwnerScope.PLATFORM
                ? "owner_scope = 'PLATFORM' AND tenant_id IS NULL"
                : "owner_scope = 'TENANT' AND tenant_id = :tenantId";
        JdbcClient.StatementSpec statement = jdbcClient.sql("""
                        SELECT %s, request_hash
                          FROM dianlian_business.knowledge_space
                         WHERE %s
                           AND created_by = :actorId
                           AND idempotency_key = :idempotencyKey
                        """.formatted(SPACE_COLUMNS, tenantPredicate))
                .param("actorId", actorId)
                .param("idempotencyKey", idempotencyKey);
        if (tenantId != null) statement = statement.param("tenantId", tenantId);
        return statement.query((resultSet, rowNum) -> new StoredSpace(
                mapSpace(resultSet, rowNum),
                resultSet.getString("request_hash")
        )).optional();
    }

    private Optional<StoredVersion> findVersionByIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        String tenantPredicate = tenantId == null ? "v.tenant_id IS NULL" : "v.tenant_id = :tenantId";
        JdbcClient.StatementSpec statement = jdbcClient.sql("""
                        SELECT %s, v.request_hash
                          FROM dianlian_business.knowledge_document_version v
                          JOIN dianlian_business.knowledge_document d
                            ON d.document_id = v.document_id
                         WHERE %s
                           AND v.created_by = :actorId
                           AND v.idempotency_key = :idempotencyKey
                        """.formatted(VERSION_COLUMNS, tenantPredicate))
                .param("actorId", actorId)
                .param("idempotencyKey", idempotencyKey);
        if (tenantId != null) statement = statement.param("tenantId", tenantId);
        return statement.query((resultSet, rowNum) -> new StoredVersion(
                mapVersion(resultSet, rowNum),
                resultSet.getString("request_hash")
        )).optional();
    }

    private KnowledgeWriteResult<KnowledgeDocumentVersion> matchingVersionReplay(
            StoredVersion replay,
            KnowledgeWrites.AppendDocumentVersion write
    ) {
        boolean sameTarget = replay.version().spaceId().equals(write.spaceId())
                && (write.createDocument() || replay.version().documentId().equals(write.documentId()));
        return sameTarget && sameRequest(replay.requestHash(), write.requestHash())
                ? KnowledgeWriteResult.replayed(replay.version().asRegistered())
                : KnowledgeWriteResult.failed(KnowledgeWriteStatus.IDEMPOTENCY_CONFLICT);
    }

    private Optional<NormalizationTarget> lockNormalizationTarget(UUID tenantId, UUID documentVersionId) {
        String tenantPredicate = tenantId == null ? "v.tenant_id IS NULL" : "v.tenant_id = :tenantId";
        JdbcClient.StatementSpec statement = jdbcClient.sql("""
                        SELECT %s,
                               v.access_state,
                               v.state_version,
                               v.resource_version,
                               v.normalized_text IS NOT NULL AS normalized_text_present,
                               d.current_version_id,
                               d.status AS document_status
                          FROM dianlian_business.knowledge_document_version v
                          JOIN dianlian_business.knowledge_document d
                            ON d.document_id = v.document_id
                           AND d.space_id = v.space_id
                         WHERE v.document_version_id = :documentVersionId
                           AND %s
                         FOR UPDATE OF d, v
                        """.formatted(VERSION_COLUMNS, tenantPredicate))
                .param("documentVersionId", documentVersionId);
        if (tenantId != null) {
            statement = statement.param("tenantId", tenantId);
        }
        return statement.query((resultSet, rowNum) -> new NormalizationTarget(
                mapVersion(resultSet, rowNum),
                resultSet.getString("status"),
                resultSet.getString("access_state"),
                resultSet.getLong("state_version"),
                resultSet.getLong("resource_version"),
                resultSet.getBoolean("normalized_text_present"),
                resultSet.getObject("current_version_id", UUID.class),
                resultSet.getString("document_status"),
                switch (resultSet.getString("document_status")) {
                    case "REVOKED", "DELETED" -> true;
                    default -> false;
                }
        )).optional();
    }

    private Optional<PublicationEvent> findPublicationEvent(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        String tenantPredicate = tenantId == null ? "tenant_id IS NULL" : "tenant_id = :tenantId";
        JdbcClient.StatementSpec statement = jdbcClient.sql("""
                        SELECT aggregate_id, request_hash
                          FROM dianlian_business.knowledge_event
                         WHERE %s
                           AND actor_id = :actorId
                           AND event_type = 'KNOWLEDGE_DOCUMENT_VERSION_PUBLISHED'
                           AND idempotency_key = :idempotencyKey
                        """.formatted(tenantPredicate))
                .param("actorId", actorId)
                .param("idempotencyKey", idempotencyKey);
        if (tenantId != null) {
            statement = statement.param("tenantId", tenantId);
        }
        return statement.query((resultSet, rowNum) -> new PublicationEvent(
                resultSet.getObject("aggregate_id", UUID.class),
                resultSet.getString("request_hash")
        )).optional();
    }

    private Optional<DocumentState> lockDocument(UUID spaceId, UUID documentId) {
        return jdbcClient.sql("""
                        SELECT document_id, state_version, resource_version, status
                          FROM dianlian_business.knowledge_document
                         WHERE space_id = :spaceId
                           AND document_id = :documentId
                         FOR UPDATE
                        """)
                .param("spaceId", spaceId)
                .param("documentId", documentId)
                .query((resultSet, rowNum) -> new DocumentState(
                        resultSet.getObject("document_id", UUID.class),
                        resultSet.getLong("state_version"),
                        resultSet.getLong("resource_version"),
                        switch (resultSet.getString("status")) {
                            case "REVOKED", "DELETED" -> -1;
                            default -> 1;
                        }
                ))
                .optional();
    }

    private long nextDocumentRevision(UUID documentId) {
        return jdbcClient.sql("""
                        SELECT COALESCE(MAX(version_no), 0) + 1
                          FROM dianlian_business.knowledge_document_version
                         WHERE document_id = :documentId
                        """)
                .param("documentId", documentId)
                .query(Long.class)
                .single();
    }

    private Optional<KnowledgeGrant> findGrantByIdempotency(UUID tenantId, UUID actorId, String idempotencyKey) {
        return grantQuery("""
                        acl.tenant_id = :tenantId
                        AND acl.granted_by = :actorId
                        AND acl.idempotency_key = :idempotencyKey
                        """)
                .param("tenantId", tenantId)
                .param("actorId", actorId)
                .param("idempotencyKey", idempotencyKey)
                .query(this::mapGrant)
                .optional();
    }

    private KnowledgeWriteResult<KnowledgeGrant> matchingGrantReplay(
            KnowledgeGrant replay,
            UUID spaceId,
            String requestHash
    ) {
        String storedHash = jdbcClient.sql("""
                        SELECT request_hash
                          FROM dianlian_business.knowledge_acl
                         WHERE acl_id = :grantId
                        """)
                .param("grantId", replay.grantId())
                .query(String.class)
                .single();
        return replay.spaceId().equals(spaceId) && sameRequest(storedHash, requestHash)
                ? KnowledgeWriteResult.replayed(replay)
                : KnowledgeWriteResult.failed(KnowledgeWriteStatus.IDEMPOTENCY_CONFLICT);
    }

    private Optional<GrantState> lockGrant(UUID grantId) {
        return jdbcClient.sql("""
                        SELECT acl_id, tenant_id, status, state_version, resource_version
                          FROM dianlian_business.knowledge_acl
                         WHERE acl_id = :grantId
                         FOR UPDATE
                        """)
                .param("grantId", grantId)
                .query((resultSet, rowNum) -> new GrantState(
                        resultSet.getObject("acl_id", UUID.class),
                        resultSet.getObject("tenant_id", UUID.class),
                        KnowledgeGrantStatus.valueOf(resultSet.getString("status")),
                        resultSet.getLong("state_version"),
                        resultSet.getLong("resource_version")
                ))
                .optional();
    }

    private Optional<RevocationEvent> findRevokeEvent(UUID tenantId, UUID actorId, String idempotencyKey) {
        return jdbcClient.sql("""
                        SELECT aggregate_id, request_hash
                          FROM dianlian_business.knowledge_event
                         WHERE tenant_id = :tenantId
                           AND actor_id = :actorId
                           AND event_type = 'KNOWLEDGE_ACL_REVOKED'
                           AND idempotency_key = :idempotencyKey
                        """)
                .param("tenantId", tenantId)
                .param("actorId", actorId)
                .param("idempotencyKey", idempotencyKey)
                .query((resultSet, rowNum) -> new RevocationEvent(
                        resultSet.getObject("aggregate_id", UUID.class),
                        resultSet.getString("request_hash")
                ))
                .optional();
    }

    private Optional<StoredBinding> findBindingByIdempotency(KnowledgeWrites.BindSpace write) {
        if (write.targetType() == KnowledgeBindingTargetType.AGENT_VERSION) {
            return jdbcClient.sql("""
                            SELECT binding_id, space_id, agent_version_id AS target_id,
                                   created_by, created_at, request_hash
                              FROM dianlian_business.agent_version_knowledge_space
                             WHERE created_by = :actorId
                               AND idempotency_key = :idempotencyKey
                            """)
                    .param("actorId", write.actorId())
                    .param("idempotencyKey", write.idempotencyKey())
                    .query((resultSet, rowNum) -> new StoredBinding(
                            mapBinding(resultSet, KnowledgeOwnerScope.PLATFORM, null,
                                    KnowledgeBindingTargetType.AGENT_VERSION),
                            resultSet.getString("request_hash")
                    ))
                    .optional();
        }
        return jdbcClient.sql("""
                        SELECT binding_id, space_id, configuration_version_id AS target_id,
                               created_by, created_at, request_hash
                          FROM dianlian_business.enterprise_agent_configuration_knowledge_space
                         WHERE tenant_id = :tenantId
                           AND created_by = :actorId
                           AND idempotency_key = :idempotencyKey
                        """)
                .param("tenantId", write.tenantId())
                .param("actorId", write.actorId())
                .param("idempotencyKey", write.idempotencyKey())
                .query((resultSet, rowNum) -> new StoredBinding(
                        mapBinding(resultSet, KnowledgeOwnerScope.TENANT, write.tenantId(),
                                KnowledgeBindingTargetType.ENTERPRISE_CONFIGURATION),
                        resultSet.getString("request_hash")
                ))
                .optional();
    }

    private int insertPlatformBinding(KnowledgeWrites.BindSpace write, long sequence) {
        return jdbcClient.sql("""
                        INSERT INTO dianlian_business.agent_version_knowledge_space
                            (binding_id, tenant_id, agent_template_id, agent_version_id, space_id,
                             status, state_version, resource_version, event_sequence,
                             request_hash, idempotency_key, created_by, created_at)
                        VALUES
                            (:bindingId, NULL, :agentTemplateId, :agentVersionId, :spaceId,
                             'ACTIVE', 1, 1, :eventSequence,
                             :requestHash, :idempotencyKey, :actorId, :occurredAt)
                        ON CONFLICT DO NOTHING
                        """)
                .param("bindingId", write.bindingId())
                .param("agentTemplateId", write.agentTemplateId())
                .param("agentVersionId", write.agentVersionId())
                .param("spaceId", write.spaceId())
                .param("eventSequence", sequence)
                .param("requestHash", write.requestHash())
                .param("idempotencyKey", write.idempotencyKey())
                .param("actorId", write.actorId())
                .param("occurredAt", utc(write.occurredAt()))
                .update();
    }

    private int insertEnterpriseBinding(KnowledgeWrites.BindSpace write, long sequence) {
        return jdbcClient.sql("""
                        INSERT INTO dianlian_business.enterprise_agent_configuration_knowledge_space
                            (binding_id, tenant_id, enterprise_agent_id, configuration_version_id, space_id,
                             status, state_version, resource_version, event_sequence,
                             request_hash, idempotency_key, created_by, created_at)
                        VALUES
                            (:bindingId, :tenantId, :enterpriseAgentId, :configurationVersionId, :spaceId,
                             'ACTIVE', 1, 1, :eventSequence,
                             :requestHash, :idempotencyKey, :actorId, :occurredAt)
                        ON CONFLICT DO NOTHING
                        """)
                .param("bindingId", write.bindingId())
                .param("tenantId", write.tenantId())
                .param("enterpriseAgentId", write.enterpriseAgentId())
                .param("configurationVersionId", write.configurationVersionId())
                .param("spaceId", write.spaceId())
                .param("eventSequence", sequence)
                .param("requestHash", write.requestHash())
                .param("idempotencyKey", write.idempotencyKey())
                .param("actorId", write.actorId())
                .param("occurredAt", utc(write.occurredAt()))
                .update();
    }

    private boolean bindingMatches(KnowledgeBinding binding, KnowledgeWrites.BindSpace write) {
        UUID targetId = write.targetType() == KnowledgeBindingTargetType.AGENT_VERSION
                ? write.agentVersionId() : write.configurationVersionId();
        return binding.spaceId().equals(write.spaceId())
                && binding.targetType() == write.targetType()
                && binding.targetId().equals(targetId);
    }

    private long nextEventSequence() {
        return jdbcClient.sql("SELECT NEXTVAL('dianlian_business.context_event_sequence')")
                .query(Long.class)
                .single();
    }

    private void insertIndexJob(
            KnowledgeWrites.CompleteDocumentNormalization write,
            UUID jobId,
            long resourceVersion,
            long eventSequence,
            String indexTarget
    ) {
        int inserted = jdbcClient.sql("""
                        INSERT INTO dianlian_business.context_index_job
                            (job_id, tenant_id, authority_scope, resource_type, resource_id,
                             resource_version, event_sequence, index_target, index_profile_version,
                             operation, status,
                             attempt_count, next_attempt_at, created_at, updated_at)
                        VALUES
                            (:jobId, :tenantId, :authorityScope, 'KNOWLEDGE_DOCUMENT_VERSION', :resourceId,
                             :resourceVersion, :eventSequence, :indexTarget, :indexProfileVersion,
                             'UPSERT', 'PENDING',
                             0, :occurredAt, :occurredAt, :occurredAt)
                        ON CONFLICT DO NOTHING
                        """)
                .param("jobId", jobId)
                .param("tenantId", write.tenantId())
                .param("authorityScope", write.tenantId() == null ? "PLATFORM" : "TENANT")
                .param("resourceId", write.documentVersionId())
                .param("resourceVersion", resourceVersion)
                .param("eventSequence", eventSequence)
                .param("indexTarget", indexTarget)
                .param("indexProfileVersion", write.indexProfileVersion())
                .param("occurredAt", utc(write.occurredAt()))
                .update();
        if (inserted != 1) {
            throw new KnowledgeCommandConflictException(
                    "KNOWLEDGE_INDEX_JOB_CONFLICT",
                    "knowledge projection job conflicts with an existing authority event"
            );
        }
    }

    private void insertEvent(
            long sequence,
            UUID eventId,
            UUID tenantId,
            String aggregateType,
            UUID aggregateId,
            String eventType,
            long resourceVersion,
            UUID actorId,
            String requestHash,
            String idempotencyKey,
            String payloadExpression,
            Instant occurredAt,
            StatementCustomizer customizer
    ) {
        JdbcClient.StatementSpec statement = jdbcClient.sql("""
                        INSERT INTO dianlian_business.knowledge_event
                            (event_sequence, event_id, tenant_id, aggregate_type, aggregate_id,
                             event_type, resource_version, actor_id, request_hash, idempotency_key,
                             payload, occurred_at)
                        VALUES
                            (:eventSequence, :eventId, :tenantId, :aggregateType, :aggregateId,
                             :eventType, :resourceVersion, :actorId, :requestHash, :idempotencyKey,
                             %s, :occurredAt)
                        """.formatted(payloadExpression))
                .param("eventSequence", sequence)
                .param("eventId", eventId)
                .param("tenantId", tenantId)
                .param("aggregateType", aggregateType)
                .param("aggregateId", aggregateId)
                .param("eventType", eventType)
                .param("resourceVersion", resourceVersion)
                .param("actorId", actorId)
                .param("requestHash", requestHash)
                .param("idempotencyKey", idempotencyKey)
                .param("occurredAt", utc(occurredAt));
        customizer.customize(statement).update();
    }

    private JdbcClient.StatementSpec grantQuery(String predicate) {
        return jdbcClient.sql("""
                SELECT %s
                  FROM dianlian_business.knowledge_acl acl
                  JOIN dianlian_business.knowledge_space space
                    ON space.space_id = acl.space_id
                  LEFT JOIN LATERAL (
                      SELECT event.payload
                        FROM dianlian_business.knowledge_event event
                       WHERE event.aggregate_type = 'ACL'
                         AND event.aggregate_id = acl.acl_id
                         AND event.event_type = 'KNOWLEDGE_ACL_REVOKED'
                       ORDER BY event.event_sequence DESC
                       LIMIT 1
                  ) revoke_event ON TRUE
                 WHERE %s
                """.formatted(GRANT_COLUMNS, predicate));
    }

    private KnowledgeSpace mapSpace(ResultSet resultSet, int rowNum) throws SQLException {
        return new KnowledgeSpace(
                resultSet.getObject("space_id", UUID.class),
                KnowledgeOwnerScope.valueOf(resultSet.getString("owner_scope")),
                resultSet.getObject("tenant_id", UUID.class),
                resultSet.getString("space_code"),
                resultSet.getString("name"),
                resultSet.getString("description"),
                KnowledgeSpaceStatus.valueOf(resultSet.getString("status")),
                resultSet.getObject("created_by", UUID.class),
                instant(resultSet, "created_at")
        );
    }

    private KnowledgeDocumentVersion mapVersion(ResultSet resultSet, int rowNum) throws SQLException {
        return new KnowledgeDocumentVersion(
                resultSet.getObject("document_id", UUID.class),
                resultSet.getObject("document_version_id", UUID.class),
                resultSet.getObject("space_id", UUID.class),
                resultSet.getObject("tenant_id", UUID.class),
                resultSet.getLong("version_no"),
                resultSet.getString("title"),
                KnowledgeSourceType.valueOf(resultSet.getString("source_type")),
                resultSet.getString("external_source_key"),
                resultSet.getString("object_key"),
                resultSet.getString("content_hash"),
                resultSet.getString("mime_type"),
                resultSet.getLong("byte_size"),
                switch (resultSet.getString("status")) {
                    case "DRAFT" -> KnowledgeDocumentVersionState.REGISTERED;
                    case "PUBLISHED" -> KnowledgeDocumentVersionState.PUBLISHED;
                    case "SUPERSEDED" -> KnowledgeDocumentVersionState.SUPERSEDED;
                    default -> throw new SQLException("unsupported knowledge document version status");
                },
                resultSet.getObject("created_by", UUID.class),
                instant(resultSet, "created_at")
        );
    }

    private KnowledgeGrant mapGrant(ResultSet resultSet, int rowNum) throws SQLException {
        return new KnowledgeGrant(
                resultSet.getObject("acl_id", UUID.class),
                resultSet.getObject("space_id", UUID.class),
                KnowledgeOwnerScope.valueOf(resultSet.getString("owner_scope")),
                resultSet.getObject("space_tenant_id", UUID.class),
                resultSet.getObject("audience_tenant_id", UUID.class),
                KnowledgeAudienceType.valueOf(resultSet.getString("audience_type")),
                resultSet.getObject("audience_id", UUID.class),
                KnowledgeGrantStatus.valueOf(resultSet.getString("status")),
                resultSet.getObject("granted_by", UUID.class),
                instant(resultSet, "granted_at"),
                resultSet.getObject("revoked_by", UUID.class),
                nullableInstant(resultSet, "revoked_at"),
                resultSet.getString("revoke_reason")
        );
    }

    private KnowledgeBinding mapBinding(
            ResultSet resultSet,
            KnowledgeOwnerScope ownerScope,
            UUID tenantId,
            KnowledgeBindingTargetType targetType
    ) throws SQLException {
        return new KnowledgeBinding(
                resultSet.getObject("binding_id", UUID.class),
                resultSet.getObject("space_id", UUID.class),
                ownerScope,
                tenantId,
                targetType,
                resultSet.getObject("target_id", UUID.class),
                resultSet.getObject("created_by", UUID.class),
                instant(resultSet, "created_at")
        );
    }

    private static Instant instant(ResultSet resultSet, String column) throws SQLException {
        return resultSet.getObject(column, OffsetDateTime.class).toInstant();
    }

    private static Instant nullableInstant(ResultSet resultSet, String column) throws SQLException {
        OffsetDateTime value = resultSet.getObject(column, OffsetDateTime.class);
        return value == null ? null : value.withOffsetSameInstant(ZoneOffset.UTC).toInstant();
    }

    private static OffsetDateTime utc(Instant instant) {
        return instant.atOffset(ZoneOffset.UTC);
    }

    private static boolean sameRequest(String storedHash, String suppliedHash) {
        return Objects.equals(storedHash, suppliedHash);
    }

    private record StoredSpace(KnowledgeSpace space, String requestHash) {
    }

    private record StoredVersion(KnowledgeDocumentVersion version, String requestHash) {
    }

    private record NormalizationTarget(
            KnowledgeDocumentVersion version,
            String versionStatus,
            String accessState,
            long stateVersion,
            long resourceVersion,
            boolean normalizedTextPresent,
            UUID currentVersionId,
            String documentStatus,
            boolean documentTerminal
    ) {
    }

    private record PublicationEvent(UUID aggregateId, String requestHash) {
    }

    private record StoredBinding(KnowledgeBinding binding, String requestHash) {
    }

    private record DocumentState(UUID documentId, long stateVersion, long resourceVersion, int activeMarker) {
        boolean terminal() {
            return activeMarker < 0;
        }
    }

    private record GrantState(
            UUID grantId,
            UUID audienceTenantId,
            KnowledgeGrantStatus status,
            long stateVersion,
            long resourceVersion
    ) {
    }

    private record RevocationEvent(UUID aggregateId, String requestHash) {
    }

    @FunctionalInterface
    private interface StatementCustomizer {
        JdbcClient.StatementSpec customize(JdbcClient.StatementSpec statement);
    }
}

package com.dianlian.platform.knowledge.application;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import com.dianlian.platform.knowledge.api.AppendKnowledgeDocumentVersionCommand;
import com.dianlian.platform.knowledge.api.AuthorizedKnowledgeResourceRef;
import com.dianlian.platform.knowledge.api.BindEnterpriseKnowledgeSpaceCommand;
import com.dianlian.platform.knowledge.api.BindPlatformKnowledgeSpaceCommand;
import com.dianlian.platform.knowledge.api.CompleteKnowledgeDocumentNormalizationCommand;
import com.dianlian.platform.knowledge.api.CreateKnowledgeSpaceCommand;
import com.dianlian.platform.knowledge.api.EnterpriseKnowledgeCommands;
import com.dianlian.platform.knowledge.api.GrantKnowledgeAudienceCommand;
import com.dianlian.platform.knowledge.api.KnowledgeAccessDeniedException;
import com.dianlian.platform.knowledge.api.KnowledgeAudienceType;
import com.dianlian.platform.knowledge.api.KnowledgeAuthorizationSource;
import com.dianlian.platform.knowledge.api.KnowledgeBindingTargetType;
import com.dianlian.platform.knowledge.api.KnowledgeBindingView;
import com.dianlian.platform.knowledge.api.KnowledgeCommandConflictException;
import com.dianlian.platform.knowledge.api.KnowledgeCommandOutcome;
import com.dianlian.platform.knowledge.api.KnowledgeDocumentVersionView;
import com.dianlian.platform.knowledge.api.KnowledgeGrantView;
import com.dianlian.platform.knowledge.api.KnowledgeOwnerScope;
import com.dianlian.platform.knowledge.api.KnowledgePermissions;
import com.dianlian.platform.knowledge.api.KnowledgeResourceNotDiscoverableException;
import com.dianlian.platform.knowledge.api.KnowledgeSpaceView;
import com.dianlian.platform.knowledge.api.PlatformKnowledgeCommands;
import com.dianlian.platform.knowledge.api.ResolveAuthorizedKnowledgeResourcesQuery;
import com.dianlian.platform.knowledge.api.RevokeKnowledgeAudienceCommand;
import com.dianlian.platform.knowledge.domain.KnowledgeBinding;
import com.dianlian.platform.knowledge.domain.KnowledgeDocumentVersion;
import com.dianlian.platform.knowledge.domain.KnowledgeGrant;
import com.dianlian.platform.knowledge.domain.KnowledgeSpace;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.function.Function;
import java.util.function.Supplier;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class KnowledgeApplicationService implements
        PlatformKnowledgeCommands,
        EnterpriseKnowledgeCommands,
        KnowledgeAuthorizationSource {

    private final KnowledgeRepository repository;
    private final Clock clock;
    private final Supplier<UUID> idGenerator;

    @Autowired
    public KnowledgeApplicationService(KnowledgeRepository repository) {
        this(repository, Clock.systemUTC(), UUID::randomUUID);
    }

    KnowledgeApplicationService(KnowledgeRepository repository, Clock clock, Supplier<UUID> idGenerator) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
        this.idGenerator = Objects.requireNonNull(idGenerator, "idGenerator must not be null");
    }

    @Override
    @Transactional
    public KnowledgeCommandOutcome<KnowledgeSpaceView> createPlatformSpace(
            CreateKnowledgeSpaceCommand command,
            PlatformAccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePlatformPermission(accessContext, KnowledgePermissions.PLATFORM_MANAGE);
        return createSpace(command, KnowledgeOwnerScope.PLATFORM, null, accessContext.actorId().value());
    }

    @Override
    @Transactional
    public KnowledgeCommandOutcome<KnowledgeSpaceView> createEnterpriseSpace(
            CreateKnowledgeSpaceCommand command,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePermission(accessContext, KnowledgePermissions.ENTERPRISE_MANAGE);
        return createSpace(
                command,
                KnowledgeOwnerScope.TENANT,
                accessContext.tenantId().value(),
                accessContext.actorId().value()
        );
    }

    @Override
    @Transactional
    public KnowledgeCommandOutcome<KnowledgeDocumentVersionView> appendPlatformDocumentVersion(
            AppendKnowledgeDocumentVersionCommand command,
            PlatformAccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePlatformPermission(accessContext, KnowledgePermissions.PLATFORM_MANAGE);
        KnowledgeSpace space = requireOwnedActiveSpace(command.spaceId(), KnowledgeOwnerScope.PLATFORM, null);
        return appendDocumentVersion(command, space, accessContext.actorId().value());
    }

    @Override
    @Transactional
    public KnowledgeCommandOutcome<KnowledgeDocumentVersionView> appendEnterpriseDocumentVersion(
            AppendKnowledgeDocumentVersionCommand command,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePermission(accessContext, KnowledgePermissions.ENTERPRISE_MANAGE);
        UUID tenantId = accessContext.tenantId().value();
        KnowledgeSpace space = requireOwnedActiveSpace(command.spaceId(), KnowledgeOwnerScope.TENANT, tenantId);
        return appendDocumentVersion(command, space, accessContext.actorId().value());
    }

    @Override
    @Transactional
    public KnowledgeCommandOutcome<KnowledgeDocumentVersionView> completePlatformDocumentNormalization(
            CompleteKnowledgeDocumentNormalizationCommand command,
            PlatformAccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePlatformPermission(accessContext, KnowledgePermissions.PLATFORM_MANAGE);
        return completeDocumentNormalization(command, null, accessContext.actorId().value());
    }

    @Override
    @Transactional
    public KnowledgeCommandOutcome<KnowledgeDocumentVersionView> completeEnterpriseDocumentNormalization(
            CompleteKnowledgeDocumentNormalizationCommand command,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePermission(accessContext, KnowledgePermissions.ENTERPRISE_MANAGE);
        return completeDocumentNormalization(
                command,
                accessContext.tenantId().value(),
                accessContext.actorId().value()
        );
    }

    @Override
    @Transactional
    public KnowledgeCommandOutcome<KnowledgeGrantView> grantPlatformAudience(
            GrantKnowledgeAudienceCommand command,
            PlatformAccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePlatformPermission(accessContext, KnowledgePermissions.PLATFORM_MANAGE);
        KnowledgeSpace space = requireOwnedActiveSpace(command.spaceId(), KnowledgeOwnerScope.PLATFORM, null);
        return grantAudience(command, space, accessContext.actorId().value());
    }

    @Override
    @Transactional
    public KnowledgeCommandOutcome<KnowledgeGrantView> grantEnterpriseAudience(
            GrantKnowledgeAudienceCommand command,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePermission(accessContext, KnowledgePermissions.ENTERPRISE_MANAGE);
        UUID tenantId = accessContext.tenantId().value();
        if (!tenantId.equals(command.audienceTenantId())) {
            throw new KnowledgeResourceNotDiscoverableException();
        }
        KnowledgeSpace space = requireOwnedActiveSpace(command.spaceId(), KnowledgeOwnerScope.TENANT, tenantId);
        return grantAudience(command, space, accessContext.actorId().value());
    }

    @Override
    @Transactional
    public KnowledgeCommandOutcome<KnowledgeGrantView> revokePlatformAudience(
            RevokeKnowledgeAudienceCommand command,
            PlatformAccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePlatformPermission(accessContext, KnowledgePermissions.PLATFORM_MANAGE);
        requireOwnedGrant(command.grantId(), KnowledgeOwnerScope.PLATFORM, null);
        return revokeAudience(command, accessContext.actorId().value());
    }

    @Override
    @Transactional
    public KnowledgeCommandOutcome<KnowledgeGrantView> revokeEnterpriseAudience(
            RevokeKnowledgeAudienceCommand command,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePermission(accessContext, KnowledgePermissions.ENTERPRISE_MANAGE);
        requireOwnedGrant(command.grantId(), KnowledgeOwnerScope.TENANT, accessContext.tenantId().value());
        return revokeAudience(command, accessContext.actorId().value());
    }

    @Override
    @Transactional
    public KnowledgeCommandOutcome<KnowledgeBindingView> bindPlatformAgentVersion(
            BindPlatformKnowledgeSpaceCommand command,
            PlatformAccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePlatformPermission(accessContext, KnowledgePermissions.PLATFORM_MANAGE);
        requireOwnedActiveSpace(command.spaceId(), KnowledgeOwnerScope.PLATFORM, null);
        Instant now = clock.instant();
        var write = new KnowledgeWrites.BindSpace(
                idGenerator.get(),
                idGenerator.get(),
                command.spaceId(),
                null,
                KnowledgeBindingTargetType.AGENT_VERSION,
                command.agentTemplateId(),
                command.agentVersionId(),
                null,
                null,
                command.requestHash(),
                command.idempotencyKey(),
                accessContext.actorId().value(),
                now
        );
        return bindingOutcome(repository.bindSpace(write));
    }

    @Override
    @Transactional
    public KnowledgeCommandOutcome<KnowledgeBindingView> bindEnterpriseConfiguration(
            BindEnterpriseKnowledgeSpaceCommand command,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePermission(accessContext, KnowledgePermissions.ENTERPRISE_MANAGE);
        UUID tenantId = accessContext.tenantId().value();
        requireOwnedActiveSpace(command.spaceId(), KnowledgeOwnerScope.TENANT, tenantId);
        Instant now = clock.instant();
        var write = new KnowledgeWrites.BindSpace(
                idGenerator.get(),
                idGenerator.get(),
                command.spaceId(),
                tenantId,
                KnowledgeBindingTargetType.ENTERPRISE_CONFIGURATION,
                null,
                null,
                command.enterpriseAgentId(),
                command.configurationVersionId(),
                command.requestHash(),
                command.idempotencyKey(),
                accessContext.actorId().value(),
                now
        );
        return bindingOutcome(repository.bindSpace(write));
    }

    @Override
    @Transactional(readOnly = true)
    public List<AuthorizedKnowledgeResourceRef> resolveAuthorizedResources(
            ResolveAuthorizedKnowledgeResourcesQuery query,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(query, "query must not be null");
        requirePermission(accessContext, KnowledgePermissions.ENTERPRISE_READ);
        UUID actorId = accessContext.actorId().value();
        if (!query.audienceUserIds().contains(actorId)) {
            throw new IllegalArgumentException("audienceUserIds must include the authenticated actor");
        }
        return List.copyOf(repository.resolveAuthorizedResources(new KnowledgeAuthorizationRequest(
                accessContext.tenantId().value(),
                query.agentVersionId(),
                query.enterpriseAgentId(),
                query.configurationVersionId(),
                query.audienceUserIds(),
                query.limit(),
                clock.instant()
        )));
    }

    private KnowledgeCommandOutcome<KnowledgeSpaceView> createSpace(
            CreateKnowledgeSpaceCommand command,
            KnowledgeOwnerScope ownerScope,
            UUID tenantId,
            UUID actorId
    ) {
        Instant now = clock.instant();
        var result = repository.createSpace(new KnowledgeWrites.CreateSpace(
                idGenerator.get(),
                idGenerator.get(),
                ownerScope,
                tenantId,
                command.spaceCode(),
                command.displayName(),
                command.description(),
                command.requestHash(),
                command.idempotencyKey(),
                actorId,
                now
        ));
        return outcome(result, KnowledgeSpace::toView, "KNOWLEDGE_SPACE_CONFLICT");
    }

    private KnowledgeCommandOutcome<KnowledgeDocumentVersionView> appendDocumentVersion(
            AppendKnowledgeDocumentVersionCommand command,
            KnowledgeSpace space,
            UUID actorId
    ) {
        Instant now = clock.instant();
        boolean createDocument = command.documentId() == null;
        UUID documentId = createDocument ? idGenerator.get() : command.documentId();
        var result = repository.appendDocumentVersion(new KnowledgeWrites.AppendDocumentVersion(
                documentId,
                createDocument,
                idGenerator.get(),
                idGenerator.get(),
                idGenerator.get(),
                space.spaceId(),
                space.tenantId(),
                command.title(),
                command.sourceType(),
                command.externalSourceKey(),
                command.sourceRef(),
                command.contentHash(),
                command.mediaType(),
                command.contentLength(),
                command.requestHash(),
                command.idempotencyKey(),
                actorId,
                now
        ));
        return outcome(result, KnowledgeDocumentVersion::toView, "KNOWLEDGE_DOCUMENT_CONFLICT");
    }

    private KnowledgeCommandOutcome<KnowledgeDocumentVersionView> completeDocumentNormalization(
            CompleteKnowledgeDocumentNormalizationCommand command,
            UUID tenantId,
            UUID actorId
    ) {
        String actualHash = sha256(command.normalizedText());
        if (!actualHash.equals(command.normalizedTextHash())) {
            throw new KnowledgeCommandConflictException(
                    "KNOWLEDGE_NORMALIZED_TEXT_HASH_MISMATCH",
                    "normalizedTextHash does not match normalizedText"
            );
        }

        var result = repository.completeDocumentNormalization(new KnowledgeWrites.CompleteDocumentNormalization(
                command.documentVersionId(),
                idGenerator.get(),
                idGenerator.get(),
                idGenerator.get(),
                tenantId,
                command.normalizedText(),
                command.normalizedTextHash(),
                command.normalizationProfileVersion(),
                command.indexProfileVersion(),
                command.requestHash(),
                command.idempotencyKey(),
                actorId,
                clock.instant()
        ));
        return outcome(result, KnowledgeDocumentVersion::toView, "KNOWLEDGE_DOCUMENT_NORMALIZATION_CONFLICT");
    }

    private KnowledgeCommandOutcome<KnowledgeGrantView> grantAudience(
            GrantKnowledgeAudienceCommand command,
            KnowledgeSpace space,
            UUID actorId
    ) {
        UUID audienceId = command.audienceType() == KnowledgeAudienceType.TENANT
                ? command.audienceTenantId()
                : command.audienceUserId();
        Instant now = clock.instant();
        var result = repository.grantAudience(new KnowledgeWrites.GrantAudience(
                idGenerator.get(),
                idGenerator.get(),
                space.spaceId(),
                space.tenantId(),
                command.audienceTenantId(),
                command.audienceType(),
                audienceId,
                command.requestHash(),
                command.idempotencyKey(),
                actorId,
                now
        ));
        return outcome(result, KnowledgeGrant::toView, "KNOWLEDGE_GRANT_CONFLICT");
    }

    private KnowledgeCommandOutcome<KnowledgeGrantView> revokeAudience(
            RevokeKnowledgeAudienceCommand command,
            UUID actorId
    ) {
        var result = repository.revokeAudience(new KnowledgeWrites.RevokeAudience(
                command.grantId(),
                idGenerator.get(),
                command.reason(),
                command.requestHash(),
                command.idempotencyKey(),
                actorId,
                clock.instant()
        ));
        return outcome(result, KnowledgeGrant::toView, "KNOWLEDGE_GRANT_REVOKE_CONFLICT");
    }

    private KnowledgeCommandOutcome<KnowledgeBindingView> bindingOutcome(
            KnowledgeWriteResult<KnowledgeBinding> result
    ) {
        return outcome(result, KnowledgeBinding::toView, "KNOWLEDGE_BINDING_CONFLICT");
    }

    private KnowledgeSpace requireOwnedActiveSpace(
            UUID spaceId,
            KnowledgeOwnerScope ownerScope,
            UUID tenantId
    ) {
        KnowledgeSpace space = repository.findSpace(spaceId)
                .filter(candidate -> candidate.ownerScope() == ownerScope)
                .filter(candidate -> Objects.equals(candidate.tenantId(), tenantId))
                .orElseThrow(KnowledgeResourceNotDiscoverableException::new);
        if (!space.active()) {
            throw new KnowledgeCommandConflictException(
                    "KNOWLEDGE_SPACE_NOT_ACTIVE",
                    "knowledge space is not active"
            );
        }
        return space;
    }

    private KnowledgeGrant requireOwnedGrant(
            UUID grantId,
            KnowledgeOwnerScope ownerScope,
            UUID tenantId
    ) {
        return repository.findGrant(grantId)
                .filter(candidate -> candidate.spaceOwnerScope() == ownerScope)
                .filter(candidate -> Objects.equals(candidate.spaceTenantId(), tenantId))
                .orElseThrow(KnowledgeResourceNotDiscoverableException::new);
    }

    private static <T, V> KnowledgeCommandOutcome<V> outcome(
            KnowledgeWriteResult<T> result,
            Function<T, V> mapper,
            String resourceConflictCode
    ) {
        return switch (result.status()) {
            case CREATED -> new KnowledgeCommandOutcome<>(mapper.apply(result.resource()), false);
            case REPLAYED -> new KnowledgeCommandOutcome<>(mapper.apply(result.resource()), true);
            case IDEMPOTENCY_CONFLICT -> throw new KnowledgeCommandConflictException(
                    "KNOWLEDGE_IDEMPOTENCY_KEY_REUSED",
                    "the idempotency key was already used with a different request"
            );
            case RESOURCE_CONFLICT -> throw new KnowledgeCommandConflictException(
                    resourceConflictCode,
                    "the knowledge resource conflicts with an existing immutable fact"
            );
            case NOT_ACTIVE -> throw new KnowledgeCommandConflictException(
                    "KNOWLEDGE_RESOURCE_NOT_ACTIVE",
                    "the knowledge resource is not active"
            );
            case NOT_FOUND -> throw new KnowledgeResourceNotDiscoverableException();
        };
    }

    private static void requirePermission(AccessContext accessContext, String permission) {
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        if (!accessContext.authorities().contains(permission)) {
            throw new KnowledgeAccessDeniedException(permission);
        }
    }

    private static void requirePlatformPermission(PlatformAccessContext accessContext, String permission) {
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        if (!accessContext.authorities().contains(permission)) {
            throw new KnowledgeAccessDeniedException(permission);
        }
    }

    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))
            );
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is not available", exception);
        }
    }
}

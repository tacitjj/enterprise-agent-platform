package com.dianlian.platform.knowledge.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.TenantId;
import com.dianlian.platform.knowledge.api.AuthorizedKnowledgeResourceRef;
import com.dianlian.platform.knowledge.api.CompleteKnowledgeDocumentNormalizationCommand;
import com.dianlian.platform.knowledge.api.CreateKnowledgeSpaceCommand;
import com.dianlian.platform.knowledge.api.GrantKnowledgeAudienceCommand;
import com.dianlian.platform.knowledge.api.KnowledgeAudienceType;
import com.dianlian.platform.knowledge.api.KnowledgeAccessDeniedException;
import com.dianlian.platform.knowledge.api.KnowledgeCommandConflictException;
import com.dianlian.platform.knowledge.api.KnowledgeDocumentVersionState;
import com.dianlian.platform.knowledge.api.KnowledgeOwnerScope;
import com.dianlian.platform.knowledge.api.KnowledgePermissions;
import com.dianlian.platform.knowledge.api.KnowledgeResourceNotDiscoverableException;
import com.dianlian.platform.knowledge.api.KnowledgeSourceType;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeEvidenceRef;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeReauthorizationQuery;
import com.dianlian.platform.knowledge.api.ResolveAuthorizedKnowledgeResourcesQuery;
import com.dianlian.platform.knowledge.api.RevokeKnowledgeAudienceCommand;
import com.dianlian.platform.knowledge.domain.KnowledgeBinding;
import com.dianlian.platform.knowledge.domain.KnowledgeDocumentVersion;
import com.dianlian.platform.knowledge.domain.KnowledgeGrant;
import com.dianlian.platform.knowledge.domain.KnowledgeSpace;
import com.dianlian.platform.knowledge.domain.KnowledgeSpaceStatus;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.function.Function;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class KnowledgeApplicationServiceTests {

    private static final Instant NOW = Instant.parse("2026-08-12T02:00:00Z");
    private static final UUID TENANT_A = UUID.fromString("10000000-0000-4000-8000-000000000001");
    private static final UUID TENANT_B = UUID.fromString("20000000-0000-4000-8000-000000000001");
    private static final UUID ACTOR_A = UUID.fromString("10000000-0000-4000-8000-000000000011");
    private static final UUID ACTOR_B = UUID.fromString("20000000-0000-4000-8000-000000000011");
    private static final UUID AUDIENCE_B = UUID.fromString("10000000-0000-4000-8000-000000000012");
    private static final UUID SPACE_ID = UUID.fromString("30000000-0000-4000-8000-000000000001");
    private static final UUID AGENT_VERSION_ID = UUID.fromString("40000000-0000-4000-8000-000000000001");
    private static final UUID ENTERPRISE_AGENT_ID = UUID.fromString("50000000-0000-4000-8000-000000000001");
    private static final UUID CONFIGURATION_ID = UUID.fromString("60000000-0000-4000-8000-000000000001");

    private RecordingKnowledgeRepository repository;
    private KnowledgeApplicationService service;

    @BeforeEach
    void setUp() {
        repository = new RecordingKnowledgeRepository();
        service = new KnowledgeApplicationService(
                repository,
                Clock.fixed(NOW, ZoneOffset.UTC),
                UUID::randomUUID
        );
    }

    @Test
    void enterpriseSpaceAlwaysUsesAuthenticatedTenantAndSupportsReplay() {
        repository.createSpaceBehavior = write -> KnowledgeWriteResult.replayed(new KnowledgeSpace(
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

        var outcome = service.createEnterpriseSpace(
                new CreateKnowledgeSpaceCommand(
                        "enterprise.manual",
                        "企业制度库",
                        "只登记权威原文",
                        "create-space-1",
                        "sha256:create-space-1"
                ),
                tenantContext(TENANT_A, ACTOR_A, KnowledgePermissions.ENTERPRISE_MANAGE)
        );

        assertThat(repository.createSpaceWrites).singleElement().satisfies(write -> {
            assertThat(write.ownerScope()).isEqualTo(KnowledgeOwnerScope.TENANT);
            assertThat(write.tenantId()).isEqualTo(TENANT_A);
            assertThat(write.actorId()).isEqualTo(ACTOR_A);
        });
        assertThat(outcome.replayed()).isTrue();
        assertThat(outcome.resource().tenantId()).isEqualTo(TENANT_A);
    }

    @Test
    void platformAndEnterprisePermissionsCannotSubstituteForEachOther() {
        assertThatThrownBy(() -> service.createEnterpriseSpace(
                new CreateKnowledgeSpaceCommand(
                        "enterprise.manual",
                        "企业制度库",
                        null,
                        "create-space-2",
                        "sha256:create-space-2"
                ),
                tenantContext(TENANT_A, ACTOR_A, KnowledgePermissions.ENTERPRISE_READ)
        )).isInstanceOf(KnowledgeAccessDeniedException.class);

        assertThatThrownBy(() -> service.createPlatformSpace(
                new CreateKnowledgeSpaceCommand(
                        "platform.manual",
                        "平台行业库",
                        null,
                        "create-space-3",
                        "sha256:create-space-3"
                ),
                platformContext(KnowledgePermissions.PLATFORM_READ)
        )).isInstanceOf(KnowledgeAccessDeniedException.class);

        assertThat(repository.createSpaceWrites).isEmpty();
    }

    @Test
    void resolverPassesTheWholeAudienceAndRequeriesAfterAuthorityChanges() {
        var resource = new AuthorizedKnowledgeResourceRef(TENANT_A, UUID.randomUUID(), UUID.randomUUID());
        repository.authorizationResults.add(List.of(resource));
        repository.authorizationResults.add(List.of());
        var query = new ResolveAuthorizedKnowledgeResourcesQuery(
                AGENT_VERSION_ID,
                ENTERPRISE_AGENT_ID,
                CONFIGURATION_ID,
                List.of(ACTOR_A, AUDIENCE_B),
                100
        );
        AccessContext access = tenantContext(TENANT_A, ACTOR_A, KnowledgePermissions.ENTERPRISE_READ);

        assertThat(service.resolveAuthorizedResources(query, access)).containsExactly(resource);
        assertThat(service.resolveAuthorizedResources(query, access)).isEmpty();

        assertThat(repository.authorizationRequests)
                .hasSize(2)
                .allSatisfy(request -> assertThat(request.audienceUserIds())
                        .containsExactly(ACTOR_A, AUDIENCE_B));
    }

    @Test
    void resolverRejectsAnAudienceThatOmitsTheAuthenticatedActor() {
        var query = new ResolveAuthorizedKnowledgeResourcesQuery(
                AGENT_VERSION_ID,
                ENTERPRISE_AGENT_ID,
                CONFIGURATION_ID,
                List.of(AUDIENCE_B),
                100
        );

        assertThatThrownBy(() -> service.resolveAuthorizedResources(
                query,
                tenantContext(TENANT_A, ACTOR_A, KnowledgePermissions.ENTERPRISE_READ)
        )).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("authenticated actor");
        assertThat(repository.authorizationRequests).isEmpty();
    }

    @Test
    void tenantCannotDiscoverOrRevokeAnotherTenantsGrant() {
        repository.findGrantResult = Optional.of(new KnowledgeGrant(
                UUID.randomUUID(),
                SPACE_ID,
                KnowledgeOwnerScope.TENANT,
                TENANT_B,
                TENANT_B,
                com.dianlian.platform.knowledge.api.KnowledgeAudienceType.TENANT,
                TENANT_B,
                com.dianlian.platform.knowledge.api.KnowledgeGrantStatus.ACTIVE,
                ACTOR_B,
                NOW,
                null,
                null,
                null
        ));

        assertThatThrownBy(() -> service.revokeEnterpriseAudience(
                new RevokeKnowledgeAudienceCommand(
                        UUID.randomUUID(),
                        "撤销",
                        "revoke-1",
                        "sha256:revoke-1"
                ),
                tenantContext(TENANT_A, ACTOR_A, KnowledgePermissions.ENTERPRISE_MANAGE)
        )).isInstanceOf(KnowledgeResourceNotDiscoverableException.class);
        assertThat(repository.revokeAudienceWrites).isEmpty();
    }

    @Test
    void enterpriseCannotGrantKnowledgeToAnotherTenant() {
        assertThatThrownBy(() -> service.grantEnterpriseAudience(
                new GrantKnowledgeAudienceCommand(
                        SPACE_ID,
                        TENANT_B,
                        KnowledgeAudienceType.TENANT,
                        null,
                        "grant-cross-tenant",
                        "sha256:grant-cross-tenant"
                ),
                tenantContext(TENANT_A, ACTOR_A, KnowledgePermissions.ENTERPRISE_MANAGE)
        )).isInstanceOf(KnowledgeResourceNotDiscoverableException.class);
        assertThat(repository.grantAudienceWrites).isEmpty();
    }

    @Test
    void repositoryIdempotencyConflictIsExposedAsStableDomainConflict() {
        repository.createSpaceBehavior = ignored ->
                KnowledgeWriteResult.failed(KnowledgeWriteStatus.IDEMPOTENCY_CONFLICT);

        assertThatThrownBy(() -> service.createPlatformSpace(
                new CreateKnowledgeSpaceCommand(
                        "platform.manual",
                        "平台行业库",
                        null,
                        "create-space-conflict",
                        "sha256:create-space-conflict"
                ),
                platformContext(KnowledgePermissions.PLATFORM_MANAGE)
        )).isInstanceOf(KnowledgeCommandConflictException.class)
                .extracting("code")
                .isEqualTo("KNOWLEDGE_IDEMPOTENCY_KEY_REUSED");
    }

    @Test
    void enterpriseNormalizationUsesAuthenticatedTenantAndPublishesOnlyAfterHashValidation() {
        String normalizedText = "企业制度的规范化正文";
        repository.completeNormalizationBehavior = write -> KnowledgeWriteResult.replayed(version(
                write.documentVersionId(),
                KnowledgeDocumentVersionState.PUBLISHED
        ));

        var outcome = service.completeEnterpriseDocumentNormalization(
                normalizationCommand(UUID.randomUUID(), normalizedText, sha256(normalizedText), "normalize-1"),
                tenantContext(TENANT_A, ACTOR_A, KnowledgePermissions.ENTERPRISE_MANAGE)
        );

        assertThat(repository.completeNormalizationWrites).singleElement().satisfies(write -> {
            assertThat(write.tenantId()).isEqualTo(TENANT_A);
            assertThat(write.actorId()).isEqualTo(ACTOR_A);
            assertThat(write.normalizedText()).isEqualTo(normalizedText);
            assertThat(write.normalizedTextHash()).isEqualTo(sha256(normalizedText));
            assertThat(write.normalizationProfileVersion()).isEqualTo("plain-text-v1");
            assertThat(write.indexProfileVersion()).isEqualTo("context-default-v1");
        });
        assertThat(outcome.replayed()).isTrue();
        assertThat(outcome.resource().state()).isEqualTo(KnowledgeDocumentVersionState.PUBLISHED);
    }

    @Test
    void normalizationRejectsMismatchedTextHashBeforeRepositoryWrite() {
        assertThatThrownBy(() -> service.completePlatformDocumentNormalization(
                normalizationCommand(UUID.randomUUID(), "可信正文", "0".repeat(64), "normalize-bad-hash"),
                platformContext(KnowledgePermissions.PLATFORM_MANAGE)
        )).isInstanceOf(KnowledgeCommandConflictException.class)
                .extracting("code")
                .isEqualTo("KNOWLEDGE_NORMALIZED_TEXT_HASH_MISMATCH");

        assertThat(repository.completeNormalizationWrites).isEmpty();
    }

    @Test
    void normalizationRequiresTheExistingManagePermissionBoundary() {
        assertThatThrownBy(() -> service.completeEnterpriseDocumentNormalization(
                normalizationCommand(UUID.randomUUID(), "正文", sha256("正文"), "normalize-denied"),
                tenantContext(TENANT_A, ACTOR_A, KnowledgePermissions.ENTERPRISE_READ)
        )).isInstanceOf(KnowledgeAccessDeniedException.class);
        assertThat(repository.completeNormalizationWrites).isEmpty();
    }

    @Test
    void resolverQueryRejectsDuplicateAudienceMembers() {
        assertThatThrownBy(() -> new ResolveAuthorizedKnowledgeResourcesQuery(
                AGENT_VERSION_ID,
                ENTERPRISE_AGENT_ID,
                CONFIGURATION_ID,
                List.of(ACTOR_A, ACTOR_A),
                100
        )).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("duplicates");
    }

    private static CompleteKnowledgeDocumentNormalizationCommand normalizationCommand(
            UUID documentVersionId,
            String normalizedText,
            String normalizedTextHash,
            String idempotencyKey
    ) {
        return new CompleteKnowledgeDocumentNormalizationCommand(
                documentVersionId,
                normalizedText,
                normalizedTextHash,
                "plain-text-v1",
                "context-default-v1",
                idempotencyKey,
                "request:" + idempotencyKey
        );
    }

    private static KnowledgeDocumentVersion version(
            UUID documentVersionId,
            KnowledgeDocumentVersionState state
    ) {
        return new KnowledgeDocumentVersion(
                UUID.randomUUID(),
                documentVersionId,
                SPACE_ID,
                TENANT_A,
                1,
                "企业制度",
                KnowledgeSourceType.UPLOAD,
                null,
                "oss://knowledge/version",
                "a".repeat(64),
                "text/plain",
                128,
                state,
                ACTOR_A,
                NOW
        );
    }

    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8))
            );
        } catch (NoSuchAlgorithmException exception) {
            throw new AssertionError(exception);
        }
    }

    private static AccessContext tenantContext(UUID tenantId, UUID actorId, String... permissions) {
        return AccessContext.fromAuthenticatedPrincipal(new AuthenticatedPrincipal(
                UUID.randomUUID(),
                new ActorId(actorId),
                "企业成员",
                null,
                SessionView.AccountStatus.ACTIVE,
                new SessionView.Tenant(
                        new TenantId(tenantId),
                        "企业",
                        SessionView.TenantStatus.ACTIVE,
                        SessionView.MembershipStatus.ACTIVE
                ),
                List.of(new SessionView.RoleGrant("ENTERPRISE_ADMIN", SessionView.DataScopeType.TENANT, tenantId)),
                Set.of(permissions),
                "pv-1",
                NOW,
                NOW.plusSeconds(3600)
        ));
    }

    private static PlatformAccessContext platformContext(String... permissions) {
        UUID actorId = UUID.fromString("90000000-0000-4000-8000-000000000001");
        return PlatformAccessContext.fromAuthenticatedPrincipal(new AuthenticatedPrincipal(
                UUID.randomUUID(),
                new ActorId(actorId),
                "平台管理员",
                null,
                SessionView.AccountStatus.ACTIVE,
                null,
                List.of(new SessionView.RoleGrant("PLATFORM_ADMIN", SessionView.DataScopeType.PLATFORM, actorId)),
                Set.of(permissions),
                "pv-1",
                NOW,
                NOW.plusSeconds(3600)
        ));
    }

    private static final class RecordingKnowledgeRepository implements KnowledgeRepository {

        private final List<KnowledgeWrites.CreateSpace> createSpaceWrites = new ArrayList<>();
        private final List<KnowledgeWrites.GrantAudience> grantAudienceWrites = new ArrayList<>();
        private final List<KnowledgeWrites.RevokeAudience> revokeAudienceWrites = new ArrayList<>();
        private final List<KnowledgeWrites.CompleteDocumentNormalization> completeNormalizationWrites =
                new ArrayList<>();
        private final List<KnowledgeAuthorizationRequest> authorizationRequests = new ArrayList<>();
        private final ArrayDeque<List<AuthorizedKnowledgeResourceRef>> authorizationResults = new ArrayDeque<>();
        private Optional<KnowledgeGrant> findGrantResult = Optional.empty();
        private Function<KnowledgeWrites.CreateSpace, KnowledgeWriteResult<KnowledgeSpace>> createSpaceBehavior =
                ignored -> {
                    throw new AssertionError("unexpected createSpace call");
                };
        private Function<KnowledgeWrites.CompleteDocumentNormalization,
                KnowledgeWriteResult<KnowledgeDocumentVersion>> completeNormalizationBehavior = ignored -> {
                    throw new AssertionError("unexpected completeDocumentNormalization call");
                };

        @Override
        public Optional<KnowledgeSpace> findSpace(UUID spaceId) {
            return Optional.empty();
        }

        @Override
        public Optional<KnowledgeGrant> findGrant(UUID grantId) {
            return findGrantResult;
        }

        @Override
        public KnowledgeWriteResult<KnowledgeSpace> createSpace(KnowledgeWrites.CreateSpace write) {
            createSpaceWrites.add(write);
            return createSpaceBehavior.apply(write);
        }

        @Override
        public KnowledgeWriteResult<KnowledgeDocumentVersion> appendDocumentVersion(
                KnowledgeWrites.AppendDocumentVersion write
        ) {
            throw new AssertionError("unexpected appendDocumentVersion call");
        }

        @Override
        public KnowledgeWriteResult<KnowledgeDocumentVersion> completeDocumentNormalization(
                KnowledgeWrites.CompleteDocumentNormalization write
        ) {
            completeNormalizationWrites.add(write);
            return completeNormalizationBehavior.apply(write);
        }

        @Override
        public KnowledgeWriteResult<KnowledgeGrant> grantAudience(KnowledgeWrites.GrantAudience write) {
            grantAudienceWrites.add(write);
            throw new AssertionError("unexpected grantAudience call");
        }

        @Override
        public KnowledgeWriteResult<KnowledgeGrant> revokeAudience(KnowledgeWrites.RevokeAudience write) {
            revokeAudienceWrites.add(write);
            throw new AssertionError("unexpected revokeAudience call");
        }

        @Override
        public KnowledgeWriteResult<KnowledgeBinding> bindSpace(KnowledgeWrites.BindSpace write) {
            throw new AssertionError("unexpected bindSpace call");
        }

        @Override
        public List<AuthorizedKnowledgeResourceRef> resolveAuthorizedResources(
                KnowledgeAuthorizationRequest request
        ) {
            authorizationRequests.add(request);
            if (authorizationResults.isEmpty()) {
                throw new AssertionError("unexpected resolveAuthorizedResources call");
            }
            return authorizationResults.removeFirst();
        }

        @Override
        public List<InvocationKnowledgeEvidenceRef> reauthorizeExactEvidence(
                InvocationKnowledgeReauthorizationQuery query
        ) {
            throw new AssertionError("unexpected reauthorizeExactEvidence call");
        }
    }
}

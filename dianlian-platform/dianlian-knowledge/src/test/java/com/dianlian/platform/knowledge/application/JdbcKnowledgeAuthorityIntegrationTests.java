package com.dianlian.platform.knowledge.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.TenantId;
import com.dianlian.platform.knowledge.api.AppendKnowledgeDocumentVersionCommand;
import com.dianlian.platform.knowledge.api.BindEnterpriseKnowledgeSpaceCommand;
import com.dianlian.platform.knowledge.api.BindPlatformKnowledgeSpaceCommand;
import com.dianlian.platform.knowledge.api.CompleteKnowledgeDocumentNormalizationCommand;
import com.dianlian.platform.knowledge.api.CreateKnowledgeSpaceCommand;
import com.dianlian.platform.knowledge.api.GrantKnowledgeAudienceCommand;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeAuthorizationQuery;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeEvidenceRef;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeReauthorizationQuery;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeRejectionReason;
import com.dianlian.platform.knowledge.api.KnowledgeAudienceType;
import com.dianlian.platform.knowledge.api.KnowledgeCommandConflictException;
import com.dianlian.platform.knowledge.api.KnowledgeDocumentVersionState;
import com.dianlian.platform.knowledge.api.KnowledgePermissions;
import com.dianlian.platform.knowledge.api.KnowledgeSourceType;
import com.dianlian.platform.knowledge.api.ResolveAuthorizedKnowledgeResourcesQuery;
import com.dianlian.platform.knowledge.api.RevokeKnowledgeAudienceCommand;
import com.dianlian.platform.knowledge.infrastructure.JdbcKnowledgeRepository;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.function.Supplier;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.postgresql.ds.PGSimpleDataSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

class JdbcKnowledgeAuthorityIntegrationTests {

    private static final Instant NOW = Instant.parse("2026-08-12T02:30:00Z");
    private static final UUID TENANT = UUID.fromString("a0000000-0000-4000-8000-000000000001");
    private static final UUID PLATFORM_ACTOR = UUID.fromString("a0000000-0000-4000-8000-000000000010");
    private static final UUID ENTERPRISE_ACTOR = UUID.fromString("a0000000-0000-4000-8000-000000000011");
    private static final UUID SECOND_MEMBER = UUID.fromString("a0000000-0000-4000-8000-000000000012");
    private static final UUID AGENT_TEMPLATE = UUID.fromString("a0000000-0000-4000-8000-000000000020");
    private static final UUID AGENT_VERSION = UUID.fromString("a0000000-0000-4000-8000-000000000021");
    private static final UUID ENTERPRISE_AGENT = UUID.fromString("a0000000-0000-4000-8000-000000000022");
    private static final UUID CONFIGURATION = UUID.fromString("a0000000-0000-4000-8000-000000000023");

    @Test
    void platformAndEnterpriseKnowledgeHonorAudienceIntersectionAndImmediateRevocation() {
        String jdbcUrl = System.getProperty("dianlian.knowledge.jdbc.url", "");
        Assumptions.assumeTrue(!jdbcUrl.isBlank(), "PostgreSQL integration URL was not supplied");

        var dataSource = new PGSimpleDataSource();
        dataSource.setURL(jdbcUrl);
        dataSource.setUser(System.getProperty("dianlian.knowledge.jdbc.user", "dianlian_app"));
        dataSource.setPassword(System.getProperty("dianlian.knowledge.jdbc.password", ""));
        var jdbc = new JdbcTemplate(dataSource);
        seedExecutionIdentity(jdbc);

        var repository = new JdbcKnowledgeRepository(JdbcClient.create(jdbc));
        var service = new KnowledgeApplicationService(repository);
        var invocationAuthority = new InvocationKnowledgeAuthorityService(repository);
        var transactions = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
        transactions.executeWithoutResult(rollback -> {
            PlatformAccessContext platformAccess = platformAccess();
            AccessContext enterpriseManage = enterpriseAccess(
                    KnowledgePermissions.ENTERPRISE_MANAGE,
                    KnowledgePermissions.ENTERPRISE_READ
            );
    
            var platformSpace = inTransaction(transactions, () -> service.createPlatformSpace(
                    new CreateKnowledgeSpaceCommand(
                            "platform.smoke",
                            "平台行业知识",
                            "平台绑定到岗位版本",
                            "platform-space-1",
                            "request:platform-space-1"
                    ),
                    platformAccess
            ));
            var enterpriseSpaceCommand = new CreateKnowledgeSpaceCommand(
                    "enterprise.smoke",
                    "企业知识",
                    "企业配置版本专属知识",
                    "enterprise-space-1",
                    "request:enterprise-space-1"
            );
            var enterpriseSpace = inTransaction(transactions, () -> service.createEnterpriseSpace(
                    enterpriseSpaceCommand,
                    enterpriseManage
            ));
            var enterpriseSpaceReplay = inTransaction(transactions, () -> service.createEnterpriseSpace(
                    enterpriseSpaceCommand,
                    enterpriseManage
            ));
            assertThat(enterpriseSpaceReplay.replayed()).isTrue();
            assertThat(enterpriseSpaceReplay.resource().spaceId()).isEqualTo(enterpriseSpace.resource().spaceId());
    
            var platformDocumentCommand = documentCommand(
                    platformSpace.resource().spaceId(), null, "平台知识", "platform-v1", 'a');
            var platformVersion = inTransaction(transactions, () -> service.appendPlatformDocumentVersion(
                    platformDocumentCommand,
                    platformAccess
            ));
            var platformVersionReplay = inTransaction(transactions, () -> service.appendPlatformDocumentVersion(
                    platformDocumentCommand,
                    platformAccess
            ));
            assertThat(platformVersionReplay.replayed()).isTrue();
            assertThat(platformVersionReplay.resource().documentVersionId())
                    .isEqualTo(platformVersion.resource().documentVersionId());
            assertThat(platformVersion.resource().state()).isEqualTo(KnowledgeDocumentVersionState.REGISTERED);
            assertRegisteredWithoutProjection(jdbc, platformVersion.resource().documentVersionId());

            String platformText = "平台行业知识的规范化正文";
            var platformNormalization = normalizationCommand(
                    platformVersion.resource().documentVersionId(),
                    platformText,
                    "platform-v1"
            );
            var platformPublished = inTransaction(transactions, () -> service.completePlatformDocumentNormalization(
                    platformNormalization,
                    platformAccess
            ));
            var platformPublishedReplay = inTransaction(
                    transactions,
                    () -> service.completePlatformDocumentNormalization(platformNormalization, platformAccess)
            );
            assertThat(platformPublished.resource().state()).isEqualTo(KnowledgeDocumentVersionState.PUBLISHED);
            assertThat(platformPublishedReplay.replayed()).isTrue();
            assertPublishedWithProjectionJobs(
                    jdbc,
                    platformVersion.resource().documentVersionId(),
                    platformText
            );
            assertThat(inTransaction(transactions, () -> service.appendPlatformDocumentVersion(
                    platformDocumentCommand,
                    platformAccess
            )).resource().state()).isEqualTo(KnowledgeDocumentVersionState.REGISTERED);
    
            var enterpriseVersionV1 = inTransaction(transactions, () -> service.appendEnterpriseDocumentVersion(
                    documentCommand(enterpriseSpace.resource().spaceId(), null, "企业知识", "enterprise-v1", 'b'),
                    enterpriseManage
            ));
            String enterpriseV1Text = "企业知识第一版规范化正文";
            inTransaction(transactions, () -> service.completeEnterpriseDocumentNormalization(
                    normalizationCommand(
                            enterpriseVersionV1.resource().documentVersionId(),
                            enterpriseV1Text,
                            "enterprise-v1"
                    ),
                    enterpriseManage
            ));
            markReady(jdbc, platformVersion.resource().documentId(), platformVersion.resource().documentVersionId());
            markReady(jdbc, enterpriseVersionV1.resource().documentId(), enterpriseVersionV1.resource().documentVersionId());
    
            var enterpriseV2Command = documentCommand(
                    enterpriseSpace.resource().spaceId(),
                    enterpriseVersionV1.resource().documentId(),
                    "企业知识（修订）",
                    "enterprise-v2",
                    'c'
            );
            var enterpriseVersion = inTransaction(transactions, () -> service.appendEnterpriseDocumentVersion(
                    enterpriseV2Command,
                    enterpriseManage
            ));
            var enterpriseVersionReplay = inTransaction(transactions, () -> service.appendEnterpriseDocumentVersion(
                    enterpriseV2Command,
                    enterpriseManage
            ));
            assertThat(enterpriseVersion.resource().revision()).isEqualTo(2);
            assertThat(enterpriseVersionReplay.replayed()).isTrue();
            assertThat(enterpriseVersionReplay.resource().documentVersionId())
                    .isEqualTo(enterpriseVersion.resource().documentVersionId());
            String enterpriseV2Text = "企业知识第二版规范化正文";
            inTransaction(transactions, () -> service.completeEnterpriseDocumentNormalization(
                    normalizationCommand(
                            enterpriseVersion.resource().documentVersionId(),
                            enterpriseV2Text,
                            "enterprise-v2"
                    ),
                    enterpriseManage
            ));
            markReady(jdbc, enterpriseVersion.resource().documentId(), enterpriseVersion.resource().documentVersionId());
    
            var platformBindingCommand = new BindPlatformKnowledgeSpaceCommand(
                    platformSpace.resource().spaceId(),
                    AGENT_TEMPLATE,
                    AGENT_VERSION,
                    "bind-platform-1",
                    "request:bind-platform-1"
            );
            inTransaction(transactions, () -> service.bindPlatformAgentVersion(
                    platformBindingCommand,
                    platformAccess
            ));
            var platformBindingReplay = inTransaction(transactions, () -> service.bindPlatformAgentVersion(
                    platformBindingCommand,
                    platformAccess
            ));
            assertThat(platformBindingReplay.replayed()).isTrue();
            inTransaction(transactions, () -> service.bindEnterpriseConfiguration(
                    new BindEnterpriseKnowledgeSpaceCommand(
                            enterpriseSpace.resource().spaceId(),
                            ENTERPRISE_AGENT,
                            CONFIGURATION,
                            "bind-enterprise-1",
                            "request:bind-enterprise-1"
                    ),
                    enterpriseManage
            ));
    
            var platformTenantGrantCommand = tenantGrant(
                    platformSpace.resource().spaceId(), "grant-platform-tenant-1");
            var platformTenantGrant = inTransaction(transactions, () -> service.grantPlatformAudience(
                    platformTenantGrantCommand,
                    platformAccess
            ));
            var platformTenantGrantReplay = inTransaction(transactions, () -> service.grantPlatformAudience(
                    platformTenantGrantCommand,
                    platformAccess
            ));
            assertThat(platformTenantGrantReplay.replayed()).isTrue();
            var enterpriseTenantGrant = inTransaction(transactions, () -> service.grantEnterpriseAudience(
                    tenantGrant(enterpriseSpace.resource().spaceId(), "grant-enterprise-tenant-1"),
                    enterpriseManage
            ));
    
            ResolveAuthorizedKnowledgeResourcesQuery bothMembers = query(List.of(ENTERPRISE_ACTOR, SECOND_MEMBER));
            assertThat(inTransaction(transactions, () -> service.resolveAuthorizedResources(
                    bothMembers,
                    enterpriseManage
            ))).extracting(resource -> resource.resourceVersionId())
                    .containsExactlyInAnyOrder(
                            platformVersion.resource().documentVersionId(),
                            enterpriseVersion.resource().documentVersionId()
                    )
                    .doesNotContain(enterpriseVersionV1.resource().documentVersionId());

            var invocationAuthorization = invocationAuthorization(TENANT);
            assertThat(inTransaction(transactions, () -> invocationAuthority.authorize(
                    invocationAuthorization
            ))).extracting(resource -> resource.resourceVersionId())
                    .containsExactlyInAnyOrder(
                            platformVersion.resource().documentVersionId(),
                            enterpriseVersion.resource().documentVersionId()
                    )
                    .doesNotContain(enterpriseVersionV1.resource().documentVersionId());

            var platformEvidence = new InvocationKnowledgeEvidenceRef(
                    platformVersion.resource().documentId(),
                    platformVersion.resource().documentVersionId()
            );
            var enterpriseEvidence = new InvocationKnowledgeEvidenceRef(
                    enterpriseVersion.resource().documentId(),
                    enterpriseVersion.resource().documentVersionId()
            );
            var staleEnterpriseEvidence = new InvocationKnowledgeEvidenceRef(
                    enterpriseVersionV1.resource().documentId(),
                    enterpriseVersionV1.resource().documentVersionId()
            );
            var unknownEvidence = new InvocationKnowledgeEvidenceRef(UUID.randomUUID(), UUID.randomUUID());
            var exactEvidence = List.of(
                    staleEnterpriseEvidence,
                    enterpriseEvidence,
                    unknownEvidence,
                    platformEvidence
            );
            var initialReauthorization = inTransaction(transactions, () -> invocationAuthority.reauthorize(
                    invocationReauthorization(TENANT, exactEvidence)
            ));
            assertThat(initialReauthorization.allowed())
                    .extracting(resource -> resource.resourceVersionId())
                    .containsExactlyInAnyOrder(
                            platformEvidence.documentVersionId(),
                            enterpriseEvidence.documentVersionId()
                    );
            assertThat(initialReauthorization.rejected())
                    .allMatch(rejected -> rejected.reason()
                            == InvocationKnowledgeRejectionReason.CURRENT_AUTHORITY_DENIED)
                    .extracting(rejected -> rejected.evidence())
                    .containsExactlyInAnyOrder(staleEnterpriseEvidence, unknownEvidence);
    
            var revokePlatformCommand = new RevokeKnowledgeAudienceCommand(
                    platformTenantGrant.resource().grantId(),
                    "停止向企业授权平台知识",
                    "revoke-platform-1",
                    "request:revoke-platform-1"
            );
            inTransaction(transactions, () -> service.revokePlatformAudience(
                    revokePlatformCommand,
                    platformAccess
            ));
            var revokePlatformReplay = inTransaction(transactions, () -> service.revokePlatformAudience(
                    revokePlatformCommand,
                    platformAccess
            ));
            assertThat(revokePlatformReplay.replayed()).isTrue();
            assertThat(inTransaction(transactions, () -> service.resolveAuthorizedResources(
                    bothMembers,
                    enterpriseManage
            ))).extracting(resource -> resource.resourceVersionId())
                    .containsExactly(enterpriseVersion.resource().documentVersionId());

            var revokedReauthorization = inTransaction(transactions, () -> invocationAuthority.reauthorize(
                    invocationReauthorization(TENANT, exactEvidence)
            ));
            assertThat(revokedReauthorization.allowed())
                    .extracting(resource -> resource.resourceVersionId())
                    .containsExactly(enterpriseEvidence.documentVersionId());
            assertThat(revokedReauthorization.rejected())
                    .allMatch(rejected -> rejected.reason()
                            == InvocationKnowledgeRejectionReason.CURRENT_AUTHORITY_DENIED)
                    .extracting(rejected -> rejected.evidence())
                    .containsExactlyInAnyOrder(platformEvidence, staleEnterpriseEvidence, unknownEvidence);

            var wrongTenantReauthorization = inTransaction(transactions, () -> invocationAuthority.reauthorize(
                    invocationReauthorization(UUID.randomUUID(), List.of(platformEvidence))
            ));
            assertThat(wrongTenantReauthorization.allowed()).isEmpty();
            assertThat(wrongTenantReauthorization.rejected())
                    .singleElement()
                    .satisfies(rejected -> {
                        assertThat(rejected.evidence()).isEqualTo(platformEvidence);
                        assertThat(rejected.reason())
                                .isEqualTo(InvocationKnowledgeRejectionReason.CURRENT_AUTHORITY_DENIED);
                    });
    
            var firstUserGrant = inTransaction(transactions, () -> service.grantPlatformAudience(
                    userGrant(platformSpace.resource().spaceId(), ENTERPRISE_ACTOR, "grant-platform-user-1"),
                    platformAccess
            ));
            assertThat(firstUserGrant.resource().audienceUserId()).isEqualTo(ENTERPRISE_ACTOR);
            assertThat(inTransaction(transactions, () -> service.resolveAuthorizedResources(
                    bothMembers,
                    enterpriseManage
            ))).extracting(resource -> resource.resourceVersionId())
                    .doesNotContain(platformVersion.resource().documentVersionId());
    
            inTransaction(transactions, () -> service.grantPlatformAudience(
                    userGrant(platformSpace.resource().spaceId(), SECOND_MEMBER, "grant-platform-user-2"),
                    platformAccess
            ));
            assertThat(inTransaction(transactions, () -> service.resolveAuthorizedResources(
                    bothMembers,
                    enterpriseManage
            ))).extracting(resource -> resource.resourceVersionId())
                    .contains(platformVersion.resource().documentVersionId());
    
            inTransaction(transactions, () -> service.revokeEnterpriseAudience(
                    new RevokeKnowledgeAudienceCommand(
                            enterpriseTenantGrant.resource().grantId(),
                            "撤销企业共享知识",
                            "revoke-enterprise-1",
                            "request:revoke-enterprise-1"
                    ),
                    enterpriseManage
            ));
            assertThat(inTransaction(transactions, () -> service.resolveAuthorizedResources(
                    bothMembers,
                    enterpriseManage
            ))).extracting(resource -> resource.resourceVersionId())
                    .containsExactly(platformVersion.resource().documentVersionId());

            var conflictingNormalizationReplay = new CompleteKnowledgeDocumentNormalizationCommand(
                    platformNormalization.documentVersionId(),
                    platformNormalization.normalizedText(),
                    platformNormalization.normalizedTextHash(),
                    platformNormalization.normalizationProfileVersion(),
                    platformNormalization.indexProfileVersion(),
                    platformNormalization.idempotencyKey(),
                    "request:normalize-platform-v1-different"
            );
            assertThatThrownBy(() -> inTransaction(
                    transactions,
                    () -> service.completePlatformDocumentNormalization(conflictingNormalizationReplay, platformAccess)
            )).isInstanceOf(KnowledgeCommandConflictException.class)
                    .extracting("code")
                    .isEqualTo("KNOWLEDGE_IDEMPOTENCY_KEY_REUSED");
            rollback.setRollbackOnly();
        });
    }

    private static AppendKnowledgeDocumentVersionCommand documentCommand(
            UUID spaceId,
            UUID documentId,
            String title,
            String suffix,
            char hashCharacter
    ) {
        return new AppendKnowledgeDocumentVersionCommand(
                spaceId,
                documentId,
                title,
                KnowledgeSourceType.UPLOAD,
                null,
                "oss://knowledge/" + suffix,
                String.valueOf(hashCharacter).repeat(64),
                "text/plain",
                128,
                "append-" + suffix,
                "request:append-" + suffix
        );
    }

    private static CompleteKnowledgeDocumentNormalizationCommand normalizationCommand(
            UUID documentVersionId,
            String normalizedText,
            String suffix
    ) {
        return new CompleteKnowledgeDocumentNormalizationCommand(
                documentVersionId,
                normalizedText,
                sha256(normalizedText),
                "plain-text-v1",
                "context-default-v1",
                "normalize-" + suffix,
                "request:normalize-" + suffix
        );
    }

    private static void assertRegisteredWithoutProjection(JdbcTemplate jdbc, UUID documentVersionId) {
        assertThat(jdbc.queryForObject("""
                SELECT COUNT(*)
                  FROM dianlian_business.knowledge_document_version
                 WHERE document_version_id = ?
                   AND status = 'DRAFT'
                   AND normalized_text IS NULL
                   AND normalized_text_hash IS NULL
                   AND normalization_profile_version IS NULL
                   AND normalized_at IS NULL
                """, Integer.class, documentVersionId)).isEqualTo(1);
        assertThat(jdbc.queryForObject("""
                SELECT COUNT(*)
                  FROM dianlian_business.knowledge_event
                 WHERE aggregate_type = 'DOCUMENT_VERSION'
                   AND aggregate_id = ?
                   AND event_type = 'KNOWLEDGE_DOCUMENT_VERSION_REGISTERED'
                """, Integer.class, documentVersionId)).isEqualTo(1);
        assertThat(jdbc.queryForObject("""
                SELECT COUNT(*)
                  FROM dianlian_business.context_index_job
                 WHERE resource_type = 'KNOWLEDGE_DOCUMENT_VERSION'
                   AND resource_id = ?
                """, Integer.class, documentVersionId)).isZero();
    }

    private static void assertPublishedWithProjectionJobs(
            JdbcTemplate jdbc,
            UUID documentVersionId,
            String normalizedText
    ) {
        assertThat(jdbc.queryForObject("""
                SELECT COUNT(*)
                  FROM dianlian_business.knowledge_document_version
                 WHERE document_version_id = ?
                   AND status = 'PUBLISHED'
                   AND normalized_text = ?
                   AND normalized_text_hash = ?
                   AND normalization_profile_version = 'plain-text-v1'
                   AND normalized_at IS NOT NULL
                """, Integer.class, documentVersionId, normalizedText, sha256(normalizedText))).isEqualTo(1);
        assertThat(jdbc.queryForObject("""
                SELECT COUNT(*)
                  FROM dianlian_business.knowledge_event
                 WHERE aggregate_type = 'DOCUMENT_VERSION'
                   AND aggregate_id = ?
                   AND event_type = 'KNOWLEDGE_DOCUMENT_VERSION_PUBLISHED'
                """, Integer.class, documentVersionId)).isEqualTo(1);
        assertThat(jdbc.queryForObject("""
                SELECT COUNT(*)
                  FROM dianlian_business.context_index_job
                 WHERE resource_type = 'KNOWLEDGE_DOCUMENT_VERSION'
                   AND resource_id = ?
                   AND operation = 'UPSERT'
                   AND status = 'PENDING'
                   AND index_profile_version = 'context-default-v1'
                   AND index_target IN ('LEXICAL', 'VECTOR')
                """, Integer.class, documentVersionId)).isEqualTo(2);
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

    private static GrantKnowledgeAudienceCommand tenantGrant(UUID spaceId, String key) {
        return new GrantKnowledgeAudienceCommand(
                spaceId,
                TENANT,
                KnowledgeAudienceType.TENANT,
                null,
                key,
                "request:" + key
        );
    }

    private static GrantKnowledgeAudienceCommand userGrant(UUID spaceId, UUID userId, String key) {
        return new GrantKnowledgeAudienceCommand(
                spaceId,
                TENANT,
                KnowledgeAudienceType.USER,
                userId,
                key,
                "request:" + key
        );
    }

    private static ResolveAuthorizedKnowledgeResourcesQuery query(List<UUID> audience) {
        return new ResolveAuthorizedKnowledgeResourcesQuery(
                AGENT_VERSION,
                ENTERPRISE_AGENT,
                CONFIGURATION,
                audience,
                100
        );
    }

    private static InvocationKnowledgeAuthorizationQuery invocationAuthorization(UUID tenantId) {
        return new InvocationKnowledgeAuthorizationQuery(
                tenantId,
                ENTERPRISE_ACTOR,
                AGENT_VERSION,
                ENTERPRISE_AGENT,
                CONFIGURATION,
                List.of(SECOND_MEMBER, ENTERPRISE_ACTOR),
                NOW,
                100
        );
    }

    private static InvocationKnowledgeReauthorizationQuery invocationReauthorization(
            UUID tenantId,
            List<InvocationKnowledgeEvidenceRef> actualEvidence
    ) {
        InvocationKnowledgeAuthorizationQuery authorization = invocationAuthorization(tenantId);
        return new InvocationKnowledgeReauthorizationQuery(
                authorization.tenantId(),
                authorization.actorUserId(),
                authorization.agentVersionId(),
                authorization.enterpriseAgentId(),
                authorization.configurationVersionId(),
                authorization.audienceUserIds(),
                authorization.observedAt(),
                authorization.limit(),
                actualEvidence
        );
    }

    private static void markReady(JdbcTemplate jdbc, UUID documentId, UUID documentVersionId) {
        jdbc.update("""
                UPDATE dianlian_business.knowledge_document_version
                   SET index_state = 'READY',
                       state_version = state_version + 1,
                       resource_version = resource_version + 1,
                       event_sequence = NEXTVAL('dianlian_business.context_event_sequence'),
                       updated_at = CURRENT_TIMESTAMP
                 WHERE document_version_id = ?
                """, documentVersionId);
        jdbc.update("""
                UPDATE dianlian_business.knowledge_document
                   SET status = 'READY',
                       state_version = state_version + 1,
                       resource_version = resource_version + 1,
                       event_sequence = NEXTVAL('dianlian_business.context_event_sequence'),
                       updated_at = CURRENT_TIMESTAMP
                 WHERE document_id = ?
                """, documentId);
    }

    private static void seedExecutionIdentity(JdbcTemplate jdbc) {
        jdbc.update("""
                INSERT INTO dianlian_business.user_account
                    (user_id, display_name, status)
                VALUES (?, '平台管理员', 'ACTIVE'), (?, '企业管理员', 'ACTIVE'), (?, '企业成员', 'ACTIVE')
                ON CONFLICT DO NOTHING
                """, PLATFORM_ACTOR, ENTERPRISE_ACTOR, SECOND_MEMBER);
        jdbc.update("""
                INSERT INTO dianlian_business.tenant
                    (tenant_id, display_name, status)
                VALUES (?, '知识冒烟企业', 'ACTIVE')
                ON CONFLICT DO NOTHING
                """, TENANT);
        jdbc.update("""
                INSERT INTO dianlian_business.tenant_member
                    (member_id, tenant_id, user_id, status)
                VALUES (?, ?, ?, 'ACTIVE'), (?, ?, ?, 'ACTIVE')
                ON CONFLICT DO NOTHING
                """, UUID.randomUUID(), TENANT, ENTERPRISE_ACTOR,
                UUID.randomUUID(), TENANT, SECOND_MEMBER);
        jdbc.update("""
                INSERT INTO dianlian_business.agent_template
                    (agent_template_id, owner_scope, template_code, status, created_by)
                VALUES (?, 'PLATFORM', 'knowledge.smoke', 'ACTIVE', ?)
                ON CONFLICT DO NOTHING
                """, AGENT_TEMPLATE, PLATFORM_ACTOR);
        jdbc.update("""
                INSERT INTO dianlian_business.agent_version
                    (agent_version_id, owner_scope, agent_template_id, template_name, template_description,
                     version_label, capability_code, input_schema, execution_template, point_estimate,
                     status, visibility_mode, visible_tenant_ids, request_hash, publish_idempotency_key,
                     published_by, published_at)
                VALUES
                    (?, 'PLATFORM', ?, '知识冒烟员工', '仅验证知识授权链',
                     '1.0.0', 'KNOWLEDGE_SMOKE', CAST(? AS JSONB), CAST(? AS JSONB), 10,
                     'PUBLISHED', 'ALL', '[]'::JSONB, 'request:publish-smoke', 'publish-smoke',
                     ?, ?)
                ON CONFLICT DO NOTHING
                """,
                AGENT_VERSION,
                AGENT_TEMPLATE,
                "{\"schemaId\":\"knowledge.smoke.input\"}",
                "{\"templateId\":\"knowledge.smoke.flow\",\"steps\":[]}",
                PLATFORM_ACTOR,
                NOW.atOffset(java.time.ZoneOffset.UTC));
        jdbc.update("""
                INSERT INTO dianlian_business.enterprise_agent
                    (enterprise_agent_id, tenant_id, agent_template_id, agent_version_id,
                     employee_code, display_name, status, request_hash, hire_idempotency_key,
                     hired_by, hired_at, state_version)
                VALUES (?, ?, ?, ?, 'knowledge-smoke', '知识冒烟员工', 'DRAFT',
                        'request:hire-smoke', 'hire-smoke', ?, ?, 0)
                ON CONFLICT DO NOTHING
                """, ENTERPRISE_AGENT, TENANT, AGENT_TEMPLATE, AGENT_VERSION,
                ENTERPRISE_ACTOR, NOW.atOffset(java.time.ZoneOffset.UTC));
        jdbc.update("""
                INSERT INTO dianlian_business.enterprise_agent_configuration_version
                    (configuration_version_id, tenant_id, enterprise_agent_id, revision,
                     display_name_snapshot, profile, enterprise_instructions,
                     model_policy_mode, knowledge_scope_mode, visibility_scope, status,
                     create_request_hash, create_idempotency_key, created_by, created_at,
                     create_result_state_version, activation_request_hash, activation_idempotency_key,
                     activated_by, activated_at, activation_result_state_version)
                VALUES
                    (?, ?, ?, 1, '知识冒烟员工', '知识冒烟配置', '仅使用明确授权知识',
                     'PLATFORM_DEFAULT', 'ENTERPRISE_AUTHORIZED', 'TENANT', 'ACTIVE',
                     'request:config-smoke', 'config-smoke', ?, ?, 1,
                     'request:activate-smoke', 'activate-smoke', ?, ?, 1)
                ON CONFLICT DO NOTHING
                """, CONFIGURATION, TENANT, ENTERPRISE_AGENT,
                ENTERPRISE_ACTOR, NOW.atOffset(java.time.ZoneOffset.UTC),
                ENTERPRISE_ACTOR, NOW.atOffset(java.time.ZoneOffset.UTC));
        jdbc.update("""
                UPDATE dianlian_business.enterprise_agent
                   SET display_name = '知识冒烟员工',
                       status = 'ACTIVE',
                       state_version = 1,
                       active_configuration_version_id = ?,
                       activated_by = ?,
                       activated_at = ?,
                       updated_at = ?
                 WHERE enterprise_agent_id = ?
                   AND status = 'DRAFT'
                """, CONFIGURATION, ENTERPRISE_ACTOR,
                NOW.atOffset(java.time.ZoneOffset.UTC),
                NOW.atOffset(java.time.ZoneOffset.UTC),
                ENTERPRISE_AGENT);
    }

    private static PlatformAccessContext platformAccess() {
        return PlatformAccessContext.fromAuthenticatedPrincipal(new AuthenticatedPrincipal(
                UUID.randomUUID(),
                new ActorId(PLATFORM_ACTOR),
                "平台管理员",
                null,
                SessionView.AccountStatus.ACTIVE,
                null,
                List.of(new SessionView.RoleGrant(
                        "PLATFORM_ADMIN",
                        SessionView.DataScopeType.PLATFORM,
                        PLATFORM_ACTOR
                )),
                Set.of(KnowledgePermissions.PLATFORM_READ, KnowledgePermissions.PLATFORM_MANAGE),
                "pv-1",
                NOW,
                NOW.plusSeconds(3600)
        ));
    }

    private static AccessContext enterpriseAccess(String... permissions) {
        return AccessContext.fromAuthenticatedPrincipal(new AuthenticatedPrincipal(
                UUID.randomUUID(),
                new ActorId(ENTERPRISE_ACTOR),
                "企业管理员",
                null,
                SessionView.AccountStatus.ACTIVE,
                new SessionView.Tenant(
                        new TenantId(TENANT),
                        "知识冒烟企业",
                        SessionView.TenantStatus.ACTIVE,
                        SessionView.MembershipStatus.ACTIVE
                ),
                List.of(new SessionView.RoleGrant(
                        "ENTERPRISE_ADMIN",
                        SessionView.DataScopeType.TENANT,
                        TENANT
                )),
                Set.of(permissions),
                "pv-1",
                NOW,
                NOW.plusSeconds(3600)
        ));
    }

    private static <T> T inTransaction(TransactionTemplate transactions, Supplier<T> action) {
        return transactions.execute(status -> action.get());
    }
}

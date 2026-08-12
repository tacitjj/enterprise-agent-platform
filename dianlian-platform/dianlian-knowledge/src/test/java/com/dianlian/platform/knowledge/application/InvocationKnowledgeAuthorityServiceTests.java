package com.dianlian.platform.knowledge.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.knowledge.api.AuthorizedKnowledgeResourceRef;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeAuthorizationQuery;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeEvidenceRef;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeReauthorizationQuery;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeRejectionReason;
import com.dianlian.platform.knowledge.domain.KnowledgeBinding;
import com.dianlian.platform.knowledge.domain.KnowledgeDocumentVersion;
import com.dianlian.platform.knowledge.domain.KnowledgeGrant;
import com.dianlian.platform.knowledge.domain.KnowledgeSpace;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class InvocationKnowledgeAuthorityServiceTests {

    private static final UUID TENANT_ID = uuid(1);
    private static final UUID ACTOR_ID = uuid(2);
    private static final UUID AUDIENCE_ID = uuid(3);
    private static final UUID AGENT_VERSION_ID = uuid(4);
    private static final UUID ENTERPRISE_AGENT_ID = uuid(5);
    private static final UUID CONFIGURATION_VERSION_ID = uuid(6);
    private static final Instant OBSERVED_AT = Instant.parse("2026-08-12T05:00:00Z");

    @Test
    void authorizeUsesTrustedInvocationIdentityWithoutCachingOrInteractivePermission() {
        var repository = new RecordingKnowledgeRepository();
        var later = new AuthorizedKnowledgeResourceRef(TENANT_ID, uuid(20), uuid(21));
        var earlier = new AuthorizedKnowledgeResourceRef(TENANT_ID, uuid(10), uuid(11));
        repository.authorizationResults.add(List.of(later, earlier));
        repository.authorizationResults.add(List.of());
        var service = new InvocationKnowledgeAuthorityService(repository);
        var query = authorizationQuery(List.of(AUDIENCE_ID, ACTOR_ID));

        assertThat(service.authorize(query)).containsExactly(earlier, later);
        assertThat(service.authorize(query)).isEmpty();

        assertThat(repository.authorizationRequests).hasSize(2).allSatisfy(request -> {
            assertThat(request.tenantId()).isEqualTo(TENANT_ID);
            assertThat(request.agentVersionId()).isEqualTo(AGENT_VERSION_ID);
            assertThat(request.enterpriseAgentId()).isEqualTo(ENTERPRISE_AGENT_ID);
            assertThat(request.configurationVersionId()).isEqualTo(CONFIGURATION_VERSION_ID);
            assertThat(request.audienceUserIds()).containsExactly(ACTOR_ID, AUDIENCE_ID);
            assertThat(request.observedAt()).isEqualTo(OBSERVED_AT);
            assertThat(request.limit()).isEqualTo(100);
        });
    }

    @Test
    void reauthorizePartitionsTheCanonicalExactEvidenceSetWithoutReturningContent() {
        var repository = new RecordingKnowledgeRepository();
        InvocationKnowledgeEvidenceRef rejected = new InvocationKnowledgeEvidenceRef(uuid(30), uuid(31));
        InvocationKnowledgeEvidenceRef allowed = new InvocationKnowledgeEvidenceRef(uuid(10), uuid(11));
        var query = reauthorizationQuery(List.of(rejected, allowed));
        repository.reauthorizationResult = List.of(allowed);
        var service = new InvocationKnowledgeAuthorityService(repository);

        var result = service.reauthorize(query);

        assertThat(result.allowed()).containsExactly(new AuthorizedKnowledgeResourceRef(
                TENANT_ID,
                allowed.documentId(),
                allowed.documentVersionId()
        ));
        assertThat(result.rejected()).singleElement().satisfies(rejection -> {
            assertThat(rejection.evidence()).isEqualTo(rejected);
            assertThat(rejection.reason()).isEqualTo(
                    InvocationKnowledgeRejectionReason.CURRENT_AUTHORITY_DENIED
            );
        });
        assertThat(query.actualEvidence()).containsExactly(allowed, rejected);
        assertThat(repository.reauthorizationRequests).containsExactly(query);
    }

    @Test
    void authorityInputsRejectActorOmissionDuplicatesAndUnboundedEvidence() {
        assertThatThrownBy(() -> authorizationQuery(List.of(AUDIENCE_ID)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("actorUserId");

        InvocationKnowledgeEvidenceRef evidence = new InvocationKnowledgeEvidenceRef(uuid(10), uuid(11));
        assertThatThrownBy(() -> reauthorizationQuery(List.of(evidence, evidence)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("duplicates");
        assertThatThrownBy(() -> new InvocationKnowledgeReauthorizationQuery(
                TENANT_ID,
                ACTOR_ID,
                AGENT_VERSION_ID,
                ENTERPRISE_AGENT_ID,
                CONFIGURATION_VERSION_ID,
                List.of(ACTOR_ID),
                OBSERVED_AT,
                1,
                List.of(evidence, new InvocationKnowledgeEvidenceRef(uuid(12), uuid(13)))
        )).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("between 1 and limit");
    }

    @Test
    void repositoryCannotExpandTheRequestedEvidenceSet() {
        var repository = new RecordingKnowledgeRepository();
        var requested = new InvocationKnowledgeEvidenceRef(uuid(10), uuid(11));
        var unexpected = new InvocationKnowledgeEvidenceRef(uuid(12), uuid(13));
        var query = reauthorizationQuery(List.of(requested));
        repository.reauthorizationResult = List.of(unexpected);
        var service = new InvocationKnowledgeAuthorityService(repository);

        assertThatThrownBy(() -> service.reauthorize(query))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("invalid evidence set");
    }

    private static InvocationKnowledgeAuthorizationQuery authorizationQuery(List<UUID> audience) {
        return new InvocationKnowledgeAuthorizationQuery(
                TENANT_ID,
                ACTOR_ID,
                AGENT_VERSION_ID,
                ENTERPRISE_AGENT_ID,
                CONFIGURATION_VERSION_ID,
                audience,
                OBSERVED_AT,
                100
        );
    }

    private static InvocationKnowledgeReauthorizationQuery reauthorizationQuery(
            List<InvocationKnowledgeEvidenceRef> evidence
    ) {
        return new InvocationKnowledgeReauthorizationQuery(
                TENANT_ID,
                ACTOR_ID,
                AGENT_VERSION_ID,
                ENTERPRISE_AGENT_ID,
                CONFIGURATION_VERSION_ID,
                List.of(AUDIENCE_ID, ACTOR_ID),
                OBSERVED_AT,
                100,
                evidence
        );
    }

    private static UUID uuid(long suffix) {
        return UUID.fromString("00000000-0000-4000-8000-%012d".formatted(suffix));
    }

    private static final class RecordingKnowledgeRepository implements KnowledgeRepository {

        private final ArrayDeque<List<AuthorizedKnowledgeResourceRef>> authorizationResults = new ArrayDeque<>();
        private final List<KnowledgeAuthorizationRequest> authorizationRequests = new ArrayList<>();
        private final List<InvocationKnowledgeReauthorizationQuery> reauthorizationRequests = new ArrayList<>();
        private List<InvocationKnowledgeEvidenceRef> reauthorizationResult = List.of();

        @Override
        public Optional<KnowledgeSpace> findSpace(UUID spaceId) {
            throw new AssertionError("unexpected findSpace call");
        }

        @Override
        public Optional<KnowledgeGrant> findGrant(UUID grantId) {
            throw new AssertionError("unexpected findGrant call");
        }

        @Override
        public KnowledgeWriteResult<KnowledgeSpace> createSpace(KnowledgeWrites.CreateSpace write) {
            throw new AssertionError("unexpected createSpace call");
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
            throw new AssertionError("unexpected completeDocumentNormalization call");
        }

        @Override
        public KnowledgeWriteResult<KnowledgeGrant> grantAudience(KnowledgeWrites.GrantAudience write) {
            throw new AssertionError("unexpected grantAudience call");
        }

        @Override
        public KnowledgeWriteResult<KnowledgeGrant> revokeAudience(KnowledgeWrites.RevokeAudience write) {
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
            return authorizationResults.removeFirst();
        }

        @Override
        public List<InvocationKnowledgeEvidenceRef> reauthorizeExactEvidence(
                InvocationKnowledgeReauthorizationQuery query
        ) {
            reauthorizationRequests.add(query);
            return reauthorizationResult;
        }
    }
}

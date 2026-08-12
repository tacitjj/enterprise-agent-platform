package com.dianlian.platform.integration.infrastructure.context;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScopeType;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource;
import com.dianlian.platform.context.api.ContextAuthorityPort.AuthorizationRequest;
import com.dianlian.platform.context.api.ContextAuthorityPort.EvidenceIdentity;
import com.dianlian.platform.context.api.ContextAuthorityPort.InvocationBoundary;
import com.dianlian.platform.context.api.ContextAuthorityPort.ReauthorizationRequest;
import com.dianlian.platform.knowledge.api.AuthorizedKnowledgeResourceRef;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeAuthorizationQuery;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeAuthoritySource;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeEvidenceRef;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeReauthorizationQuery;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeReauthorizationResult;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeRejectionReason;
import com.dianlian.platform.knowledge.api.RejectedInvocationKnowledgeEvidence;
import com.dianlian.platform.memory.api.InvocationMemoryAuthoritySource;
import com.dianlian.platform.memory.api.MemoryScopeRef;
import com.dianlian.platform.memory.api.MemoryScopeType;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class AuthoritativeContextAuthorityAdapterTests {

    private static final UUID TENANT_ID = uuid(1);
    private static final UUID ACTOR_ID = uuid(2);
    private static final UUID SECOND_AUDIENCE_ID = uuid(3);
    private static final UUID ENTERPRISE_AGENT_ID = uuid(4);
    private static final UUID AGENT_VERSION_ID = uuid(5);
    private static final UUID CONFIGURATION_VERSION_ID = uuid(6);
    private static final UUID CONVERSATION_ID = uuid(7);
    private static final Instant OBSERVED_AT = Instant.parse("2026-08-12T06:00:00Z");

    @Test
    void mapsKnowledgeAndDirectMemoryAuthorityWithoutInteractiveAccessContext() {
        var knowledge = new RecordingKnowledgeAuthority();
        var memory = new RecordingMemoryAuthority();
        var documentId = uuid(20);
        var documentVersionId = uuid(21);
        knowledge.authorization = List.of(new AuthorizedKnowledgeResourceRef(
                TENANT_ID,
                documentId,
                documentVersionId
        ));
        memory.authorization = InvocationMemoryAuthoritySource.AuthorizeScopesResult.allowed(List.of(
                authorizedScope(MemoryScopeType.AGENT, ENTERPRISE_AGENT_ID, 0),
                authorizedScope(MemoryScopeType.USER_AGENT, ACTOR_ID, 0)
        ));
        var adapter = new AuthoritativeContextAuthorityAdapter(knowledge, memory);

        var result = adapter.authorize(new AuthorizationRequest(directInvocation(), true, true, 37));

        assertThat(result.accepted()).isTrue();
        assertThat(result.rejectionCode()).isNull();
        assertThat(result.knowledgeResources()).singleElement().satisfies(resource -> {
            assertThat(resource.tenantId()).isEqualTo(TENANT_ID);
            assertThat(resource.resourceId()).isEqualTo(documentId);
            assertThat(resource.resourceVersionId()).isEqualTo(documentVersionId);
        });
        assertThat(result.memoryScopes())
                .extracting(scope -> scope.scopeType())
                .containsExactly(AllowedMemoryScopeType.AGENT, AllowedMemoryScopeType.USER_AGENT);

        assertThat(knowledge.authorizationQueries).singleElement().satisfies(query -> {
            assertThat(query.tenantId()).isEqualTo(TENANT_ID);
            assertThat(query.actorUserId()).isEqualTo(ACTOR_ID);
            assertThat(query.agentVersionId()).isEqualTo(AGENT_VERSION_ID);
            assertThat(query.enterpriseAgentId()).isEqualTo(ENTERPRISE_AGENT_ID);
            assertThat(query.configurationVersionId()).isEqualTo(CONFIGURATION_VERSION_ID);
            assertThat(query.audienceUserIds()).containsExactly(ACTOR_ID, SECOND_AUDIENCE_ID);
            assertThat(query.observedAt()).isEqualTo(OBSERVED_AT);
            assertThat(query.limit()).isEqualTo(37);
        });
        assertThat(memory.authorizationQueries).singleElement().satisfies(query -> {
            assertThat(query.tenantId()).isEqualTo(TENANT_ID);
            assertThat(query.actorUserId()).isEqualTo(ACTOR_ID);
            assertThat(query.enterpriseAgentId()).isEqualTo(ENTERPRISE_AGENT_ID);
            assertThat(query.conversationId()).isEqualTo(CONVERSATION_ID);
            assertThat(query.groupConversation()).isFalse();
            assertThat(query.audienceUserIds()).containsExactly(ACTOR_ID, SECOND_AUDIENCE_ID);
            assertThat(query.historyFloorSequenceNo()).isZero();
            assertThat(query.observedAt()).isEqualTo(OBSERVED_AT);
        });
    }

    @Test
    void groupAuthorizationExposesGroupScopeButNeverPrivateUserScope() {
        var knowledge = new RecordingKnowledgeAuthority();
        var memory = new RecordingMemoryAuthority();
        memory.authorization = InvocationMemoryAuthoritySource.AuthorizeScopesResult.allowed(List.of(
                authorizedScope(MemoryScopeType.AGENT, ENTERPRISE_AGENT_ID, 0),
                authorizedScope(MemoryScopeType.GROUP_AGENT, CONVERSATION_ID, 11)
        ));
        var adapter = new AuthoritativeContextAuthorityAdapter(knowledge, memory);

        var result = adapter.authorize(new AuthorizationRequest(groupInvocation(), false, true, 10));

        assertThat(result.accepted()).isTrue();
        assertThat(result.memoryScopes())
                .extracting(scope -> scope.scopeType())
                .containsExactly(AllowedMemoryScopeType.AGENT, AllowedMemoryScopeType.GROUP_AGENT)
                .doesNotContain(AllowedMemoryScopeType.USER_AGENT);
        assertThat(result.memoryScopes().getLast().historyFloorSequenceNo()).isEqualTo(11);
        assertThat(knowledge.authorizationQueries).isEmpty();
    }

    @Test
    void invalidDirectOrGroupScopeCombinationFailsClosed() {
        var knowledge = new RecordingKnowledgeAuthority();
        var memory = new RecordingMemoryAuthority();
        var adapter = new AuthoritativeContextAuthorityAdapter(knowledge, memory);

        memory.authorization = InvocationMemoryAuthoritySource.AuthorizeScopesResult.allowed(List.of(
                authorizedScope(MemoryScopeType.AGENT, ENTERPRISE_AGENT_ID, 0),
                authorizedScope(MemoryScopeType.USER_AGENT, ACTOR_ID, 0)
        ));
        assertThatThrownBy(() -> adapter.authorize(new AuthorizationRequest(
                groupInvocation(), false, true, 10
        ))).isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("group invocation");

        memory.authorization = InvocationMemoryAuthoritySource.AuthorizeScopesResult.allowed(List.of(
                authorizedScope(MemoryScopeType.AGENT, ENTERPRISE_AGENT_ID, 0),
                authorizedScope(MemoryScopeType.GROUP_AGENT, CONVERSATION_ID, 11)
        ));
        assertThatThrownBy(() -> adapter.authorize(new AuthorizationRequest(
                directInvocation(), false, true, 10
        ))).isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("direct invocation");
    }

    @Test
    void filtersKnowledgeEvidenceWhoseCurrentAuthorityWasRevoked() {
        var knowledge = new RecordingKnowledgeAuthority();
        var memory = new RecordingMemoryAuthority();
        var allowed = knowledgeEvidence("knowledge-allowed", uuid(30), uuid(31));
        var revoked = knowledgeEvidence("knowledge-revoked", uuid(32), uuid(33));
        knowledge.reauthorization = new InvocationKnowledgeReauthorizationResult(
                List.of(new AuthorizedKnowledgeResourceRef(
                        TENANT_ID,
                        allowed.sourceId(),
                        UUID.fromString(allowed.sourceVersion())
                )),
                List.of(new RejectedInvocationKnowledgeEvidence(
                        new InvocationKnowledgeEvidenceRef(
                                revoked.sourceId(),
                                UUID.fromString(revoked.sourceVersion())
                        ),
                        InvocationKnowledgeRejectionReason.CURRENT_AUTHORITY_DENIED
                ))
        );
        var adapter = new AuthoritativeContextAuthorityAdapter(knowledge, memory);

        var result = adapter.reauthorize(new ReauthorizationRequest(
                directInvocation(),
                List.of(revoked, allowed)
        ));

        assertThat(result.contractAccepted()).isTrue();
        assertThat(result.allowedEvidence()).containsExactly(allowed);
        assertThat(result.rejectedEvidence()).singleElement().satisfies(rejection -> {
            assertThat(rejection.evidenceId()).isEqualTo(revoked.evidenceId());
            assertThat(rejection.reasonCode()).isEqualTo("CURRENT_AUTHORITY_DENIED");
        });
        assertThat(knowledge.reauthorizationQueries).singleElement().satisfies(query -> {
            assertThat(query.tenantId()).isEqualTo(TENANT_ID);
            assertThat(query.actorUserId()).isEqualTo(ACTOR_ID);
            assertThat(query.actualEvidence()).containsExactly(
                    new InvocationKnowledgeEvidenceRef(
                            allowed.sourceId(),
                            UUID.fromString(allowed.sourceVersion())
                    ),
                    new InvocationKnowledgeEvidenceRef(
                            revoked.sourceId(),
                            UUID.fromString(revoked.sourceVersion())
                    )
            );
        });
        assertThat(memory.reauthorizationQueries).isEmpty();
    }

    @Test
    void memoryContractViolationRejectsTheWholeMixedEvidenceContract() {
        var knowledge = new RecordingKnowledgeAuthority();
        var memory = new RecordingMemoryAuthority();
        var knowledgeItem = knowledgeEvidence("knowledge-allowed", uuid(40), uuid(41));
        var memoryItem = memoryEvidence("memory-private", uuid(42), 1);
        knowledge.reauthorization = new InvocationKnowledgeReauthorizationResult(
                List.of(new AuthorizedKnowledgeResourceRef(
                        TENANT_ID,
                        knowledgeItem.sourceId(),
                        UUID.fromString(knowledgeItem.sourceVersion())
                )),
                List.of()
        );
        memory.reauthorization = new InvocationMemoryAuthoritySource.ReauthorizationResult(
                false,
                InvocationMemoryAuthoritySource.RejectionCode.GROUP_PRIVATE_SCOPE_CONTRACT_VIOLATION,
                List.of(),
                List.of()
        );
        var adapter = new AuthoritativeContextAuthorityAdapter(knowledge, memory);

        var result = adapter.reauthorize(new ReauthorizationRequest(
                groupInvocation(),
                List.of(knowledgeItem, memoryItem)
        ));

        assertThat(result.contractAccepted()).isFalse();
        assertThat(result.rejectionCode()).isEqualTo("GROUP_PRIVATE_SCOPE_CONTRACT_VIOLATION");
        assertThat(result.allowedEvidence()).isEmpty();
        assertThat(result.rejectedEvidence()).isEmpty();
        assertThat(knowledge.reauthorizationQueries).hasSize(1);
        assertThat(memory.reauthorizationQueries).hasSize(1);
    }

    @Test
    void invalidKnowledgeUuidOrMemoryVersionFailsClosedBeforeAuthorityCall() {
        var knowledge = new RecordingKnowledgeAuthority();
        var memory = new RecordingMemoryAuthority();
        var adapter = new AuthoritativeContextAuthorityAdapter(knowledge, memory);
        var invalidKnowledge = evidence(
                "invalid-knowledge",
                RequestedSource.KNOWLEDGE,
                uuid(50),
                "not-a-uuid"
        );

        assertThatThrownBy(() -> adapter.reauthorize(new ReauthorizationRequest(
                directInvocation(),
                List.of(invalidKnowledge)
        ))).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("knowledge sourceVersion");
        assertThat(knowledge.reauthorizationQueries).isEmpty();
        assertThat(memory.reauthorizationQueries).isEmpty();

        var invalidMemory = evidence(
                "invalid-memory",
                RequestedSource.MEMORY,
                uuid(51),
                "not-an-integer"
        );
        assertThatThrownBy(() -> adapter.reauthorize(new ReauthorizationRequest(
                directInvocation(),
                List.of(invalidMemory)
        ))).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("memory sourceVersion");
        assertThat(knowledge.reauthorizationQueries).isEmpty();
        assertThat(memory.reauthorizationQueries).isEmpty();
    }

    @Test
    void mergesMixedEvidenceInStableRequestAndRejectionOrder() {
        var knowledge = new RecordingKnowledgeAuthority();
        var memory = new RecordingMemoryAuthority();
        var memoryAllowed = memoryEvidence("memory-allowed", uuid(60), 2);
        var knowledgeRejected = knowledgeEvidence("z-knowledge-rejected", uuid(61), uuid(62));
        var knowledgeAllowed = knowledgeEvidence("knowledge-allowed", uuid(63), uuid(64));
        var memoryRejected = memoryEvidence("a-memory-rejected", uuid(65), 3);
        var requestEvidence = List.of(
                memoryAllowed,
                knowledgeRejected,
                knowledgeAllowed,
                memoryRejected
        );
        knowledge.reauthorization = new InvocationKnowledgeReauthorizationResult(
                List.of(new AuthorizedKnowledgeResourceRef(
                        TENANT_ID,
                        knowledgeAllowed.sourceId(),
                        UUID.fromString(knowledgeAllowed.sourceVersion())
                )),
                List.of(new RejectedInvocationKnowledgeEvidence(
                        new InvocationKnowledgeEvidenceRef(
                                knowledgeRejected.sourceId(),
                                UUID.fromString(knowledgeRejected.sourceVersion())
                        ),
                        InvocationKnowledgeRejectionReason.CURRENT_AUTHORITY_DENIED
                ))
        );
        var agentScope = new MemoryScopeRef(MemoryScopeType.AGENT, ENTERPRISE_AGENT_ID);
        memory.reauthorization = new InvocationMemoryAuthoritySource.ReauthorizationResult(
                true,
                null,
                List.of(new InvocationMemoryAuthoritySource.AuthorizedMemoryEvidence(
                        new InvocationMemoryAuthoritySource.MemoryEvidenceKey(memoryAllowed.sourceId(), 2),
                        agentScope
                )),
                List.of(new InvocationMemoryAuthoritySource.RejectedMemoryEvidence(
                        new InvocationMemoryAuthoritySource.MemoryEvidenceKey(memoryRejected.sourceId(), 3),
                        InvocationMemoryAuthoritySource.RejectionCode.MEMORY_NOT_ACTIVE
                ))
        );
        var adapter = new AuthoritativeContextAuthorityAdapter(knowledge, memory);
        var request = new ReauthorizationRequest(directInvocation(), requestEvidence);

        var first = adapter.reauthorize(request);
        var replay = adapter.reauthorize(request);

        assertThat(first).isEqualTo(replay);
        assertThat(first.allowedEvidence()).containsExactly(memoryAllowed, knowledgeAllowed);
        assertThat(first.rejectedEvidence())
                .extracting(rejection -> rejection.evidenceId())
                .containsExactly("a-memory-rejected", "z-knowledge-rejected");
        assertThat(first.rejectedEvidence())
                .extracting(rejection -> rejection.reasonCode())
                .containsExactly("MEMORY_NOT_ACTIVE", "CURRENT_AUTHORITY_DENIED");
        assertThat(knowledge.reauthorizationQueries).hasSize(2);
        assertThat(memory.reauthorizationQueries).hasSize(2);
    }

    private static InvocationBoundary directInvocation() {
        return invocation(false, 0);
    }

    private static InvocationBoundary groupInvocation() {
        return invocation(true, 11);
    }

    private static InvocationBoundary invocation(boolean groupConversation, long historyFloorSequenceNo) {
        return new InvocationBoundary(
                TENANT_ID,
                ACTOR_ID,
                ENTERPRISE_AGENT_ID,
                AGENT_VERSION_ID,
                CONFIGURATION_VERSION_ID,
                CONVERSATION_ID,
                groupConversation,
                uuid(8),
                12,
                3,
                "conversation-v1",
                List.of(SECOND_AUDIENCE_ID, ACTOR_ID),
                historyFloorSequenceNo,
                OBSERVED_AT
        );
    }

    private static InvocationMemoryAuthoritySource.AuthorizedMemoryScope authorizedScope(
            MemoryScopeType scopeType,
            UUID scopeId,
            long historyFloorSequenceNo
    ) {
        return new InvocationMemoryAuthoritySource.AuthorizedMemoryScope(
                TENANT_ID,
                scopeType,
                scopeId,
                ENTERPRISE_AGENT_ID,
                historyFloorSequenceNo
        );
    }

    private static EvidenceIdentity knowledgeEvidence(String evidenceId, UUID documentId, UUID versionId) {
        return evidence(evidenceId, RequestedSource.KNOWLEDGE, documentId, versionId.toString());
    }

    private static EvidenceIdentity memoryEvidence(String evidenceId, UUID memoryId, long version) {
        return evidence(evidenceId, RequestedSource.MEMORY, memoryId, Long.toString(version));
    }

    private static EvidenceIdentity evidence(
            String evidenceId,
            RequestedSource source,
            UUID sourceId,
            String sourceVersion
    ) {
        return new EvidenceIdentity(
                evidenceId,
                source,
                sourceId,
                sourceVersion,
                "chunk-" + evidenceId,
                "a".repeat(64),
                "测试引用"
        );
    }

    private static UUID uuid(long suffix) {
        return UUID.fromString("00000000-0000-4000-8000-%012d".formatted(suffix));
    }

    private static final class RecordingKnowledgeAuthority implements InvocationKnowledgeAuthoritySource {

        private final List<InvocationKnowledgeAuthorizationQuery> authorizationQueries = new ArrayList<>();
        private final List<InvocationKnowledgeReauthorizationQuery> reauthorizationQueries = new ArrayList<>();
        private List<AuthorizedKnowledgeResourceRef> authorization = List.of();
        private InvocationKnowledgeReauthorizationResult reauthorization =
                new InvocationKnowledgeReauthorizationResult(List.of(), List.of());

        @Override
        public List<AuthorizedKnowledgeResourceRef> authorize(InvocationKnowledgeAuthorizationQuery query) {
            authorizationQueries.add(query);
            return authorization;
        }

        @Override
        public InvocationKnowledgeReauthorizationResult reauthorize(
                InvocationKnowledgeReauthorizationQuery query
        ) {
            reauthorizationQueries.add(query);
            return reauthorization;
        }
    }

    private static final class RecordingMemoryAuthority implements InvocationMemoryAuthoritySource {

        private final List<AuthorizeScopesQuery> authorizationQueries = new ArrayList<>();
        private final List<ReauthorizeQuery> reauthorizationQueries = new ArrayList<>();
        private AuthorizeScopesResult authorization = AuthorizeScopesResult.allowed(List.of(
                authorizedScope(MemoryScopeType.AGENT, ENTERPRISE_AGENT_ID, 0)
        ));
        private ReauthorizationResult reauthorization = new ReauthorizationResult(
                true,
                null,
                List.of(),
                List.of()
        );

        @Override
        public AuthorizeScopesResult authorizeScopes(AuthorizeScopesQuery query) {
            authorizationQueries.add(query);
            return authorization;
        }

        @Override
        public ReauthorizationResult reauthorize(ReauthorizeQuery query) {
            reauthorizationQueries.add(query);
            return reauthorization;
        }
    }
}

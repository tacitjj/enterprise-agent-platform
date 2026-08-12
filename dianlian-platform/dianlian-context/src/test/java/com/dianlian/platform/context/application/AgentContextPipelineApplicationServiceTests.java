package com.dianlian.platform.context.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.context.api.AgentContextRequest;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScope;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScopeType;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AuthorizedKnowledgeResource;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextBundle;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextEvidence;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextSourceBundle;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextSourceState;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RetrievalTrace;
import com.dianlian.platform.context.api.ContextAuthorityPort;
import com.dianlian.platform.context.api.ContextAuthorityViolationException;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class AgentContextPipelineApplicationServiceTests {

    private static final Instant NOW = Instant.parse("2026-08-12T10:00:00Z");
    private static final UUID TENANT = uuid(1);
    private static final UUID USER = uuid(11);
    private static final UUID AGENT = uuid(121);
    private static final UUID CONVERSATION = uuid(201);
    private static final UUID DOCUMENT = uuid(301);
    private static final UUID DOCUMENT_VERSION = uuid(302);
    private static final UUID MEMORY = uuid(401);

    @Test
    void directFlowUsesOnlyAgentAndUserMemoryAndProducesStableAuthorizationHash() {
        var authority = new RecordingAuthority(false, false);
        var service = new AgentContextPipelineApplicationService(
                authority, List.of(request -> bundle(request.requestId())));

        var first = service.authorize(request(false, true), NOW);
        var replay = service.authorize(request(false, true), NOW.plusSeconds(5));

        assertThat(first.authority().memoryScopes()).extracting(AllowedMemoryScope::scopeType)
                .containsExactly(AllowedMemoryScopeType.AGENT, AllowedMemoryScopeType.USER_AGENT);
        assertThat(first.authorizationSnapshotHash()).isEqualTo(replay.authorizationSnapshotHash());

        var draft = service.retrieve(first, uuid(501), uuid(502), NOW.plusSeconds(10));
        var fenced = service.fenceAndAssemble(draft, NOW.plusSeconds(2));
        assertThat(fenced.context().ready()).isTrue();
        assertThat(fenced.context().systemInstruction()).contains("企业知识", "已确认记忆");
        assertThat(fenced.evidence()).hasSize(2);
    }

    @Test
    void groupPrivateMemoryIsAContractViolation() {
        var service = new AgentContextPipelineApplicationService(
                new RecordingAuthority(true, false), List.of(request -> bundle(request.requestId())));

        assertThatThrownBy(() -> service.authorize(request(true, true), NOW))
                .isInstanceOf(ContextAuthorityViolationException.class)
                .hasMessageContaining("GROUP_PRIVATE_SCOPE_CONTRACT_VIOLATION");
    }

    @Test
    void requiredKnowledgeRevokedBeforeModelCreatesBlocker() {
        var service = new AgentContextPipelineApplicationService(
                new RecordingAuthority(false, true), List.of(request -> bundle(request.requestId())));
        var plan = service.authorize(request(false, true), NOW);
        var draft = service.retrieve(plan, uuid(501), uuid(502), NOW.plusSeconds(10));

        var fenced = service.fenceAndAssemble(draft, NOW.plusSeconds(2));

        assertThat(fenced.context().ready()).isFalse();
        assertThat(fenced.context().blockers()).containsExactly("REQUIRED_KNOWLEDGE_REVOKED_BEFORE_MODEL");
        assertThat(fenced.context().knowledge().evidence()).isEmpty();
    }

    private static AgentContextRequest request(boolean group, boolean required) {
        return new AgentContextRequest(
                TENANT, USER, AGENT, CONVERSATION, group, uuid(211), uuid(212), "合同审核",
                "平台岗位", "企业红线", "审核合同", uuid(213), 10, 3, "conversation-v1", 2,
                List.of(USER), List.of(), true, required, false);
    }

    private static ContextBundle bundle(UUID requestId) {
        return new ContextBundle(
                AuthorizedContextRetrievalContract.B0_CONTRACT_VERSION, requestId, "snapshot-1", NOW,
                new ContextSourceBundle(ContextSourceState.READY, null, List.of(knowledgeEvidence())),
                new ContextSourceBundle(ContextSourceState.READY, null, List.of(memoryEvidence())),
                new RetrievalTrace(List.of("LEXICAL"), 2, 2, "context-default-v1", 10));
    }

    private static ContextEvidence knowledgeEvidence() {
        return new ContextEvidence("k1", RequestedSource.KNOWLEDGE, DOCUMENT, DOCUMENT_VERSION.toString(),
                "chunk-k", "合同制度", "知识片段", hash('a'), 0.9, "制度第1条");
    }

    private static ContextEvidence memoryEvidence() {
        return new ContextEvidence("m1", RequestedSource.MEMORY, MEMORY, "1", "chunk-m",
                "已确认记忆", "用户习惯", hash('b'), 0.8, "记忆 #1");
    }

    private static String hash(char value) {
        return String.valueOf(value).repeat(64);
    }

    private static UUID uuid(long suffix) {
        return UUID.fromString("00000000-0000-0000-0000-" + String.format("%012d", suffix));
    }

    private static final class RecordingAuthority implements ContextAuthorityPort {
        private final boolean leakPrivateToGroup;
        private final boolean revokeKnowledge;

        private RecordingAuthority(boolean leakPrivateToGroup, boolean revokeKnowledge) {
            this.leakPrivateToGroup = leakPrivateToGroup;
            this.revokeKnowledge = revokeKnowledge;
        }

        @Override
        public Authorization authorize(AuthorizationRequest request) {
            var invocation = request.invocation();
            var secondType = invocation.groupConversation() && !leakPrivateToGroup
                    ? AllowedMemoryScopeType.GROUP_AGENT : AllowedMemoryScopeType.USER_AGENT;
            var secondId = secondType == AllowedMemoryScopeType.GROUP_AGENT
                    ? invocation.conversationId() : invocation.actorUserId();
            return new Authorization(true, null,
                    List.of(new AuthorizedKnowledgeResource(TENANT, DOCUMENT, DOCUMENT_VERSION)),
                    List.of(
                            new AllowedMemoryScope(TENANT, AllowedMemoryScopeType.AGENT, AGENT, AGENT, 0),
                            new AllowedMemoryScope(TENANT, secondType, secondId, AGENT,
                                    secondType == AllowedMemoryScopeType.GROUP_AGENT ? 2 : 0)));
        }

        @Override
        public Reauthorization reauthorize(ReauthorizationRequest request) {
            var allowed = request.actualEvidence().stream()
                    .filter(item -> !(revokeKnowledge && item.sourceType() == RequestedSource.KNOWLEDGE))
                    .toList();
            var rejected = request.actualEvidence().stream()
                    .filter(item -> revokeKnowledge && item.sourceType() == RequestedSource.KNOWLEDGE)
                    .map(item -> new EvidenceRejection(item.evidenceId(), "CURRENT_AUTHORITY_DENIED"))
                    .toList();
            return new Reauthorization(true, null, allowed, rejected);
        }
    }
}

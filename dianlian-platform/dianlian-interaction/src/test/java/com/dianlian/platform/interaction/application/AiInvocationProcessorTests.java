package com.dianlian.platform.interaction.application;

import static org.assertj.core.api.Assertions.assertThat;

import com.dianlian.platform.billing.api.PointSettlementResult;
import com.dianlian.platform.billing.api.PointSettlementService;
import com.dianlian.platform.billing.api.SettlePointsCommand;
import com.dianlian.platform.context.api.AgentContextBundle;
import com.dianlian.platform.context.api.AgentContextPipeline;
import com.dianlian.platform.context.api.AgentContextRequest;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextSourceState;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RetrievalTrace;
import com.dianlian.platform.context.api.ContextAuthorizationPlan;
import com.dianlian.platform.context.api.ContextAuthorityPort;
import com.dianlian.platform.context.api.ContextMessage;
import com.dianlian.platform.context.api.ContextSourceResult;
import com.dianlian.platform.context.api.FencedAgentContext;
import com.dianlian.platform.context.api.RetrievedContextDraft;
import com.dianlian.platform.model.api.*;
import java.math.BigDecimal;
import java.time.*;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.*;
import org.springframework.transaction.support.*;

class AiInvocationProcessorTests {

    private static final Instant NOW = Instant.parse("2026-08-11T09:00:00Z");
    private static final UUID TENANT_ID = uuid(1), ACTOR_ID = uuid(11), AGENT_ID = uuid(121);
    private static final UUID CONVERSATION_ID = uuid(201), INVOCATION_ID = uuid(301);
    private static final UUID AGENT_VERSION_ID = uuid(401), CONFIGURATION_VERSION_ID = uuid(402);
    private static final UUID ROUTE_ID = uuid(501), MODEL_ID = uuid(502), RESERVATION_ID = uuid(601);

    @Test
    void confirmedUsagePublishesOnlyAfterThreeAccessFencesAndIncludesFrozenHistory() {
        var repository = new RecordingRepository(claimed(), true);
        var pipeline = new RecordingPipeline(true);
        var gateway = new RecordingGateway(response(true));
        var settlement = new RecordingSettlement();

        assertThat(processor(repository, pipeline, gateway, settlement).processNext("worker-1")).isTrue();

        assertThat(repository.published).isTrue();
        assertThat(repository.preModelFenceCount).isEqualTo(2);
        assertThat(repository.publishFenceChecked).isTrue();
        assertThat(pipeline.reauthorizeCount).isEqualTo(1);
        assertThat(settlement.lastCommand.capturedAmount()).isEqualTo(3_000);
        assertThat(pipeline.lastRequest.historyFloorSequenceNo()).isEqualTo(7);
        assertThat(gateway.lastRequest.messages()).extracting(ModelChatMessage::text)
                .containsExactly("[发言人：张三] 历史问题", "[发言人：合同审核员工] 历史回答", "请审核当前合同");
    }

    @Test
    void evidenceRevokedAfterProviderDoesNotPublishAndChargesEnterpriseZero() {
        var repository = new RecordingRepository(claimed(), true);
        var settlement = new RecordingSettlement();

        assertThat(processor(repository, new RecordingPipeline(false), new RecordingGateway(response(true)), settlement)
                .processNext("worker-1")).isTrue();

        assertThat(repository.accessBlocked).isTrue();
        assertThat(repository.lastAccessError).isEqualTo("EVIDENCE_REVOKED_AFTER_PROVIDER");
        assertThat(repository.published).isFalse();
        assertThat(settlement.lastCommand.capturedAmount()).isZero();
    }

    @Test
    void missingProviderUsageStaysPendingWithoutFreeSettlement() {
        var repository = new RecordingRepository(claimed(), true);
        var settlement = new RecordingSettlement();

        assertThat(processor(repository, new RecordingPipeline(true), new RecordingGateway(response(false)), settlement)
                .processNext("worker-1")).isTrue();

        assertThat(repository.lastRecorded.status()).isEqualTo("USAGE_PENDING");
        assertThat(repository.published).isFalse();
        assertThat(settlement.lastCommand).isNull();
    }

    private static AiInvocationProcessor processor(
            RecordingRepository repository,
            AgentContextPipeline pipeline,
            ModelGateway gateway,
            PointSettlementService settlement
    ) {
        return new AiInvocationProcessor(repository, pipeline, routeQuery(), gateway, settlement,
                transactionTemplate(), Clock.fixed(NOW, ZoneOffset.UTC));
    }

    private static AiInvocationRepository.ClaimedInvocation claimed() {
        return new AiInvocationRepository.ClaimedInvocation(
                INVOCATION_ID, TENANT_ID, CONVERSATION_ID, true, uuid(302), 12, 3,
                "conversation-v1", 7, "请审核当前合同", ACTOR_ID, AGENT_ID,
                AGENT_VERSION_ID, CONFIGURATION_VERSION_ID, "法务合同审核", "平台岗位规范",
                "企业合同红线", "NONE", ROUTE_ID, MODEL_ID, RESERVATION_ID, List.of(ACTOR_ID),
                true, "RUNNING", 1, 1, "worker-1", null, 0, 0, false, null);
    }

    private static ModelChatResponse response(boolean usageConfirmed) {
        return new ModelChatResponse("审核结论", usageConfirmed ? 1_000 : 0, usageConfirmed ? 2_000 : 0,
                usageConfirmed, "provider-request", "STOP");
    }

    private static ContextAuthorityPort.InvocationBoundary boundary() {
        return new ContextAuthorityPort.InvocationBoundary(
                TENANT_ID, ACTOR_ID, AGENT_ID, AGENT_VERSION_ID, CONFIGURATION_VERSION_ID,
                CONVERSATION_ID, true, uuid(302), 12, 3, "conversation-v1", List.of(ACTOR_ID), 7, NOW);
    }

    private static ContextAuthorityPort.EvidenceIdentity evidence() {
        return new ContextAuthorityPort.EvidenceIdentity(
                "memory-1", com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource.MEMORY,
                uuid(801), "1", "chunk-1", "a".repeat(64), "记忆 #1");
    }

    private static FencedAgentContext fenced(AgentContextRequest request) {
        var context = new AgentContextBundle(
                AGENT_VERSION_ID, CONFIGURATION_VERSION_ID, "系统指令", request.recentMessages(),
                ContextSourceResult.empty("NO_KNOWLEDGE"), ContextSourceResult.empty("NO_MEMORY"),
                List.of(), List.of());
        return new FencedAgentContext(context, "b".repeat(64), uuid(901), "snapshot-1",
                new RetrievalTrace(List.of("LEXICAL"), 1, 1, "context-default-v1", 1),
                List.of(evidence()), "NO_KNOWLEDGE", "NO_MEMORY", NOW);
    }

    private static ModelRouteQuery routeQuery() {
        return new ModelRouteQuery() {
            public ResolvedModelRoute resolve(UUID t, UUID a, ModelCapabilityType c, ModelRoutePreference p) { return route(); }
            public ResolvedModelRoute requireSnapshot(UUID routeBindingId, UUID modelDefinitionId) { return route(); }
        };
    }

    private static ResolvedModelRoute route() {
        return new ResolvedModelRoute(ROUTE_ID, 1, "PLATFORM", new ModelDefinitionView(
                MODEL_ID, "DASHSCOPE_TEST", 1, "测试模型", "ALIBABA_DASHSCOPE", "OPENAI_COMPATIBLE",
                "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-test",
                "env:DIANLIAN_MODEL_TEST_KEY", ModelCapabilityType.TEXT_CHAT, BigDecimal.ZERO, 4_096,
                1_000_000, 1_000_000, 500_000, ModelDefinitionStatus.ACTIVE, ACTOR_ID, NOW));
    }

    private static TransactionTemplate transactionTemplate() {
        return new TransactionTemplate(new PlatformTransactionManager() {
            public TransactionStatus getTransaction(TransactionDefinition definition) { return new SimpleTransactionStatus(); }
            public void commit(TransactionStatus status) { }
            public void rollback(TransactionStatus status) { }
        });
    }

    private static UUID uuid(long suffix) {
        return UUID.fromString("00000000-0000-0000-0000-" + String.format("%012d", suffix));
    }

    private static final class RecordingPipeline implements AgentContextPipeline {
        private final boolean finalEvidenceAllowed;
        private AgentContextRequest lastRequest;
        private int reauthorizeCount;

        private RecordingPipeline(boolean finalEvidenceAllowed) { this.finalEvidenceAllowed = finalEvidenceAllowed; }

        public ContextAuthorizationPlan authorize(AgentContextRequest request, Instant observedAt) {
            lastRequest = request;
            var authority = new ContextAuthorityPort.Authorization(true, null, List.of(), List.of());
            return new ContextAuthorizationPlan(request, boundary(), authority,
                    List.of(com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource.MEMORY),
                    new com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RetrievalPolicy(1,1,1,1,128),
                    "b".repeat(64));
        }
        public RetrievedContextDraft retrieve(ContextAuthorizationPlan plan, UUID requestId, UUID traceId, Instant deadlineAt) {
            return new RetrievedContextDraft(plan, new com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextRetrievalRequest(
                    "1.0", requestId, traceId, deadlineAt, TENANT_ID, ACTOR_ID, AGENT_ID, CONVERSATION_ID,
                    "审核", List.of(ACTOR_ID), List.of(), List.of(new com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScope(
                    TENANT_ID, com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScopeType.AGENT,
                    AGENT_ID, AGENT_ID, 0)), List.of(com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource.MEMORY),
                    plan.retrievalPolicy(), plan.authorizationSnapshotHash()), emptyBundle(requestId));
        }
        public FencedAgentContext fenceAndAssemble(RetrievedContextDraft draft, Instant observedAt) { return fenced(lastRequest); }
        public ContextAuthorityPort.Reauthorization reauthorize(ContextAuthorityPort.InvocationBoundary i,
                List<ContextAuthorityPort.EvidenceIdentity> e, Instant observedAt) {
            reauthorizeCount++;
            return finalEvidenceAllowed
                    ? new ContextAuthorityPort.Reauthorization(true, null, e, List.of())
                    : new ContextAuthorityPort.Reauthorization(true, null, List.of(),
                            List.of(new ContextAuthorityPort.EvidenceRejection("memory-1", "MEMORY_NOT_ACTIVE")));
        }
        private com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextBundle emptyBundle(UUID requestId) {
            var empty = new com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextSourceBundle(
                    ContextSourceState.EMPTY, "EMPTY", List.of());
            return new com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextBundle(
                    "1.0", requestId, "snapshot", NOW, empty, empty,
                    new RetrievalTrace(List.of("LEXICAL"), 0, 0, "context-default-v1", 1));
        }
    }

    private static final class RecordingGateway implements ModelGateway {
        private final ModelChatResponse response; private ModelChatRequest lastRequest;
        private RecordingGateway(ModelChatResponse response) { this.response = response; }
        public ModelChatResponse chat(ResolvedModelRoute route, ModelChatRequest request) { lastRequest = request; return response; }
    }

    private static final class RecordingSettlement implements PointSettlementService {
        private SettlePointsCommand lastCommand;
        public PointSettlementResult settle(SettlePointsCommand command) {
            lastCommand = command;
            return new PointSettlementResult(uuid(701), command.reservationId(), command.capturedAmount(), 0,
                    "CAPTURED", NOW, false);
        }
    }

    private static final class RecordingRepository implements AiInvocationRepository {
        private Optional<ClaimedInvocation> next; private final boolean finalAccessCurrent;
        private ClaimedInvocation lastRecorded; private int preModelFenceCount; private boolean publishFenceChecked;
        private boolean accessBlocked, published; private String lastAccessError;
        private InvocationContextAuthoritySnapshot snapshot;
        private RecordingRepository(ClaimedInvocation invocation, boolean finalAccessCurrent) {
            next = Optional.of(invocation); this.finalAccessCurrent = finalAccessCurrent;
        }
        public Optional<ClaimedInvocation> claimNext(String w, Instant n, Instant l) { var v=next; next=Optional.empty(); return v; }
        public List<ContextMessage> recentMessages(ClaimedInvocation i, int l) { return List.of(
                new ContextMessage(ContextMessage.Role.HUMAN,"张三","历史问题"),
                new ContextMessage(ContextMessage.Role.AGENT,"合同审核员工","历史回答")); }
        public UUID saveContext(ClaimedInvocation i, InvocationContextSnapshot s) {
            snapshot = new InvocationContextAuthoritySnapshot(uuid(999), s.invocationBoundary(),
                    s.fencedContext().authorizationSnapshotHash(), s.contextHash(), s.fencedContext().evidence(), NOW);
            return snapshot.contextSnapshotId();
        }
        public Optional<InvocationContextAuthoritySnapshot> loadContextAuthority(ClaimedInvocation i) { return Optional.ofNullable(snapshot); }
        public void scheduleContextRetry(ClaimedInvocation i,String e,Instant r,Instant n) { }
        public boolean lockPreModelAccessCurrent(ClaimedInvocation i, Instant n) { preModelFenceCount++; return true; }
        public ClaimedInvocation recordProviderResponse(ClaimedInvocation s, ModelChatResponse r, Instant a, Instant b) {
            lastRecorded = new ClaimedInvocation(s.invocationId(),s.tenantId(),s.conversationId(),s.groupConversation(),
                    s.sourceMessageId(),s.sourceSequenceNo(),s.membershipVersion(),s.policyVersion(),s.historyFloorSequenceNo(),
                    s.userQuery(),s.requestedBy(),s.enterpriseAgentId(),s.agentVersionId(),s.configurationVersionId(),s.roleName(),
                    s.platformProfile(),s.enterpriseInstructions(),s.knowledgeScopeMode(),s.modelRouteBindingId(),s.modelDefinitionId(),
                    s.pointReservationId(),s.audienceUserIds(),s.accessStillCurrent(),r.usageConfirmed()?"RESPONSE_RECEIVED":"USAGE_PENDING",
                    s.attemptNo(),s.leaseEpoch(),r.usageConfirmed()?s.leaseOwner():null,r.text(),r.inputTokens(),r.outputTokens(),r.usageConfirmed(),r.providerRequestId());
            return lastRecorded;
        }
        public void recordProviderFailure(ClaimedInvocation i,String e,Instant a,Instant b) { }
        public void markContextBlocked(ClaimedInvocation i,String e,Instant n) { }
        public boolean lockPublishAccessCurrent(ClaimedInvocation i,Instant n) { publishFenceChecked=true; return finalAccessCurrent; }
        public void markAccessBlocked(ClaimedInvocation i,String e,Instant n) { accessBlocked=true; lastAccessError=e; }
        public void publishResponse(ClaimedInvocation i,long c,Instant n) { published=true; }
    }
}

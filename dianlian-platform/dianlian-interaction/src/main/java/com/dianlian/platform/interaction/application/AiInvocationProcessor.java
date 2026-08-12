package com.dianlian.platform.interaction.application;

import com.dianlian.platform.billing.api.PointSettlementService;
import com.dianlian.platform.billing.api.SettlePointsCommand;
import com.dianlian.platform.context.api.AgentContextPipeline;
import com.dianlian.platform.context.api.AgentContextRequest;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalException;
import com.dianlian.platform.context.api.ContextAuthorityViolationException;
import com.dianlian.platform.employee.api.EnterpriseAgentKnowledgeScopeMode;
import com.dianlian.platform.model.api.ModelChatMessage;
import com.dianlian.platform.model.api.ModelChatRequest;
import com.dianlian.platform.model.api.ModelGateway;
import com.dianlian.platform.model.api.ModelProviderUnavailableException;
import com.dianlian.platform.model.api.ModelRouteQuery;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Duration;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class AiInvocationProcessor {

    private final AiInvocationRepository repository;
    private final AgentContextPipeline contextPipeline;
    private final ModelRouteQuery modelRouteQuery;
    private final ModelGateway modelGateway;
    private final PointSettlementService pointSettlementService;
    private final TransactionTemplate transactionTemplate;
    private final Clock clock;

    @Autowired
    public AiInvocationProcessor(
            AiInvocationRepository repository,
            AgentContextPipeline contextPipeline,
            ModelRouteQuery modelRouteQuery,
            ModelGateway modelGateway,
            PointSettlementService pointSettlementService,
            TransactionTemplate transactionTemplate
    ) {
        this(repository, contextPipeline, modelRouteQuery, modelGateway,
                pointSettlementService, transactionTemplate, Clock.systemUTC());
    }

    AiInvocationProcessor(
            AiInvocationRepository repository,
            AgentContextPipeline contextPipeline,
            ModelRouteQuery modelRouteQuery,
            ModelGateway modelGateway,
            PointSettlementService pointSettlementService,
            TransactionTemplate transactionTemplate,
            Clock clock
    ) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
        this.contextPipeline = Objects.requireNonNull(contextPipeline, "contextPipeline must not be null");
        this.modelRouteQuery = Objects.requireNonNull(modelRouteQuery, "modelRouteQuery must not be null");
        this.modelGateway = Objects.requireNonNull(modelGateway, "modelGateway must not be null");
        this.pointSettlementService = Objects.requireNonNull(pointSettlementService, "pointSettlementService must not be null");
        this.transactionTemplate = Objects.requireNonNull(transactionTemplate, "transactionTemplate must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
    }

    public boolean processNext(String workerId) {
        var now = clock.instant();
        var claimed = transactionTemplate.execute(status -> repository.claimNext(
                workerId, now, now.plus(Duration.ofMinutes(3))));
        if (claimed == null || claimed.isEmpty()) return false;
        var invocation = claimed.orElseThrow();
        if (invocation.responseReady()) {
            finalizeResponse(invocation);
            return true;
        }
        if (!invocation.accessStillCurrent()) {
            blockAccessAndRelease(invocation, "CONVERSATION_ACCESS_CHANGED");
            return true;
        }

        var recentMessages = transactionTemplate.execute(status -> repository.recentMessages(invocation, 30));
        var knowledgeMode = EnterpriseAgentKnowledgeScopeMode.valueOf(invocation.knowledgeScopeMode());
        var request = new AgentContextRequest(
                invocation.tenantId(),
                invocation.requestedBy(),
                invocation.enterpriseAgentId(),
                invocation.conversationId(),
                invocation.groupConversation(),
                invocation.agentVersionId(),
                invocation.configurationVersionId(),
                invocation.roleName(),
                invocation.platformProfile(),
                invocation.enterpriseInstructions(),
                invocation.userQuery(),
                invocation.sourceMessageId(),
                invocation.sourceSequenceNo(),
                invocation.membershipVersion(),
                invocation.policyVersion(),
                invocation.historyFloorSequenceNo(),
                invocation.audienceUserIds(),
                recentMessages == null ? List.of() : recentMessages,
                knowledgeMode != EnterpriseAgentKnowledgeScopeMode.NONE,
                knowledgeMode == EnterpriseAgentKnowledgeScopeMode.ENTERPRISE_REQUIRED,
                false
        );
        final com.dianlian.platform.context.api.FencedAgentContext fencedContext;
        try {
            var plan = transactionTemplate.execute(status -> {
                if (!repository.lockPreModelAccessCurrent(invocation, clock.instant())) {
                    throw new ContextAuthorityViolationException("CONVERSATION_ACCESS_CHANGED_BEFORE_RETRIEVAL");
                }
                return contextPipeline.authorize(request, clock.instant());
            });
            var draft = contextPipeline.retrieve(
                    Objects.requireNonNull(plan), UUID.randomUUID(), UUID.randomUUID(),
                    clock.instant().plusSeconds(15));
            fencedContext = transactionTemplate.execute(status -> {
                if (!repository.lockPreModelAccessCurrent(invocation, clock.instant())) {
                    throw new ContextAuthorityViolationException("CONVERSATION_ACCESS_CHANGED_BEFORE_MODEL");
                }
                var fenced = contextPipeline.fenceAndAssemble(draft, clock.instant());
                repository.saveContext(invocation, new InvocationContextSnapshot(
                        fenced, plan.invocation(), hashContext(fenced.context()), clock.instant()));
                return fenced;
            });
        } catch (AuthorizedContextRetrievalException exception) {
            if (exception.retryable() && invocation.attemptNo() < 3) {
                transactionTemplate.executeWithoutResult(status -> repository.scheduleContextRetry(
                        invocation, exception.code(), clock.instant().plusSeconds(retryDelay(invocation.attemptNo())),
                        clock.instant()));
            } else {
                blockAndRelease(invocation, exception.code());
            }
            return true;
        } catch (ContextAuthorityViolationException exception) {
            blockAndRelease(invocation, exception.code());
            return true;
        }
        var context = Objects.requireNonNull(fencedContext).context();
        if (!context.ready()) {
            blockAndRelease(invocation, String.join(",", context.blockers()));
            return true;
        }

        var route = modelRouteQuery.requireSnapshot(
                invocation.modelRouteBindingId(), invocation.modelDefinitionId());
        var startedAt = clock.instant();
        try {
            var messages = new java.util.ArrayList<ModelChatMessage>();
            for (var message : context.recentMessages()) {
                messages.add(new ModelChatMessage(
                        message.role() == com.dianlian.platform.context.api.ContextMessage.Role.HUMAN
                                ? ModelChatMessage.Role.HUMAN : ModelChatMessage.Role.AGENT,
                        "[发言人：" + message.actorLabel() + "] " + message.text()
                ));
            }
            messages.add(new ModelChatMessage(ModelChatMessage.Role.HUMAN, invocation.userQuery()));
            var response = modelGateway.chat(route, new ModelChatRequest(
                    invocation.invocationId(),
                    context.systemInstruction(),
                    messages
            ));
            var refreshed = transactionTemplate.execute(status -> repository.recordProviderResponse(
                    invocation, response, startedAt, clock.instant()));
            var persisted = Objects.requireNonNull(refreshed, "provider response must be persisted");
            if (persisted.usageConfirmed()) {
                finalizeResponse(persisted);
            }
        } catch (ModelProviderUnavailableException exception) {
            transactionTemplate.executeWithoutResult(status -> {
                repository.recordProviderFailure(invocation, "MODEL_PROVIDER_UNAVAILABLE", startedAt, clock.instant());
                settle(invocation, 0, "MODEL_PROVIDER_FAILURE");
            });
        }
        return true;
    }

    private void finalizeResponse(AiInvocationRepository.ClaimedInvocation invocation) {
        if (!invocation.usageConfirmed()) return;
        var route = modelRouteQuery.requireSnapshot(
                invocation.modelRouteBindingId(), invocation.modelDefinitionId());
        long captured = calculateCharge(
                invocation.inputTokens(), invocation.outputTokens(),
                route.model().inputRateMicroCreditPerMillionTokens(),
                route.model().outputRateMicroCreditPerMillionTokens(),
                route.model().reservationCeilingMicroCredit()
        );
        transactionTemplate.executeWithoutResult(status -> {
            if (!repository.lockPublishAccessCurrent(invocation, clock.instant())) {
                repository.markAccessBlocked(invocation, "CONVERSATION_ACCESS_CHANGED", clock.instant());
                settle(invocation, 0, "ACCESS_REVOKED_AFTER_PROVIDER");
                return;
            }
            var authority = repository.loadContextAuthority(invocation)
                    .orElseThrow(() -> new IllegalStateException("AI invocation context authority is missing"));
            var reauthorized = contextPipeline.reauthorize(
                    authority.invocationBoundary(), authority.evidence(), clock.instant());
            if (!reauthorized.contractAccepted()
                    || reauthorized.allowedEvidence().size() != authority.evidence().size()) {
                repository.markAccessBlocked(invocation, "EVIDENCE_REVOKED_AFTER_PROVIDER", clock.instant());
                settle(invocation, 0, "EVIDENCE_REVOKED_AFTER_PROVIDER");
                return;
            }
            settle(invocation, captured, "MODEL_USAGE");
            repository.publishResponse(invocation, captured, clock.instant());
        });
    }

    private void blockAndRelease(AiInvocationRepository.ClaimedInvocation invocation, String errorCode) {
        transactionTemplate.executeWithoutResult(status -> {
            repository.markContextBlocked(invocation, errorCode, clock.instant());
            settle(invocation, 0, "CONTEXT_BLOCKED");
        });
    }

    private void blockAccessAndRelease(AiInvocationRepository.ClaimedInvocation invocation, String errorCode) {
        transactionTemplate.executeWithoutResult(status -> {
            repository.markAccessBlocked(invocation, errorCode, clock.instant());
            settle(invocation, 0, "ACCESS_BLOCKED");
        });
    }

    private void settle(
            AiInvocationRepository.ClaimedInvocation invocation,
            long captured,
            String reasonCode
    ) {
        pointSettlementService.settle(new SettlePointsCommand(
                invocation.tenantId(),
                invocation.requestedBy(),
                invocation.pointReservationId(),
                captured,
                "ai-invocation-settlement:" + invocation.invocationId(),
                hashText(invocation.invocationId() + ":" + captured + ":" + reasonCode),
                reasonCode
        ));
    }

    private static long calculateCharge(
            int inputTokens,
            int outputTokens,
            long inputRate,
            long outputRate,
            long ceiling
    ) {
        long input = ceilDiv(Math.multiplyExact((long) inputTokens, inputRate), 1_000_000L);
        long output = ceilDiv(Math.multiplyExact((long) outputTokens, outputRate), 1_000_000L);
        return Math.min(Math.addExact(input, output), ceiling);
    }

    private static long ceilDiv(long value, long divisor) {
        return value == 0 ? 0 : Math.addExact(value, divisor - 1) / divisor;
    }

    private static long retryDelay(int attemptNo) {
        return Math.min(30, 1L << Math.max(0, attemptNo - 1));
    }

    private static String hashContext(com.dianlian.platform.context.api.AgentContextBundle context) {
        return hashText(context.agentVersionId() + "\n" + context.configurationVersionId() + "\n"
                + context.systemInstruction() + "\n" + context.memoryScopes() + "\n"
                + context.recentMessages());
    }

    private static String hashText(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is required", exception);
        }
    }
}

package com.dianlian.platform.context.application;

import com.dianlian.platform.context.api.AgentContextBundle;
import com.dianlian.platform.context.api.AgentContextPipeline;
import com.dianlian.platform.context.api.AgentContextRequest;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextRetrievalRequest;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RetrievalPolicy;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalPort;
import com.dianlian.platform.context.api.ContextAuthorizationPlan;
import com.dianlian.platform.context.api.ContextAuthorityPort;
import com.dianlian.platform.context.api.ContextAuthorityViolationException;
import com.dianlian.platform.context.api.ContextEvidence;
import com.dianlian.platform.context.api.ContextSourceResult;
import com.dianlian.platform.context.api.ContextSourceState;
import com.dianlian.platform.context.api.FencedAgentContext;
import com.dianlian.platform.context.api.MemoryScopeRef;
import com.dianlian.platform.context.api.MemoryScopeType;
import com.dianlian.platform.context.api.RetrievedContextDraft;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import org.springframework.stereotype.Service;

@Service
public final class AgentContextPipelineApplicationService implements AgentContextPipeline {

    private static final RetrievalPolicy DEFAULT_POLICY = new RetrievalPolicy(20, 20, 20, 12, 8_000);

    private final ContextAuthorityPort authorityPort;
    private final List<AuthorizedContextRetrievalPort> retrievalPorts;

    public AgentContextPipelineApplicationService(
            ContextAuthorityPort authorityPort,
            List<AuthorizedContextRetrievalPort> retrievalPorts
    ) {
        this.authorityPort = Objects.requireNonNull(authorityPort);
        this.retrievalPorts = List.copyOf(Objects.requireNonNull(retrievalPorts));
    }

    @Override
    public ContextAuthorizationPlan authorize(AgentContextRequest request, Instant observedAt) {
        Objects.requireNonNull(request, "request must not be null");
        var invocation = boundary(request, observedAt);
        var authority = authorityPort.authorize(new ContextAuthorityPort.AuthorizationRequest(
                invocation, request.enterpriseKnowledgeEnabled(), true, 2_000
        ));
        if (!authority.accepted()) {
            throw new ContextAuthorityViolationException(authority.rejectionCode());
        }
        validateMemoryScopes(request, authority.memoryScopes());
        var sources = new ArrayList<RequestedSource>();
        if (request.enterpriseKnowledgeEnabled() && !authority.knowledgeResources().isEmpty()) {
            sources.add(RequestedSource.KNOWLEDGE);
        }
        if (!authority.memoryScopes().isEmpty()) sources.add(RequestedSource.MEMORY);
        if (sources.isEmpty()) {
            throw new ContextAuthorityViolationException("NO_AUTHORIZED_CONTEXT_SOURCE");
        }
        String hash = AuthorizationSnapshotHasher.hash(
                invocation, authority.knowledgeResources(), authority.memoryScopes(), sources, DEFAULT_POLICY);
        return new ContextAuthorizationPlan(request, invocation, authority, sources, DEFAULT_POLICY, hash);
    }

    @Override
    public RetrievedContextDraft retrieve(
            ContextAuthorizationPlan plan,
            UUID requestId,
            UUID traceId,
            Instant deadlineAt
    ) {
        Objects.requireNonNull(plan, "plan must not be null");
        var request = new ContextRetrievalRequest(
                AuthorizedContextRetrievalContract.B0_CONTRACT_VERSION,
                requestId,
                traceId,
                deadlineAt,
                plan.request().tenantId(),
                plan.request().actorUserId(),
                plan.request().enterpriseAgentId(),
                plan.request().conversationId(),
                plan.request().userQuery(),
                plan.request().audienceUserIds(),
                plan.authority().knowledgeResources(),
                plan.authority().memoryScopes(),
                plan.requestedSources(),
                plan.retrievalPolicy(),
                plan.authorizationSnapshotHash()
        );
        if (retrievalPorts.size() != 1) {
            throw new com.dianlian.platform.context.api.AuthorizedContextRetrievalException(
                    "CONTEXT_RETRIEVAL_SERVICE_NOT_CONNECTED",
                    true
            );
        }
        return new RetrievedContextDraft(plan, request, retrievalPorts.getFirst().retrieve(request));
    }

    @Override
    public FencedAgentContext fenceAndAssemble(RetrievedContextDraft draft, Instant observedAt) {
        Objects.requireNonNull(draft, "draft must not be null");
        var allEvidence = new ArrayList<com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextEvidence>();
        allEvidence.addAll(draft.retrievalBundle().knowledge().evidence());
        allEvidence.addAll(draft.retrievalBundle().memory().evidence());
        var reauthorized = authorityPort.reauthorize(new ContextAuthorityPort.ReauthorizationRequest(
                withObservedAt(draft.plan().invocation(), observedAt),
                allEvidence.stream().map(AgentContextPipelineApplicationService::identity).toList()));
        if (!reauthorized.contractAccepted()) {
            throw new ContextAuthorityViolationException(reauthorized.rejectionCode());
        }
        var allowedIds = reauthorized.allowedEvidence().stream()
                .map(ContextAuthorityPort.EvidenceIdentity::evidenceId)
                .collect(java.util.stream.Collectors.toUnmodifiableSet());
        var allowed = allEvidence.stream().filter(item -> allowedIds.contains(item.evidenceId())).toList();
        var knowledge = sourceResult(
                RequestedSource.KNOWLEDGE,
                allowed,
                draft.retrievalBundle().knowledge().reasonCode(),
                "KNOWLEDGE_NO_AUTHORIZED_EVIDENCE"
        );
        var memory = sourceResult(
                RequestedSource.MEMORY,
                allowed,
                draft.retrievalBundle().memory().reasonCode(),
                "MEMORY_NO_CONFIRMED_EVIDENCE"
        );
        var blockers = new ArrayList<String>();
        if (draft.plan().request().enterpriseKnowledgeRequired()
                && knowledge.state() != ContextSourceState.READY) {
            blockers.add("REQUIRED_KNOWLEDGE_REVOKED_BEFORE_MODEL");
        }
        if (draft.plan().request().longTermMemoryRequired()
                && memory.state() != ContextSourceState.READY) {
            blockers.add("REQUIRED_LONG_TERM_MEMORY_REVOKED_BEFORE_MODEL");
        }
        var context = new AgentContextBundle(
                draft.plan().request().agentVersionId(),
                draft.plan().request().configurationVersionId(),
                RoleContextApplicationService.renderSystemInstruction(draft.plan().request(), knowledge, memory),
                draft.plan().request().recentMessages(),
                knowledge,
                memory,
                draft.plan().authority().memoryScopes().stream().map(scope -> new MemoryScopeRef(
                        scope.tenantId(), MemoryScopeType.valueOf(scope.scopeType().name()),
                        scope.scopeId(), scope.enterpriseAgentId())).toList(),
                blockers
        );
        var evidence = allowed.stream().map(AgentContextPipelineApplicationService::identity).toList();
        return new FencedAgentContext(
                context,
                draft.plan().authorizationSnapshotHash(),
                draft.retrievalRequest().requestId(),
                draft.retrievalBundle().retrievalSnapshotId(),
                draft.retrievalBundle().retrievalTrace(),
                evidence,
                knowledge.reasonCode(),
                memory.reasonCode(),
                observedAt
        );
    }

    @Override
    public ContextAuthorityPort.Reauthorization reauthorize(
            ContextAuthorityPort.InvocationBoundary invocation,
            List<ContextAuthorityPort.EvidenceIdentity> evidence,
            Instant observedAt
    ) {
        return authorityPort.reauthorize(new ContextAuthorityPort.ReauthorizationRequest(
                withObservedAt(invocation, observedAt), evidence));
    }

    private static ContextAuthorityPort.InvocationBoundary boundary(AgentContextRequest request, Instant observedAt) {
        return new ContextAuthorityPort.InvocationBoundary(
                request.tenantId(), request.actorUserId(), request.enterpriseAgentId(),
                request.agentVersionId(), request.configurationVersionId(), request.conversationId(),
                request.groupConversation(), request.sourceMessageId(), request.sourceSequenceNo(),
                request.membershipVersion(), request.policyVersion(), request.audienceUserIds(),
                request.historyFloorSequenceNo(), observedAt
        );
    }

    private static ContextAuthorityPort.InvocationBoundary withObservedAt(
            ContextAuthorityPort.InvocationBoundary source,
            Instant observedAt
    ) {
        return new ContextAuthorityPort.InvocationBoundary(
                source.tenantId(), source.actorUserId(), source.enterpriseAgentId(), source.agentVersionId(),
                source.configurationVersionId(), source.conversationId(), source.groupConversation(),
                source.sourceMessageId(), source.sourceSequenceNo(), source.membershipVersion(),
                source.policyVersion(), source.audienceUserIds(), source.historyFloorSequenceNo(), observedAt
        );
    }

    private static ContextSourceResult sourceResult(
            RequestedSource type,
            List<com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextEvidence> allowed,
            String originalReason,
            String emptyReason
    ) {
        var evidence = allowed.stream().filter(item -> item.sourceType() == type)
                .map(AgentContextPipelineApplicationService::evidence).toList();
        return evidence.isEmpty()
                ? ContextSourceResult.empty(originalReason == null ? emptyReason : originalReason)
                : new ContextSourceResult(ContextSourceState.READY, evidence, null);
    }

    private static ContextEvidence evidence(
            com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextEvidence value
    ) {
        return new ContextEvidence(
                value.evidenceId(), value.sourceType().name(), value.sourceId(), value.sourceVersion(),
                value.chunkId(), value.title(), value.excerpt(), value.contentHash(), value.score(), value.citation());
    }

    private static ContextAuthorityPort.EvidenceIdentity identity(
            com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextEvidence value
    ) {
        return new ContextAuthorityPort.EvidenceIdentity(
                value.evidenceId(), value.sourceType(), value.sourceId(), value.sourceVersion(), value.chunkId(),
                value.contentHash(), value.citation());
    }

    private static void validateMemoryScopes(
            AgentContextRequest request,
            List<com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScope> scopes
    ) {
        if (request.groupConversation() && scopes.stream()
                .anyMatch(scope -> scope.scopeType()
                        == com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScopeType.USER_AGENT)) {
            throw new ContextAuthorityViolationException("GROUP_PRIVATE_SCOPE_CONTRACT_VIOLATION");
        }
        if (!request.groupConversation() && scopes.stream()
                .anyMatch(scope -> scope.scopeType()
                        == com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScopeType.GROUP_AGENT)) {
            throw new ContextAuthorityViolationException("DIRECT_GROUP_SCOPE_CONTRACT_VIOLATION");
        }
    }
}

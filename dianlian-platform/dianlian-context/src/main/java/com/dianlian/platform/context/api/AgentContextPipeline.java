package com.dianlian.platform.context.api;

import java.time.Instant;
import java.util.UUID;

public interface AgentContextPipeline {

    ContextAuthorizationPlan authorize(AgentContextRequest request, Instant observedAt);

    RetrievedContextDraft retrieve(
            ContextAuthorizationPlan plan,
            UUID requestId,
            UUID traceId,
            Instant deadlineAt
    );

    FencedAgentContext fenceAndAssemble(RetrievedContextDraft draft, Instant observedAt);

    ContextAuthorityPort.Reauthorization reauthorize(
            ContextAuthorityPort.InvocationBoundary invocation,
            java.util.List<ContextAuthorityPort.EvidenceIdentity> evidence,
            Instant observedAt
    );
}

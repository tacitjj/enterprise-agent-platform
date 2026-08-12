package com.dianlian.platform.context.api;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RetrievalPolicy;
import java.util.List;
import java.util.Objects;

public record ContextAuthorizationPlan(
        AgentContextRequest request,
        ContextAuthorityPort.InvocationBoundary invocation,
        ContextAuthorityPort.Authorization authority,
        List<RequestedSource> requestedSources,
        RetrievalPolicy retrievalPolicy,
        String authorizationSnapshotHash
) {
    public ContextAuthorizationPlan {
        Objects.requireNonNull(request, "request must not be null");
        Objects.requireNonNull(invocation, "invocation must not be null");
        Objects.requireNonNull(authority, "authority must not be null");
        if (!authority.accepted()) {
            throw new IllegalArgumentException("authorization plan requires accepted authority");
        }
        requestedSources = List.copyOf(Objects.requireNonNull(requestedSources, "requestedSources must not be null"));
        Objects.requireNonNull(retrievalPolicy, "retrievalPolicy must not be null");
        authorizationSnapshotHash = Objects.requireNonNull(
                authorizationSnapshotHash,
                "authorizationSnapshotHash must not be null"
        );
        if (!authorizationSnapshotHash.matches("^[0-9a-f]{64}$")) {
            throw new IllegalArgumentException("authorizationSnapshotHash must be lowercase SHA-256");
        }
    }
}

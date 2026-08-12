package com.dianlian.platform.context.api;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextBundle;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextRetrievalRequest;
import java.util.Objects;

public record RetrievedContextDraft(
        ContextAuthorizationPlan plan,
        ContextRetrievalRequest retrievalRequest,
        ContextBundle retrievalBundle
) {
    public RetrievedContextDraft {
        Objects.requireNonNull(plan, "plan must not be null");
        Objects.requireNonNull(retrievalRequest, "retrievalRequest must not be null");
        Objects.requireNonNull(retrievalBundle, "retrievalBundle must not be null");
        if (!retrievalRequest.requestId().equals(retrievalBundle.requestId())) {
            throw new IllegalArgumentException("retrieval response requestId does not match request");
        }
    }
}

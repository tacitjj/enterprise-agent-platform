package com.dianlian.platform.knowledge.api;

import com.dianlian.platform.identity.api.AccessContext;
import java.util.List;

/**
 * Resolves a fresh, invocation-scoped allowlist before calling the Python retriever.
 * Implementations must evaluate current grants for every audience member.
 */
public interface KnowledgeAuthorizationSource {

    List<AuthorizedKnowledgeResourceRef> resolveAuthorizedResources(
            ResolveAuthorizedKnowledgeResourcesQuery query,
            AccessContext accessContext
    );
}

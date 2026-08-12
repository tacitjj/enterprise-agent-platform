package com.dianlian.platform.knowledge.api;

import java.util.List;

/**
 * Provides fresh knowledge authority decisions for asynchronous AI invocations.
 *
 * <p>This boundary accepts the invocation identity captured by the trusted Java control plane. It
 * never accepts or synthesizes an interactive {@code AccessContext}, and it returns identifiers
 * only—never document text or excerpts.</p>
 */
public interface InvocationKnowledgeAuthoritySource {

    /**
     * Resolves the current, invocation-scoped knowledge allowlist.
     *
     * <p>The operation is read-only and performs no caching. Repeating it against the same database
     * state and {@code observedAt} produces the same canonically ordered result.</p>
     *
     * @param query trusted invocation identity, full audience and result bound
     * @return exact document/version identifiers currently authorized for every audience member
     */
    List<AuthorizedKnowledgeResourceRef> authorize(InvocationKnowledgeAuthorizationQuery query);

    /**
     * Rechecks the exact evidence actually returned by a retriever before it is consumed.
     *
     * @param query trusted invocation identity plus the exact document/version set to recheck
     * @return canonically ordered allowed and rejected identifiers without document content
     */
    InvocationKnowledgeReauthorizationResult reauthorize(
            InvocationKnowledgeReauthorizationQuery query
    );
}

package com.dianlian.platform.knowledge.api;

/** Stable rejection reason returned without revealing resource existence across tenants. */
public enum InvocationKnowledgeRejectionReason {
    /**
     * Current execution identity, binding, resource state, version state or audience ACL no longer
     * authorizes this evidence. All failures deliberately share one reason to prevent enumeration.
     */
    CURRENT_AUTHORITY_DENIED
}

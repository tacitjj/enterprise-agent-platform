package com.dianlian.platform.memory.api;

import com.dianlian.platform.memory.api.InvocationMemoryAuthoritySource.AuthorizeScopesQuery;

/**
 * Verifies current tenant, audience, conversation, and digital-employee binding authority.
 *
 * <p>An implementation must fail closed and, for a group invocation, verify that the supplied
 * audience is the exact current active human audience rather than merely checking the requester.
 * For a direct invocation it must verify the single human audience and active employee binding.</p>
 */
@FunctionalInterface
public interface InvocationMemoryBoundaryVerifier {

    boolean isAuthorized(AuthorizeScopesQuery query);
}

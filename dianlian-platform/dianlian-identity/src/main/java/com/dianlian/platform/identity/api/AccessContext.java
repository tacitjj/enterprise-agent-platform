package com.dianlian.platform.identity.api;

import java.time.Instant;
import java.util.Objects;
import java.util.Set;

public final class AccessContext {

    private final TenantId tenantId;
    private final ActorId actorId;
    private final Set<String> authorities;
    private final Instant authenticatedAt;

    private AccessContext(
            TenantId tenantId,
            ActorId actorId,
            Set<String> authorities,
            Instant authenticatedAt
    ) {
        this.tenantId = Objects.requireNonNull(tenantId, "tenantId must not be null");
        this.actorId = Objects.requireNonNull(actorId, "actorId must not be null");
        this.authorities = Set.copyOf(Objects.requireNonNull(authorities, "authorities must not be null"));
        this.authenticatedAt = Objects.requireNonNull(authenticatedAt, "authenticatedAt must not be null");
    }

    static AccessContext authenticated(
            TenantId tenantId,
            ActorId actorId,
            Set<String> authorities,
            Instant authenticatedAt
    ) {
        return new AccessContext(tenantId, actorId, authorities, authenticatedAt);
    }

    /**
     * Builds the business access context from an already authenticated server-side principal.
     * Request parameters must never be used to construct this context.
     */
    public static AccessContext fromAuthenticatedPrincipal(AuthenticatedPrincipal principal) {
        Objects.requireNonNull(principal, "principal must not be null");
        return new AccessContext(
                principal.requireActiveTenantId(),
                principal.actorId(),
                principal.permissions(),
                principal.authenticatedAt()
        );
    }

    public TenantId tenantId() {
        return tenantId;
    }

    public ActorId actorId() {
        return actorId;
    }

    public Set<String> authorities() {
        return authorities;
    }

    public Instant authenticatedAt() {
        return authenticatedAt;
    }
}

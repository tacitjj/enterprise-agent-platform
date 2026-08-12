package com.dianlian.platform.identity.api;

import java.time.Instant;
import java.util.Objects;
import java.util.Set;

/**
 * Server-derived authority for platform-owned resources.
 * Tenant sessions can never be promoted into this context by carrying a platform permission string.
 */
public final class PlatformAccessContext {

    private final ActorId actorId;
    private final Set<String> authorities;
    private final Instant authenticatedAt;

    private PlatformAccessContext(ActorId actorId, Set<String> authorities, Instant authenticatedAt) {
        this.actorId = Objects.requireNonNull(actorId, "actorId must not be null");
        this.authorities = Set.copyOf(Objects.requireNonNull(authorities, "authorities must not be null"));
        this.authenticatedAt = Objects.requireNonNull(authenticatedAt, "authenticatedAt must not be null");
    }

    public static PlatformAccessContext fromAuthenticatedPrincipal(AuthenticatedPrincipal principal) {
        Objects.requireNonNull(principal, "principal must not be null");
        boolean platformGrant = principal.roleGrants().stream()
                .anyMatch(grant -> grant.scopeType() == SessionView.DataScopeType.PLATFORM);
        if (principal.activeTenant() != null || !platformGrant) {
            throw new PlatformAccessRequiredException();
        }
        return new PlatformAccessContext(
                principal.actorId(),
                principal.permissions(),
                principal.authenticatedAt()
        );
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

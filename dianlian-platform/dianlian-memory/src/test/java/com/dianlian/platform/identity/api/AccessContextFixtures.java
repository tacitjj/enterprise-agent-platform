package com.dianlian.platform.identity.api;

import java.time.Instant;
import java.util.Set;
import java.util.UUID;

public final class AccessContextFixtures {

    private AccessContextFixtures() {
    }

    public static AccessContext authenticated(UUID tenantId, UUID actorId, String... authorities) {
        return AccessContext.authenticated(
                new TenantId(tenantId),
                new ActorId(actorId),
                Set.of(authorities),
                Instant.parse("2026-08-12T00:00:00Z")
        );
    }
}

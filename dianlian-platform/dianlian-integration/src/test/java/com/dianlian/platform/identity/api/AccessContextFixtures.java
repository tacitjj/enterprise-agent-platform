package com.dianlian.platform.identity.api;

import java.time.Instant;
import java.util.Set;
import java.util.UUID;

public final class AccessContextFixtures {

    private AccessContextFixtures() {
    }

    public static AccessContext authenticated() {
        return AccessContext.authenticated(
                new TenantId(UUID.fromString("00000000-0000-0000-0000-000000000001")),
                new ActorId(UUID.fromString("00000000-0000-0000-0000-000000000002")),
                Set.of("TASK_EXECUTE"),
                Instant.parse("2026-01-01T00:00:00Z")
        );
    }
}

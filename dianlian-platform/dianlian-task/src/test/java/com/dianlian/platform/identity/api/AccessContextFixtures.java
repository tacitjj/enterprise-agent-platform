package com.dianlian.platform.identity.api;

import java.time.Instant;
import java.util.Set;
import java.util.UUID;

public final class AccessContextFixtures {

    public static final UUID TENANT_ID = UUID.fromString("00000000-0000-0000-0000-000000000001");
    public static final UUID ACTOR_ID = UUID.fromString("00000000-0000-0000-0000-000000000002");

    private AccessContextFixtures() {
    }

    public static AccessContext authenticated() {
        return authenticated(Set.of("enterprise.employee.execute", "task.create"));
    }

    public static AccessContext authenticated(Set<String> authorities) {
        return AccessContext.authenticated(
                new TenantId(TENANT_ID),
                new ActorId(ACTOR_ID),
                authorities,
                Instant.parse("2026-01-01T00:00:00Z")
        );
    }
}

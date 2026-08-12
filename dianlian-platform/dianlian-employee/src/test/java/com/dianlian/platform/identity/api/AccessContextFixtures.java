package com.dianlian.platform.identity.api;

import java.time.Instant;
import java.util.Set;
import java.util.List;
import java.util.UUID;

public final class AccessContextFixtures {

    private AccessContextFixtures() {
    }

    public static AccessContext authenticated(UUID tenantId, UUID actorId, String... authorities) {
        return AccessContext.authenticated(
                new TenantId(tenantId),
                new ActorId(actorId),
                Set.of(authorities),
                Instant.parse("2026-08-11T00:00:00Z")
        );
    }

    public static AuthenticatedPrincipal platformPrincipal(UUID actorId, String... permissions) {
        Instant authenticatedAt = Instant.parse("2026-08-11T00:00:00Z");
        return new AuthenticatedPrincipal(
                UUID.fromString("90000000-0000-0000-0000-000000000001"),
                new ActorId(actorId),
                "平台模板管理员",
                null,
                SessionView.AccountStatus.ACTIVE,
                null,
                List.of(new SessionView.RoleGrant(
                        "PLATFORM_OPERATOR",
                        SessionView.DataScopeType.PLATFORM,
                        UUID.fromString("10000000-0000-0000-0000-000000000000")
                )),
                Set.of(permissions),
                "platform-v1",
                authenticatedAt,
                authenticatedAt.plusSeconds(3600)
        );
    }
}

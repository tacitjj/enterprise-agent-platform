package com.dianlian.platform.identity.api;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class AccessContextTests {

    @Test
    void derivesTenantActorAndAuthoritiesFromAuthenticatedPrincipal() {
        var principal = principal(tenant());

        var context = AccessContext.fromAuthenticatedPrincipal(principal);

        assertEquals(principal.activeTenant().id(), context.tenantId());
        assertEquals(principal.actorId(), context.actorId());
        assertEquals(Set.of("task:create"), context.authorities());
    }

    @Test
    void platformSessionCannotBeUsedAsTenantBusinessContext() {
        var principal = principal(null);

        assertThrows(
                ActiveTenantRequiredException.class,
                () -> AccessContext.fromAuthenticatedPrincipal(principal)
        );
    }

    private static AuthenticatedPrincipal principal(SessionView.Tenant activeTenant) {
        return new AuthenticatedPrincipal(
                UUID.fromString("00000000-0000-0000-0000-000000000010"),
                new ActorId(UUID.fromString("00000000-0000-0000-0000-000000000020")),
                "测试用户",
                null,
                SessionView.AccountStatus.ACTIVE,
                activeTenant,
                List.of(),
                Set.of("task:create"),
                "v1-test",
                Instant.parse("2026-08-11T00:00:00Z"),
                Instant.parse("2026-08-12T00:00:00Z")
        );
    }

    private static SessionView.Tenant tenant() {
        return new SessionView.Tenant(
                new TenantId(UUID.fromString("00000000-0000-0000-0000-000000000001")),
                "测试企业",
                SessionView.TenantStatus.ACTIVE,
                SessionView.MembershipStatus.ACTIVE
        );
    }
}

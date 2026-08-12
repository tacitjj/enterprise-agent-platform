package com.dianlian.platform.identity.domain;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;

import com.dianlian.platform.identity.api.SessionView;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class PermissionVersionTests {

    private static final SessionView.RoleGrant TENANT_ADMIN = new SessionView.RoleGrant(
            "TENANT_ADMIN",
            SessionView.DataScopeType.TENANT,
            UUID.fromString("00000000-0000-0000-0000-000000000001")
    );

    @Test
    void fingerprintIsIndependentFromCollectionOrder() {
        var first = PermissionVersion.fingerprint(
                1,
                2L,
                3L,
                List.of(TENANT_ADMIN),
                Set.of("task:read", "task:create")
        );
        var second = PermissionVersion.fingerprint(
                1,
                2L,
                3L,
                List.of(TENANT_ADMIN),
                Set.of("task:create", "task:read")
        );

        assertEquals(first, second);
    }

    @Test
    void fingerprintChangesWhenEffectivePermissionChanges() {
        var before = PermissionVersion.fingerprint(
                1,
                2L,
                3L,
                List.of(TENANT_ADMIN),
                Set.of("task:read")
        );
        var after = PermissionVersion.fingerprint(
                1,
                2L,
                3L,
                List.of(TENANT_ADMIN),
                Set.of("task:read", "task:create")
        );

        assertNotEquals(before, after);
    }
}

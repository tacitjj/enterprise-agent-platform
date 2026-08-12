package com.dianlian.platform.employee.api;

import java.util.Objects;
import java.util.Set;
import java.util.UUID;

public record EnterpriseVisibility(EnterpriseVisibilityMode mode, Set<UUID> tenantIds) {

    public EnterpriseVisibility {
        Objects.requireNonNull(mode, "mode must not be null");
        tenantIds = Set.copyOf(Objects.requireNonNull(tenantIds, "tenantIds must not be null"));
        if (mode == EnterpriseVisibilityMode.ALL && !tenantIds.isEmpty()) {
            throw new IllegalArgumentException("ALL visibility must not declare tenantIds");
        }
        if (mode == EnterpriseVisibilityMode.ALLOWLIST && tenantIds.isEmpty()) {
            throw new IllegalArgumentException("ALLOWLIST visibility requires at least one tenantId");
        }
    }

    public static EnterpriseVisibility allEnterprises() {
        return new EnterpriseVisibility(EnterpriseVisibilityMode.ALL, Set.of());
    }

    public static EnterpriseVisibility allowlist(Set<UUID> tenantIds) {
        return new EnterpriseVisibility(EnterpriseVisibilityMode.ALLOWLIST, tenantIds);
    }

    public boolean includes(UUID tenantId) {
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        return mode == EnterpriseVisibilityMode.ALL || tenantIds.contains(tenantId);
    }
}

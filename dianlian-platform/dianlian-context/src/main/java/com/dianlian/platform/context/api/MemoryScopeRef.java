package com.dianlian.platform.context.api;

import java.util.Objects;
import java.util.UUID;

public record MemoryScopeRef(
        UUID tenantId,
        MemoryScopeType scopeType,
        UUID scopeId,
        UUID enterpriseAgentId
) {
    public MemoryScopeRef {
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(scopeType, "scopeType must not be null");
        Objects.requireNonNull(scopeId, "scopeId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
    }
}

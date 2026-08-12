package com.dianlian.platform.model.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record ModelRouteBindingView(
        UUID routeBindingId,
        String scopeType,
        UUID tenantId,
        UUID enterpriseAgentId,
        ModelCapabilityType capabilityType,
        UUID modelDefinitionId,
        long stateVersion,
        String status,
        UUID createdBy,
        Instant createdAt
) {
    public ModelRouteBindingView {
        Objects.requireNonNull(routeBindingId, "routeBindingId must not be null");
        scopeType = ModelValueChecks.code(scopeType, "scopeType", 32);
        Objects.requireNonNull(capabilityType, "capabilityType must not be null");
        Objects.requireNonNull(modelDefinitionId, "modelDefinitionId must not be null");
        if (stateVersion < 1) throw new IllegalArgumentException("stateVersion must be positive");
        status = ModelValueChecks.code(status, "status", 32);
        Objects.requireNonNull(createdBy, "createdBy must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }
}

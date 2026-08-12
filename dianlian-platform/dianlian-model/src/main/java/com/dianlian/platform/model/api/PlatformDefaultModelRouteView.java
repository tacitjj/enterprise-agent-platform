package com.dianlian.platform.model.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

/**
 * Minimal public projection of the currently active platform default route.
 * Model definitions and credential references remain available only through the separately authorized catalog.
 */
public record PlatformDefaultModelRouteView(
        ModelCapabilityType capabilityType,
        UUID modelDefinitionId,
        UUID routeBindingId,
        long stateVersion,
        String status,
        Instant createdAt
) {
    public PlatformDefaultModelRouteView {
        Objects.requireNonNull(capabilityType, "capabilityType must not be null");
        Objects.requireNonNull(modelDefinitionId, "modelDefinitionId must not be null");
        Objects.requireNonNull(routeBindingId, "routeBindingId must not be null");
        if (stateVersion < 1) throw new IllegalArgumentException("stateVersion must be positive");
        if (!"ACTIVE".equals(status)) throw new IllegalArgumentException("status must be ACTIVE");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }
}

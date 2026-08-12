package com.dianlian.platform.model.api;

import java.util.Objects;
import java.util.UUID;

public record ResolvedModelRoute(
        UUID routeBindingId,
        long routeStateVersion,
        String routeSource,
        ModelDefinitionView model
) {
    public ResolvedModelRoute {
        Objects.requireNonNull(routeBindingId, "routeBindingId must not be null");
        if (routeStateVersion < 1) throw new IllegalArgumentException("routeStateVersion must be positive");
        routeSource = ModelValueChecks.code(routeSource, "routeSource", 32);
        Objects.requireNonNull(model, "model must not be null");
    }
}

package com.dianlian.platform.model.api;

import java.util.UUID;

public interface ModelRouteQuery {
    ResolvedModelRoute resolve(
            UUID tenantId,
            UUID enterpriseAgentId,
            ModelCapabilityType capabilityType,
            ModelRoutePreference preference
    );

    ResolvedModelRoute requireSnapshot(UUID routeBindingId, UUID modelDefinitionId);
}

package com.dianlian.platform.model.application;

import com.dianlian.platform.model.api.ModelDefinitionView;
import com.dianlian.platform.model.api.ModelRouteBindingView;
import com.dianlian.platform.model.api.ModelRoutePreference;
import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.PlatformDefaultModelRouteView;
import com.dianlian.platform.model.api.RegisterModelDefinitionCommand;
import com.dianlian.platform.model.api.SetModelRouteCommand;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface ModelRepository {
    Optional<StoredModelDefinition> findDefinitionByIdempotency(UUID actorId, String idempotencyKey);

    ModelDefinitionView insertDefinition(RegisterModelDefinitionCommand command, UUID actorId, Instant now);

    List<ModelDefinitionView> listDefinitions(int limit);

    List<PlatformDefaultModelRouteView> listActivePlatformDefaultRoutes();

    Optional<ModelDefinitionView> findActiveDefinition(UUID modelDefinitionId, ModelCapabilityType capabilityType);

    Optional<StoredRouteBinding> findRouteByIdempotency(UUID actorId, String idempotencyKey);

    ModelRouteBindingView replaceRoute(
            String scopeType,
            UUID tenantId,
            UUID enterpriseAgentId,
            SetModelRouteCommand command,
            UUID actorId,
            Instant now
    );

    Optional<ResolvedRouteRecord> resolve(
            UUID tenantId,
            UUID enterpriseAgentId,
            ModelCapabilityType capabilityType,
            ModelRoutePreference preference
    );

    Optional<ResolvedRouteRecord> findSnapshot(UUID routeBindingId, UUID modelDefinitionId);

    record StoredModelDefinition(ModelDefinitionView definition, String requestHash) {
    }

    record StoredRouteBinding(ModelRouteBindingView binding, String requestHash) {
    }

    record ResolvedRouteRecord(ModelRouteBindingView binding, ModelDefinitionView definition) {
    }
}

package com.dianlian.platform.model.application;

import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.ModelDefinitionView;
import com.dianlian.platform.model.api.ModelRouteBindingView;
import com.dianlian.platform.model.api.ModelRoutePreference;
import com.dianlian.platform.model.api.PlatformDefaultModelRouteView;
import com.dianlian.platform.model.api.RegisterModelDefinitionCommand;
import com.dianlian.platform.model.api.SetModelRouteCommand;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

final class TestModelRepository implements ModelRepository {

    Optional<StoredModelDefinition> definitionReplay = Optional.empty();
    Optional<ResolvedRouteRecord> resolvedRoute = Optional.empty();
    Optional<ResolvedRouteRecord> snapshotRoute = Optional.empty();
    List<PlatformDefaultModelRouteView> platformDefaultRoutes = List.of();
    boolean insertDefinitionCalled;
    boolean listPlatformDefaultRoutesCalled;

    @Override
    public Optional<StoredModelDefinition> findDefinitionByIdempotency(UUID actorId, String idempotencyKey) {
        return definitionReplay;
    }

    @Override
    public ModelDefinitionView insertDefinition(RegisterModelDefinitionCommand command, UUID actorId, Instant now) {
        insertDefinitionCalled = true;
        throw new AssertionError("insertDefinition was not expected");
    }

    @Override
    public List<ModelDefinitionView> listDefinitions(int limit) {
        throw new UnsupportedOperationException();
    }

    @Override
    public List<PlatformDefaultModelRouteView> listActivePlatformDefaultRoutes() {
        listPlatformDefaultRoutesCalled = true;
        return platformDefaultRoutes;
    }

    @Override
    public Optional<ModelDefinitionView> findActiveDefinition(
            UUID modelDefinitionId,
            ModelCapabilityType capabilityType
    ) {
        throw new UnsupportedOperationException();
    }

    @Override
    public Optional<StoredRouteBinding> findRouteByIdempotency(UUID actorId, String idempotencyKey) {
        throw new UnsupportedOperationException();
    }

    @Override
    public ModelRouteBindingView replaceRoute(
            String scopeType,
            UUID tenantId,
            UUID enterpriseAgentId,
            SetModelRouteCommand command,
            UUID actorId,
            Instant now
    ) {
        throw new UnsupportedOperationException();
    }

    @Override
    public Optional<ResolvedRouteRecord> resolve(
            UUID tenantId,
            UUID enterpriseAgentId,
            ModelCapabilityType capabilityType,
            ModelRoutePreference preference
    ) {
        return resolvedRoute;
    }

    @Override
    public Optional<ResolvedRouteRecord> findSnapshot(UUID routeBindingId, UUID modelDefinitionId) {
        return snapshotRoute;
    }
}

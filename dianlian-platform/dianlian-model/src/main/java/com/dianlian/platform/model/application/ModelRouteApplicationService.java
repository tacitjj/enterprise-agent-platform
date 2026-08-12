package com.dianlian.platform.model.application;

import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.ModelDefinitionStatus;
import com.dianlian.platform.model.api.ModelRouteQuery;
import com.dianlian.platform.model.api.ModelRoutePreference;
import com.dianlian.platform.model.api.ModelRouteUnavailableException;
import com.dianlian.platform.model.api.ResolvedModelRoute;
import java.util.Objects;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ModelRouteApplicationService implements ModelRouteQuery {

    private final ModelRepository repository;

    public ModelRouteApplicationService(ModelRepository repository) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
    }

    @Override
    @Transactional(readOnly = true)
    public ResolvedModelRoute resolve(
            UUID tenantId,
            UUID enterpriseAgentId,
            ModelCapabilityType capabilityType,
            ModelRoutePreference preference
    ) {
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(capabilityType, "capabilityType must not be null");
        Objects.requireNonNull(preference, "preference must not be null");
        var route = repository.resolve(tenantId, enterpriseAgentId, capabilityType, preference)
                .orElseThrow(ModelRouteUnavailableException::new);
        if (route.definition().status() != ModelDefinitionStatus.ACTIVE) {
            throw new ModelRouteUnavailableException();
        }
        return new ResolvedModelRoute(
                route.binding().routeBindingId(),
                route.binding().stateVersion(),
                route.binding().scopeType(),
                route.definition()
        );
    }

    @Override
    @Transactional(readOnly = true)
    public ResolvedModelRoute requireSnapshot(UUID routeBindingId, UUID modelDefinitionId) {
        Objects.requireNonNull(routeBindingId, "routeBindingId must not be null");
        Objects.requireNonNull(modelDefinitionId, "modelDefinitionId must not be null");
        var route = repository.findSnapshot(routeBindingId, modelDefinitionId)
                .orElseThrow(ModelRouteUnavailableException::new);
        return new ResolvedModelRoute(
                route.binding().routeBindingId(),
                route.binding().stateVersion(),
                route.binding().scopeType(),
                route.definition()
        );
    }
}

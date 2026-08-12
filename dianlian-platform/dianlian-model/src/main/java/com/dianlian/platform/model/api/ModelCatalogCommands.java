package com.dianlian.platform.model.api;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import java.util.UUID;

public interface ModelCatalogCommands {
    ModelCommandOutcome<ModelDefinitionView> register(
            RegisterModelDefinitionCommand command,
            PlatformAccessContext accessContext
    );

    ModelCommandOutcome<ModelRouteBindingView> setPlatformDefault(
            SetModelRouteCommand command,
            PlatformAccessContext accessContext
    );

    ModelCommandOutcome<ModelRouteBindingView> bindEnterpriseAgent(
            UUID enterpriseAgentId,
            SetModelRouteCommand command,
            AccessContext accessContext
    );
}

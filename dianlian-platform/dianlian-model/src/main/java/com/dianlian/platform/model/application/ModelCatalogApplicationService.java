package com.dianlian.platform.model.application;

import com.dianlian.platform.employee.api.EnterpriseAgentManagementQuery;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import com.dianlian.platform.model.api.ModelAccessDeniedException;
import com.dianlian.platform.model.api.ModelCatalogCommands;
import com.dianlian.platform.model.api.ModelCatalogQuery;
import com.dianlian.platform.model.api.ModelCommandConflictException;
import com.dianlian.platform.model.api.ModelCommandOutcome;
import com.dianlian.platform.model.api.ModelDefinitionView;
import com.dianlian.platform.model.api.ModelPermissions;
import com.dianlian.platform.model.api.ModelRouteBindingView;
import com.dianlian.platform.model.api.PlatformDefaultModelRouteView;
import com.dianlian.platform.model.api.RegisterModelDefinitionCommand;
import com.dianlian.platform.model.api.SetModelRouteCommand;
import java.time.Clock;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ModelCatalogApplicationService implements ModelCatalogCommands, ModelCatalogQuery {

    private static final int LIST_LIMIT = 200;
    private final ModelRepository repository;
    private final EnterpriseAgentManagementQuery enterpriseAgentQuery;
    private final ModelEndpointPolicy endpointPolicy;
    private final Clock clock;

    @Autowired
    public ModelCatalogApplicationService(
            ModelRepository repository,
            EnterpriseAgentManagementQuery enterpriseAgentQuery,
            ModelEndpointPolicy endpointPolicy
    ) {
        this(repository, enterpriseAgentQuery, endpointPolicy, Clock.systemUTC());
    }

    ModelCatalogApplicationService(
            ModelRepository repository,
            EnterpriseAgentManagementQuery enterpriseAgentQuery,
            ModelEndpointPolicy endpointPolicy,
            Clock clock
    ) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
        this.enterpriseAgentQuery = Objects.requireNonNull(
                enterpriseAgentQuery, "enterpriseAgentQuery must not be null");
        this.endpointPolicy = Objects.requireNonNull(endpointPolicy, "endpointPolicy must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
    }

    @Override
    @Transactional
    public ModelCommandOutcome<ModelDefinitionView> register(
            RegisterModelDefinitionCommand command,
            PlatformAccessContext accessContext
    ) {
        requirePlatform(accessContext, ModelPermissions.PLATFORM_MANAGE);
        var replay = repository.findDefinitionByIdempotency(
                accessContext.actorId().value(),
                command.idempotencyKey()
        );
        if (replay.isPresent()) {
            requireSameRequest(replay.orElseThrow().requestHash(), command.requestHash());
            return new ModelCommandOutcome<>(replay.orElseThrow().definition(), true);
        }
        endpointPolicy.validate(command.baseUrl());
        return new ModelCommandOutcome<>(repository.insertDefinition(
                command,
                accessContext.actorId().value(),
                clock.instant()
        ), false);
    }

    @Override
    @Transactional
    public ModelCommandOutcome<ModelRouteBindingView> setPlatformDefault(
            SetModelRouteCommand command,
            PlatformAccessContext accessContext
    ) {
        requirePlatform(accessContext, ModelPermissions.PLATFORM_MANAGE);
        return replaceRoute("PLATFORM", null, null, command, accessContext.actorId().value());
    }

    @Override
    @Transactional
    public ModelCommandOutcome<ModelRouteBindingView> bindEnterpriseAgent(
            UUID enterpriseAgentId,
            SetModelRouteCommand command,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        requireTenant(accessContext, ModelPermissions.ENTERPRISE_ROUTE_CONFIGURE);
        enterpriseAgentQuery.getManagedDetail(enterpriseAgentId, accessContext);
        return replaceRoute(
                "AGENT",
                accessContext.tenantId().value(),
                enterpriseAgentId,
                command,
                accessContext.actorId().value()
        );
    }

    @Override
    @Transactional(readOnly = true)
    public List<ModelDefinitionView> list(PlatformAccessContext accessContext) {
        requirePlatform(accessContext, ModelPermissions.PLATFORM_READ);
        return repository.listDefinitions(LIST_LIMIT);
    }

    @Override
    @Transactional(readOnly = true)
    public List<PlatformDefaultModelRouteView> listPlatformDefaults(PlatformAccessContext accessContext) {
        requirePlatform(accessContext, ModelPermissions.PLATFORM_READ);
        return repository.listActivePlatformDefaultRoutes();
    }

    private ModelCommandOutcome<ModelRouteBindingView> replaceRoute(
            String scopeType,
            UUID tenantId,
            UUID enterpriseAgentId,
            SetModelRouteCommand command,
            UUID actorId
    ) {
        var replay = repository.findRouteByIdempotency(actorId, command.idempotencyKey());
        if (replay.isPresent()) {
            requireSameRequest(replay.orElseThrow().requestHash(), command.requestHash());
            return new ModelCommandOutcome<>(replay.orElseThrow().binding(), true);
        }
        repository.findActiveDefinition(command.modelDefinitionId(), command.capabilityType())
                .orElseThrow(() -> new ModelCommandConflictException(
                        "MODEL_DEFINITION_NOT_ACTIVE",
                        "The selected model definition is not active for this capability"
                ));
        return new ModelCommandOutcome<>(repository.replaceRoute(
                scopeType,
                tenantId,
                enterpriseAgentId,
                command,
                actorId,
                clock.instant()
        ), false);
    }

    private static void requireSameRequest(String stored, String incoming) {
        if (!Objects.equals(stored, incoming)) {
            throw new ModelCommandConflictException(
                    "IDEMPOTENCY_REQUEST_CONFLICT",
                    "The idempotency key was already used with another model command"
            );
        }
    }

    private static void requirePlatform(PlatformAccessContext context, String permission) {
        Objects.requireNonNull(context, "accessContext must not be null");
        if (!context.authorities().contains(permission)) throw new ModelAccessDeniedException(permission);
    }

    private static void requireTenant(AccessContext context, String permission) {
        Objects.requireNonNull(context, "accessContext must not be null");
        if (!context.authorities().contains(permission)) throw new ModelAccessDeniedException(permission);
    }
}

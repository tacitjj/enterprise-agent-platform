package com.dianlian.platform.model.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.ModelDefinitionStatus;
import com.dianlian.platform.model.api.ModelDefinitionView;
import com.dianlian.platform.model.api.ModelRouteBindingView;
import com.dianlian.platform.model.api.ModelRoutePreference;
import com.dianlian.platform.model.api.ModelRouteUnavailableException;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class ModelRouteApplicationServiceTests {

    @Test
    void newResolutionRequiresAnActiveDefinition() {
        var repository = new TestModelRepository();
        var route = route(ModelDefinitionStatus.DISABLED);
        repository.resolvedRoute = Optional.of(route);

        var service = new ModelRouteApplicationService(repository);

        assertThatThrownBy(() -> service.resolve(
                route.binding().tenantId(),
                route.binding().enterpriseAgentId(),
                ModelCapabilityType.TEXT_CHAT,
                ModelRoutePreference.AGENT_THEN_PLATFORM
        )).isInstanceOf(ModelRouteUnavailableException.class);
    }

    @Test
    void historicalSnapshotCanReadADisabledDefinition() {
        var repository = new TestModelRepository();
        var route = route(ModelDefinitionStatus.DISABLED);
        repository.snapshotRoute = Optional.of(route);

        var resolved = new ModelRouteApplicationService(repository).requireSnapshot(
                route.binding().routeBindingId(),
                route.definition().modelDefinitionId()
        );

        assertThat(resolved.model().status()).isEqualTo(ModelDefinitionStatus.DISABLED);
    }

    private static ModelRepository.ResolvedRouteRecord route(ModelDefinitionStatus status) {
        var routeId = UUID.randomUUID();
        var tenantId = UUID.randomUUID();
        var agentId = UUID.randomUUID();
        var modelId = UUID.randomUUID();
        var actorId = UUID.randomUUID();
        var now = Instant.parse("2026-08-11T00:00:00Z");
        var binding = new ModelRouteBindingView(
                routeId,
                "AGENT",
                tenantId,
                agentId,
                ModelCapabilityType.TEXT_CHAT,
                modelId,
                1,
                "ACTIVE",
                actorId,
                now
        );
        var definition = new ModelDefinitionView(
                modelId,
                "TEXT_MODEL",
                1,
                "Text model",
                "PROVIDER",
                "OPENAI_COMPATIBLE",
                "https://api.example.com/v1",
                "provider-model",
                "env:DIANLIAN_MODEL_PROVIDER_KEY",
                ModelCapabilityType.TEXT_CHAT,
                new BigDecimal("0.2"),
                2_048,
                1,
                1,
                10,
                status,
                actorId,
                now
        );
        return new ModelRepository.ResolvedRouteRecord(binding, definition);
    }
}

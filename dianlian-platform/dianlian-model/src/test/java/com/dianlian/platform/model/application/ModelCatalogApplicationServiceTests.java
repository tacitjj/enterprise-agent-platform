package com.dianlian.platform.model.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.employee.api.EnterpriseAgentDetail;
import com.dianlian.platform.employee.api.EnterpriseAgentManagementQuery;
import com.dianlian.platform.employee.api.EnterpriseAgentSummary;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.ModelAccessDeniedException;
import com.dianlian.platform.model.api.ModelPermissions;
import com.dianlian.platform.model.api.PlatformDefaultModelRouteView;
import com.dianlian.platform.model.api.RegisterModelDefinitionCommand;
import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.Test;

class ModelCatalogApplicationServiceTests {

    @Test
    void validatesEndpointBeforeInsertingANewDefinition() {
        var repository = new TestModelRepository();
        var actorId = new ActorId(UUID.randomUUID());
        var accessContext = platformAccessContext(actorId, Set.of(ModelPermissions.PLATFORM_MANAGE));
        var endpointChecked = new AtomicBoolean();
        var command = command();
        var service = new ModelCatalogApplicationService(
                repository,
                new UnusedEnterpriseAgentQuery(),
                baseUrl -> {
                    endpointChecked.set(true);
                    throw new IllegalArgumentException("rejected");
                },
                Clock.systemUTC()
        );

        assertThatThrownBy(() -> service.register(command, accessContext))
                .isInstanceOf(IllegalArgumentException.class);
        assertThat(endpointChecked).isTrue();
        assertThat(repository.insertDefinitionCalled).isFalse();
    }

    @Test
    void listsOnlyTheRepositoryPlatformDefaultsWithPlatformReadPermission() {
        var repository = new TestModelRepository();
        var actorId = new ActorId(UUID.randomUUID());
        var route = new PlatformDefaultModelRouteView(
                ModelCapabilityType.TEXT_CHAT,
                UUID.randomUUID(),
                UUID.randomUUID(),
                2,
                "ACTIVE",
                Instant.parse("2026-08-11T01:00:00Z")
        );
        repository.platformDefaultRoutes = List.of(route);
        var service = service(repository);

        var result = service.listPlatformDefaults(
                platformAccessContext(actorId, Set.of(ModelPermissions.PLATFORM_READ))
        );

        assertThat(result).containsExactly(route);
        assertThat(repository.listPlatformDefaultRoutesCalled).isTrue();
    }

    @Test
    void platformManagePermissionDoesNotImplicitlyGrantCatalogRead() {
        var repository = new TestModelRepository();
        var service = service(repository);

        assertThatThrownBy(() -> service.listPlatformDefaults(platformAccessContext(
                new ActorId(UUID.randomUUID()),
                Set.of(ModelPermissions.PLATFORM_MANAGE)
        ))).isInstanceOf(ModelAccessDeniedException.class);
        assertThat(repository.listPlatformDefaultRoutesCalled).isFalse();
    }

    private static ModelCatalogApplicationService service(TestModelRepository repository) {
        return new ModelCatalogApplicationService(
                repository,
                new UnusedEnterpriseAgentQuery(),
                baseUrl -> {
                },
                Clock.systemUTC()
        );
    }

    private static PlatformAccessContext platformAccessContext(ActorId actorId, Set<String> permissions) {
        var now = Instant.parse("2026-08-11T00:00:00Z");
        var principal = new AuthenticatedPrincipal(
                UUID.randomUUID(),
                actorId,
                "Platform operator",
                null,
                SessionView.AccountStatus.ACTIVE,
                null,
                List.of(new SessionView.RoleGrant(
                        "PLATFORM_ADMIN",
                        SessionView.DataScopeType.PLATFORM,
                        UUID.randomUUID()
                )),
                permissions,
                "v1",
                now,
                now.plusSeconds(3_600)
        );
        return PlatformAccessContext.fromAuthenticatedPrincipal(principal);
    }

    private static RegisterModelDefinitionCommand command() {
        return new RegisterModelDefinitionCommand(
                "TEXT_MODEL",
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
                "idem-1",
                "request-hash"
        );
    }

    private static final class UnusedEnterpriseAgentQuery implements EnterpriseAgentManagementQuery {
        @Override
        public List<EnterpriseAgentSummary> listManaged(AccessContext accessContext) {
            throw new UnsupportedOperationException();
        }

        @Override
        public EnterpriseAgentDetail getManagedDetail(UUID enterpriseAgentId, AccessContext accessContext) {
            throw new UnsupportedOperationException();
        }
    }
}

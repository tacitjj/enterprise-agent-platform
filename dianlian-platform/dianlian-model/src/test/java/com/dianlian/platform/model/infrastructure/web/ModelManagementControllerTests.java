package com.dianlian.platform.model.infrastructure.web;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorContextPort;
import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.TenantId;
import com.dianlian.platform.model.api.ModelAccessDeniedException;
import com.dianlian.platform.model.api.ModelCatalogCommands;
import com.dianlian.platform.model.api.ModelCatalogQuery;
import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.ModelCommandOutcome;
import com.dianlian.platform.model.api.ModelDefinitionView;
import com.dianlian.platform.model.api.ModelPermissions;
import com.dianlian.platform.model.api.ModelRouteBindingView;
import com.dianlian.platform.model.api.PlatformDefaultModelRouteView;
import com.dianlian.platform.model.api.RegisterModelDefinitionCommand;
import com.dianlian.platform.model.api.SetModelRouteCommand;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;

class ModelManagementControllerTests {

    private static final Instant NOW = Instant.parse("2026-08-11T08:00:00Z");

    @Test
    void listsMinimalDefaultRouteProjectionWithoutCredentialFields() {
        var route = new PlatformDefaultModelRouteView(
                ModelCapabilityType.TEXT_CHAT,
                UUID.randomUUID(),
                UUID.randomUUID(),
                3,
                "ACTIVE",
                NOW
        );
        var query = new RecordingQuery(List.of(route));
        var controller = controller(platformPrincipal(), query);

        var response = controller.listPlatformDefaultRoutes();

        assertThat(response.getHeaders().getFirst(HttpHeaders.CACHE_CONTROL)).isEqualTo("no-store");
        assertThat(response.getBody().items()).containsExactly(route);
        assertThat(query.called).isTrue();
        assertThat(Arrays.stream(PlatformDefaultModelRouteView.class.getRecordComponents())
                .map(component -> component.getName())
                .collect(Collectors.toSet()))
                .containsExactlyInAnyOrder(
                        "capabilityType",
                        "modelDefinitionId",
                        "routeBindingId",
                        "stateVersion",
                        "status",
                        "createdAt"
                );
    }

    @Test
    void tenantSessionCannotReadPlatformDefaultsByCarryingPlatformPermission() {
        var query = new RecordingQuery(List.of());
        var controller = controller(tenantPrincipal(), query);

        assertThatThrownBy(controller::listPlatformDefaultRoutes)
                .isInstanceOf(ModelAccessDeniedException.class);
        assertThat(query.called).isFalse();
    }

    private static ModelManagementController controller(
            AuthenticatedPrincipal principal,
            ModelCatalogQuery query
    ) {
        ActorContextPort actorContextPort = () -> Optional.of(principal);
        return new ModelManagementController(
                actorContextPort,
                new UnusedCommands(),
                query,
                new ObjectMapper()
        );
    }

    private static AuthenticatedPrincipal platformPrincipal() {
        return principal(
                null,
                new SessionView.RoleGrant(
                        "PLATFORM_ADMIN",
                        SessionView.DataScopeType.PLATFORM,
                        UUID.randomUUID()
                )
        );
    }

    private static AuthenticatedPrincipal tenantPrincipal() {
        var tenantId = new TenantId(UUID.randomUUID());
        return principal(
                new SessionView.Tenant(
                        tenantId,
                        "Tenant",
                        SessionView.TenantStatus.ACTIVE,
                        SessionView.MembershipStatus.ACTIVE
                ),
                new SessionView.RoleGrant(
                        "TENANT_ADMIN",
                        SessionView.DataScopeType.TENANT,
                        tenantId.value()
                )
        );
    }

    private static AuthenticatedPrincipal principal(
            SessionView.Tenant activeTenant,
            SessionView.RoleGrant roleGrant
    ) {
        return new AuthenticatedPrincipal(
                UUID.randomUUID(),
                new ActorId(UUID.randomUUID()),
                "Operator",
                null,
                SessionView.AccountStatus.ACTIVE,
                activeTenant,
                List.of(roleGrant),
                Set.of(ModelPermissions.PLATFORM_READ),
                "v1",
                NOW,
                NOW.plusSeconds(3_600)
        );
    }

    private static final class RecordingQuery implements ModelCatalogQuery {
        private final List<PlatformDefaultModelRouteView> routes;
        private final AtomicBoolean called = new AtomicBoolean();

        private RecordingQuery(List<PlatformDefaultModelRouteView> routes) {
            this.routes = routes;
        }

        @Override
        public List<ModelDefinitionView> list(PlatformAccessContext accessContext) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<PlatformDefaultModelRouteView> listPlatformDefaults(PlatformAccessContext accessContext) {
            called.set(true);
            return routes;
        }
    }

    private static final class UnusedCommands implements ModelCatalogCommands {
        @Override
        public ModelCommandOutcome<ModelDefinitionView> register(
                RegisterModelDefinitionCommand command,
                PlatformAccessContext accessContext
        ) {
            throw new UnsupportedOperationException();
        }

        @Override
        public ModelCommandOutcome<ModelRouteBindingView> setPlatformDefault(
                SetModelRouteCommand command,
                PlatformAccessContext accessContext
        ) {
            throw new UnsupportedOperationException();
        }

        @Override
        public ModelCommandOutcome<ModelRouteBindingView> bindEnterpriseAgent(
                UUID enterpriseAgentId,
                SetModelRouteCommand command,
                AccessContext accessContext
        ) {
            throw new UnsupportedOperationException();
        }
    }
}

package com.dianlian.platform.employee.infrastructure.web;

import static org.assertj.core.api.Assertions.assertThat;

import com.dianlian.platform.employee.api.AgentTemplateCommands;
import com.dianlian.platform.employee.api.ActivateEnterpriseAgentCommand;
import com.dianlian.platform.employee.api.AgentVersionQuery;
import com.dianlian.platform.employee.api.AgentVersionStatus;
import com.dianlian.platform.employee.api.CommandOutcome;
import com.dianlian.platform.employee.api.CreateEnterpriseAgentConfigurationCommand;
import com.dianlian.platform.employee.api.EmployeePermissions;
import com.dianlian.platform.employee.api.EnterpriseAgentCommands;
import com.dianlian.platform.employee.api.EnterpriseAgentAllowedAction;
import com.dianlian.platform.employee.api.EnterpriseAgentDetail;
import com.dianlian.platform.employee.api.EnterpriseAgentManagementQuery;
import com.dianlian.platform.employee.api.EnterpriseAgentReadiness;
import com.dianlian.platform.employee.api.EnterpriseAgentReadinessBlocker;
import com.dianlian.platform.employee.api.EnterpriseAgentStatus;
import com.dianlian.platform.employee.api.EnterpriseAgentSummary;
import com.dianlian.platform.employee.api.EnterpriseAgentTemplateSnapshot;
import com.dianlian.platform.employee.api.EnterpriseVisibility;
import com.dianlian.platform.employee.api.ExecutionExecutorType;
import com.dianlian.platform.employee.api.ExecutionStepDescriptor;
import com.dianlian.platform.employee.api.ExecutionTemplateDescriptor;
import com.dianlian.platform.employee.api.HireEnterpriseAgentCommand;
import com.dianlian.platform.employee.api.InputSchemaDescriptor;
import com.dianlian.platform.employee.api.PublishAgentVersionCommand;
import com.dianlian.platform.employee.api.PublishedAgentVersion;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorContextPort;
import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import com.dianlian.platform.identity.api.PlatformAccessRequiredException;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.TenantId;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;

class EmployeeManagementControllerTests {

    private static final UUID ACTOR_ID = UUID.fromString("10000000-0000-4000-8000-000000000010");
    private static final UUID TENANT_ID = UUID.fromString("10000000-0000-4000-8000-000000000001");
    private static final UUID TEMPLATE_ID = UUID.fromString("10000000-0000-4000-8000-000000000101");
    private static final UUID VERSION_ID = UUID.fromString("10000000-0000-4000-8000-000000000111");
    private static final UUID AGENT_ID = UUID.fromString("10000000-0000-4000-8000-000000000121");
    private static final Instant NOW = Instant.parse("2026-08-11T04:00:00Z");

    @Test
    void platformListAndPublishUseTenantlessServerPrincipal() throws Exception {
        var principal = platformPrincipal();
        var ports = new RecordingPorts(principal);
        ports.publishedVersion = publishedVersion();
        var controller = ports.controller();

        var list = controller.listPublishedVersions();
        var published = controller.publishVersion(
                "publish:quotation:000001",
                publishRequest(ports.objectMapper)
        );

        assertThat(list.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(list.getHeaders().getCacheControl()).isEqualTo("no-store");
        assertThat(list.getBody().items()).singleElement()
                .extracting(EmployeeManagementController.AgentVersionView::agentVersionId)
                .isEqualTo(VERSION_ID);
        assertThat(published.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        assertThat(published.getHeaders().getFirst("Idempotency-Replayed")).isEqualTo("false");
        assertThat(published.getHeaders().containsKey(HttpHeaders.LOCATION)).isFalse();
        assertThat(ports.publishContext.actorId().value()).isEqualTo(ACTOR_ID);
        assertThat(ports.publishCommand.idempotencyKey()).isEqualTo("publish:quotation:000001");
        assertThat(ports.publishCommand.requestHash()).matches("[0-9a-f]{64}");
    }

    @Test
    void enterpriseHireDerivesTenantAndActorFromServerPrincipal() {
        var principal = enterprisePrincipal();
        var ports = new RecordingPorts(principal);
        ports.enterpriseAgent = enterpriseAgent();
        var controller = ports.controller();

        var list = controller.listEnterpriseAgents();
        var hired = controller.hireEnterpriseAgent(
                "hire:quotation:00000001",
                new EmployeeManagementController.HireEnterpriseAgentRequest(
                        VERSION_ID,
                        "DL-QUOTE-002",
                        "待配置报价员工"
                )
        );

        assertThat(list.getBody().items()).singleElement()
                .extracting(EmployeeManagementController.EnterpriseAgentView::enterpriseAgentId)
                .isEqualTo(AGENT_ID);
        assertThat(hired.getStatusCode()).isEqualTo(HttpStatus.CREATED);
        assertThat(ports.hireContext.tenantId().value()).isEqualTo(TENANT_ID);
        assertThat(ports.hireContext.actorId().value()).isEqualTo(ACTOR_ID);
        assertThat(hired.getBody().status()).isEqualTo("DRAFT");
        assertThat(hired.getBody().stateVersion()).isEqualTo("0");
        assertThat(ports.hireCommand.requestHash()).matches("[0-9a-f]{64}");
    }

    @Test
    void tenantSessionCannotBecomePlatformOperatorFromPermissionStringAlone() {
        var tenantPrincipal = principal(
                new SessionView.Tenant(
                        new TenantId(TENANT_ID),
                        "点联本地样板企业",
                        SessionView.TenantStatus.ACTIVE,
                        SessionView.MembershipStatus.ACTIVE
                ),
                Set.of(EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH)
        );

        var controller = new RecordingPorts(tenantPrincipal).controller();

        org.assertj.core.api.Assertions.assertThatThrownBy(controller::listPublishedVersions)
                .isInstanceOf(PlatformAccessRequiredException.class);
    }

    private static EmployeeManagementController.PublishAgentVersionRequest publishRequest(ObjectMapper mapper)
            throws Exception {
        return new EmployeeManagementController.PublishAgentVersionRequest(
                "quotation-specialist",
                "报价专员",
                "依据需求与确定性规则形成可复核报价",
                "1.1.0",
                "QUOTATION",
                new EmployeeManagementController.InputSchemaRequest(
                        "quotation.request",
                        "1.1.0",
                        mapper.readTree("{\"type\":\"object\",\"properties\":{}}")
                ),
                new EmployeeManagementController.ExecutionTemplateRequest(
                        "quotation.v1",
                        "1.1.0",
                        List.of(new EmployeeManagementController.ExecutionStepRequest(
                                "understand",
                                "理解需求",
                                ExecutionExecutorType.MODEL,
                                List.of(),
                                "quotation.request",
                                "quotation.normalized",
                                false
                        ))
                ),
                mapper.getNodeFactory().textNode("350000000"),
                new EmployeeManagementController.VisibilityRequest(
                        com.dianlian.platform.employee.api.EnterpriseVisibilityMode.ALL,
                        Set.of()
                )
        );
    }

    private static PublishedAgentVersion publishedVersion() {
        return new PublishedAgentVersion(
                TEMPLATE_ID,
                VERSION_ID,
                "quotation-specialist",
                "报价专员",
                "依据需求与确定性规则形成可复核报价",
                "1.0.0",
                "QUOTATION",
                new InputSchemaDescriptor(
                        "quotation.request",
                        "1.0.0",
                        "{\"type\":\"object\",\"additionalProperties\":false}"
                ),
                new ExecutionTemplateDescriptor(
                        "quotation.v1",
                        "1.0.0",
                        List.of(new ExecutionStepDescriptor(
                                "understand",
                                "理解需求",
                                ExecutionExecutorType.MODEL,
                                List.of(),
                                "quotation.request",
                                "quotation.normalized",
                                false
                        ))
                ),
                350_000_000L,
                AgentVersionStatus.PUBLISHED,
                EnterpriseVisibility.allEnterprises(),
                NOW
        );
    }

    private static EnterpriseAgentSummary enterpriseAgent() {
        return new EnterpriseAgentSummary(
                AGENT_ID,
                TENANT_ID,
                TEMPLATE_ID,
                VERSION_ID,
                "DL-QUOTE-001",
                "报价员工",
                "QUOTATION",
                EnterpriseAgentStatus.DRAFT,
                0,
                null,
                null,
                null,
                NOW
        );
    }

    private static EnterpriseAgentDetail enterpriseAgentDetail() {
        return new EnterpriseAgentDetail(
                enterpriseAgent(),
                new EnterpriseAgentTemplateSnapshot(
                        "报价专员",
                        "依据需求与确定性规则形成可复核报价",
                        "1.0.0",
                        AgentVersionStatus.PUBLISHED
                ),
                null,
                new EnterpriseAgentReadiness(
                        false,
                        List.of(new EnterpriseAgentReadinessBlocker(
                                "CONFIGURATION_REQUIRED",
                                "请先创建企业员工配置版本。"
                        ))
                ),
                Set.of(
                        EnterpriseAgentAllowedAction.VIEW,
                        EnterpriseAgentAllowedAction.CREATE_CONFIGURATION_VERSION
                )
        );
    }

    private static AuthenticatedPrincipal platformPrincipal() {
        return principal(null, Set.of(
                EmployeePermissions.PLATFORM_TEMPLATE_READ,
                EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH
        ));
    }

    private static AuthenticatedPrincipal enterprisePrincipal() {
        return principal(
                new SessionView.Tenant(
                        new TenantId(TENANT_ID),
                        "点联本地样板企业",
                        SessionView.TenantStatus.ACTIVE,
                        SessionView.MembershipStatus.ACTIVE
                ),
                Set.of(EmployeePermissions.ENTERPRISE_AGENT_HIRE, EmployeePermissions.ENTERPRISE_AGENT_READ)
        );
    }

    private static AuthenticatedPrincipal principal(SessionView.Tenant tenant, Set<String> permissions) {
        return new AuthenticatedPrincipal(
                UUID.fromString("90000000-0000-4000-8000-000000000001"),
                new ActorId(ACTOR_ID),
                "测试用户",
                null,
                SessionView.AccountStatus.ACTIVE,
                tenant,
                tenant == null
                        ? List.of(new SessionView.RoleGrant(
                                "PLATFORM_OPERATOR",
                                SessionView.DataScopeType.PLATFORM,
                                UUID.fromString("10000000-0000-0000-0000-000000000000")
                        ))
                        : List.of(),
                permissions,
                "permission-v1",
                NOW,
                NOW.plusSeconds(3600)
        );
    }

    private static final class RecordingPorts implements
            AgentTemplateCommands,
            AgentVersionQuery,
            EnterpriseAgentCommands,
            EnterpriseAgentManagementQuery {

        private final AuthenticatedPrincipal principal;
        private final ObjectMapper objectMapper = new ObjectMapper();
        private PublishedAgentVersion publishedVersion;
        private EnterpriseAgentSummary enterpriseAgent;
        private PublishAgentVersionCommand publishCommand;
        private PlatformAccessContext publishContext;
        private HireEnterpriseAgentCommand hireCommand;
        private AccessContext hireContext;

        private RecordingPorts(AuthenticatedPrincipal principal) {
            this.principal = principal;
        }

        private EmployeeManagementController controller() {
            ActorContextPort actorContext = () -> Optional.of(principal);
            return new EmployeeManagementController(
                    actorContext,
                    this,
                    this,
                    this,
                    this,
                    objectMapper
            );
        }

        @Override
        public CommandOutcome<PublishedAgentVersion> publishVersion(
                PublishAgentVersionCommand command,
                PlatformAccessContext accessContext
        ) {
            this.publishCommand = command;
            this.publishContext = accessContext;
            return new CommandOutcome<>(publishedVersion, false);
        }

        @Override
        public List<PublishedAgentVersion> listPublished(PlatformAccessContext accessContext) {
            return List.of(publishedVersion);
        }

        @Override
        public List<PublishedAgentVersion> listRecruitable(AccessContext accessContext) {
            return List.of(publishedVersion);
        }

        @Override
        public CommandOutcome<EnterpriseAgentSummary> hire(
                HireEnterpriseAgentCommand command,
                AccessContext accessContext
        ) {
            this.hireCommand = command;
            this.hireContext = accessContext;
            return new CommandOutcome<>(enterpriseAgent, false);
        }

        @Override
        public CommandOutcome<EnterpriseAgentDetail> createConfigurationVersion(
                CreateEnterpriseAgentConfigurationCommand command,
                AccessContext accessContext
        ) {
            return new CommandOutcome<>(enterpriseAgentDetail(), false);
        }

        @Override
        public CommandOutcome<EnterpriseAgentDetail> activate(
                ActivateEnterpriseAgentCommand command,
                AccessContext accessContext
        ) {
            return new CommandOutcome<>(enterpriseAgentDetail(), false);
        }

        @Override
        public List<EnterpriseAgentSummary> listManaged(AccessContext accessContext) {
            return List.of(enterpriseAgent);
        }

        @Override
        public EnterpriseAgentDetail getManagedDetail(UUID enterpriseAgentId, AccessContext accessContext) {
            return enterpriseAgentDetail();
        }
    }
}

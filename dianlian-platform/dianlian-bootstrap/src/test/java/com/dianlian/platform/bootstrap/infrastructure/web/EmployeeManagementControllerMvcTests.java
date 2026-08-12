package com.dianlian.platform.bootstrap.infrastructure.web;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import cn.dev33.satoken.stp.StpLogic;
import com.dianlian.platform.bootstrap.infrastructure.config.SaTokenWebMvcConfiguration;
import com.dianlian.platform.bootstrap.infrastructure.security.ApiSecurityProblemWriter;
import com.dianlian.platform.bootstrap.infrastructure.security.DianlianPrincipalContext;
import com.dianlian.platform.bootstrap.infrastructure.security.SaTokenActorContextAdapter;
import com.dianlian.platform.bootstrap.infrastructure.security.SaTokenAuthenticationInterceptor;
import com.dianlian.platform.employee.api.AgentVersionStatus;
import com.dianlian.platform.employee.api.EmployeePermissions;
import com.dianlian.platform.employee.api.EnterpriseAgentStatus;
import com.dianlian.platform.employee.api.EnterpriseAgentSummary;
import com.dianlian.platform.employee.api.EnterpriseVisibility;
import com.dianlian.platform.employee.api.ExecutableAgentSummary;
import com.dianlian.platform.employee.api.ExecutionExecutorType;
import com.dianlian.platform.employee.api.ExecutionStepDescriptor;
import com.dianlian.platform.employee.api.ExecutionTemplateDescriptor;
import com.dianlian.platform.employee.api.InputSchemaDescriptor;
import com.dianlian.platform.employee.application.EmployeeApplicationService;
import com.dianlian.platform.employee.application.EmployeeRepository;
import com.dianlian.platform.employee.domain.AgentTemplate;
import com.dianlian.platform.employee.domain.AgentVersion;
import com.dianlian.platform.employee.domain.EnterpriseAgent;
import com.dianlian.platform.employee.domain.EnterpriseAgentConfigurationVersion;
import com.dianlian.platform.employee.domain.EnterpriseAgentStateEvent;
import com.dianlian.platform.employee.infrastructure.web.EmployeeManagementController;
import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.SessionAuthenticationPort;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.TenantId;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestExecutionListeners;
import org.springframework.test.context.support.DependencyInjectionTestExecutionListener;
import org.springframework.test.context.web.ServletTestExecutionListener;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(controllers = EmployeeManagementController.class)
@TestExecutionListeners(
        listeners = {ServletTestExecutionListener.class, DependencyInjectionTestExecutionListener.class},
        mergeMode = TestExecutionListeners.MergeMode.REPLACE_DEFAULTS
)
@Import({
        SaTokenWebMvcConfiguration.class,
        SaTokenAuthenticationInterceptor.class,
        DianlianPrincipalContext.class,
        ApiSecurityProblemWriter.class,
        SaTokenActorContextAdapter.class,
        EmployeeManagementProblemHandler.class,
        EmployeeManagementControllerMvcTests.TestDoubles.class
})
class EmployeeManagementControllerMvcTests {

    private static final String ACCESS_TOKEN = "test-platform-jwt-access-token";
    private static final String IDEMPOTENCY_KEY = "publish:contract:000001";
    private static final UUID SESSION_ID = UUID.fromString("10000000-0000-4000-8000-000000000001");
    private static final UUID ACTOR_ID = UUID.fromString("20000000-0000-4000-8000-000000000001");
    private static final UUID TENANT_ID = UUID.fromString("30000000-0000-4000-8000-000000000001");
    private static final UUID PLATFORM_SCOPE_ID = UUID.fromString("40000000-0000-4000-8000-000000000001");
    private static final UUID TEMPLATE_ID = UUID.fromString("50000000-0000-4000-8000-000000000001");
    private static final UUID VERSION_ID = UUID.fromString("60000000-0000-4000-8000-000000000001");
    private static final Instant AUTHENTICATED_AT = Instant.parse("2026-08-11T00:00:00Z");

    private final MockMvc mockMvc;
    private final ObjectMapper objectMapper;
    private final TestStpLogic stpLogic;
    private final MutableSessionAuthenticationPort sessionAuthenticationPort;
    private final RecordingEmployeeRepository employeeRepository;

    @Autowired
    EmployeeManagementControllerMvcTests(
            MockMvc mockMvc,
            ObjectMapper objectMapper,
            TestStpLogic stpLogic,
            MutableSessionAuthenticationPort sessionAuthenticationPort,
            RecordingEmployeeRepository employeeRepository
    ) {
        this.mockMvc = mockMvc;
        this.objectMapper = objectMapper;
        this.stpLogic = stpLogic;
        this.sessionAuthenticationPort = sessionAuthenticationPort;
        this.employeeRepository = employeeRepository;
    }

    @BeforeEach
    void resetTestDoubles() {
        sessionAuthenticationPort.principal = null;
        employeeRepository.reset();
    }

    @Test
    void enterpriseSessionCannotAccessPlatformEndpointsEvenWithPlatformPermissionStrings() throws Exception {
        stubAuthenticatedPrincipal(enterprisePrincipal(Set.of(
                EmployeePermissions.PLATFORM_TEMPLATE_READ,
                EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH
        )));

        mockMvc.perform(get("/api/v1/platform/agent-versions")
                        .header("Authorization", "Bearer " + ACCESS_TOKEN))
                .andExpect(status().isForbidden())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("PLATFORM_ACCESS_REQUIRED"));

        mockMvc.perform(post("/api/v1/platform/agent-versions")
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("Idempotency-Key", IDEMPOTENCY_KEY)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(publishRequest("350000000", false)))
                .andExpect(status().isForbidden())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("PLATFORM_ACCESS_REQUIRED"));

        assertThat(employeeRepository.interactionCount).isZero();
    }

    @Test
    void tenantlessPlatformReadPermissionCanListButCannotPublish() throws Exception {
        stubAuthenticatedPrincipal(platformPrincipal(Set.of(EmployeePermissions.PLATFORM_TEMPLATE_READ)));
        employeeRepository.publishedVersions = List.of(agentVersion());

        mockMvc.perform(get("/api/v1/platform/agent-versions")
                        .header("Authorization", "Bearer " + ACCESS_TOKEN))
                .andExpect(status().isOk())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.items[0].agentVersionId").value(VERSION_ID.toString()))
                .andExpect(jsonPath("$.items[0].pointEstimateMicroCredit").value("350000000"));

        assertThat(employeeRepository.listPublishedCalls).isEqualTo(1);
        employeeRepository.reset();

        mockMvc.perform(post("/api/v1/platform/agent-versions")
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("Idempotency-Key", IDEMPOTENCY_KEY)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(publishRequest("350000000", false)))
                .andExpect(status().isForbidden())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("EMPLOYEE_MANAGEMENT_ACCESS_DENIED"));

        assertThat(employeeRepository.interactionCount).isZero();
    }

    @Test
    void tenantlessPlatformPublishPermissionAcceptsStringPointsAndPassesIdempotencyKey() throws Exception {
        stubAuthenticatedPrincipal(platformPrincipal(Set.of(EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH)));
        mockMvc.perform(post("/api/v1/platform/agent-versions")
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("Idempotency-Key", IDEMPOTENCY_KEY)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(publishRequest("350000000", false)))
                .andExpect(status().isCreated())
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(header().string("Idempotency-Replayed", "false"))
                .andExpect(jsonPath("$.pointEstimateMicroCredit").value("350000000"));

        assertThat(employeeRepository.insertedVersion).isNotNull();
        assertThat(employeeRepository.insertedVersion.pointEstimate()).isEqualTo(350_000_000L);
        assertThat(employeeRepository.insertedVersion.publishIdempotencyKey()).isEqualTo(IDEMPOTENCY_KEY);
        assertThat(employeeRepository.insertedVersion.requestHash()).matches("[0-9a-f]{64}");
    }

    @Test
    void platformPublishRejectsNumericPointValueBeforeApplicationService() throws Exception {
        stubAuthenticatedPrincipal(platformPrincipal(Set.of(EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH)));

        mockMvc.perform(post("/api/v1/platform/agent-versions")
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("Idempotency-Key", IDEMPOTENCY_KEY)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(publishRequest(350_000_000L, false)))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

        assertThat(employeeRepository.interactionCount).isZero();
    }

    @Test
    void platformPublishRejectsUnknownRequestFieldsBeforeApplicationService() throws Exception {
        stubAuthenticatedPrincipal(platformPrincipal(Set.of(EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH)));

        mockMvc.perform(post("/api/v1/platform/agent-versions")
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("Idempotency-Key", IDEMPOTENCY_KEY)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(publishRequest("350000000", true)))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

        assertThat(employeeRepository.interactionCount).isZero();
    }

    @Test
    void enterpriseEmployeeDetailAndCommandsExposeStrongPreconditionContract() throws Exception {
        stubAuthenticatedPrincipal(enterprisePrincipal(Set.of(
                EmployeePermissions.ENTERPRISE_AGENT_READ,
                EmployeePermissions.ENTERPRISE_AGENT_CONFIGURE,
                EmployeePermissions.ENTERPRISE_AGENT_ACTIVATE
        )));
        employeeRepository.enterpriseAgent = draftEnterpriseAgent();
        employeeRepository.agentVersion = agentVersion();

        mockMvc.perform(get("/api/v1/enterprise/agents/{enterpriseAgentId}", VERSION_ID)
                        .header("Authorization", "Bearer " + ACCESS_TOKEN))
                .andExpect(status().isOk())
                .andExpect(header().string("ETag", "\"ea-0\""))
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.status").value("DRAFT"))
                .andExpect(jsonPath("$.stateVersion").value("0"));

        employeeRepository.reset();
        mockMvc.perform(post("/api/v1/enterprise/agents/{enterpriseAgentId}/configuration-versions", VERSION_ID)
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("Idempotency-Key", "configure:contract:000001")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(configurationRequest()))
                .andExpect(status().isPreconditionRequired())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("EMPLOYEE_IF_MATCH_REQUIRED"))
                .andExpect(jsonPath("$.action").value("REFRESH_RESOURCE"));
        assertThat(employeeRepository.interactionCount).isZero();

        mockMvc.perform(post("/api/v1/enterprise/agents/{enterpriseAgentId}/activate", VERSION_ID)
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("If-Match", "\"ea-0\"")
                        .header("Idempotency-Key", "activate:contract:000001")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
        assertThat(employeeRepository.interactionCount).isZero();

        mockMvc.perform(post("/api/v1/enterprise/agents/{enterpriseAgentId}/configuration-versions", VERSION_ID)
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("If-Match", "\"ea-0\"")
                        .header("Idempotency-Key", "configure:contract:000003")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("null"))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
        assertThat(employeeRepository.interactionCount).isZero();

        employeeRepository.enterpriseAgent = draftEnterpriseAgent();
        mockMvc.perform(post("/api/v1/enterprise/agents/{enterpriseAgentId}/configuration-versions", VERSION_ID)
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("If-Match", "\"ea-9\"")
                        .header("Idempotency-Key", "configure:contract:000002")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(configurationRequest()))
                .andExpect(status().isPreconditionFailed())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("EMPLOYEE_STATE_VERSION_MISMATCH"))
                .andExpect(jsonPath("$.action").value("REFRESH_RESOURCE"));
    }

    private void stubAuthenticatedPrincipal(AuthenticatedPrincipal principal) {
        sessionAuthenticationPort.principal = principal;
    }

    private byte[] publishRequest(Object pointEstimateMicroCredit, boolean includeUnknownField) throws Exception {
        var request = new LinkedHashMap<String, Object>();
        request.put("templateCode", "quotation-specialist");
        request.put("templateName", "报价专员");
        request.put("templateDescription", "依据需求与确定性规则形成可复核报价");
        request.put("version", "1.1.0");
        request.put("capabilityCode", "QUOTATION");
        request.put("inputSchema", Map.of(
                "schemaId", "quotation.request",
                "schemaVersion", "1.1.0",
                "jsonSchema", Map.of("type", "object", "additionalProperties", false)
        ));
        request.put("executionTemplate", Map.of(
                "templateCode", "quotation.v1",
                "version", "1.1.0",
                "steps", List.of(Map.of(
                        "stepKey", "understand",
                        "title", "理解需求",
                        "executorType", "MODEL",
                        "dependsOn", List.of(),
                        "inputSchemaRef", "quotation.request",
                        "outputSchemaRef", "quotation.normalized",
                        "humanCheckpoint", false
                ))
        ));
        request.put("pointEstimateMicroCredit", pointEstimateMicroCredit);
        request.put("enterpriseVisibility", Map.of("mode", "ALL", "tenantIds", List.of()));
        if (includeUnknownField) {
            request.put("tenantId", TENANT_ID);
        }
        return objectMapper.writeValueAsBytes(request);
    }

    private byte[] configurationRequest() throws Exception {
        return objectMapper.writeValueAsBytes(Map.of(
                "displayNameSnapshot", "企业报价专员",
                "profile", "按企业规范形成可复核成果",
                "enterpriseInstructions", "仅使用当前企业授权数据。",
                "modelPolicyMode", "PLATFORM_DEFAULT",
                "knowledgeScopeMode", "NONE",
                "visibilityScope", "TENANT"
        ));
    }

    private static AgentVersion agentVersion() {
        return new AgentVersion(
                VERSION_ID,
                TEMPLATE_ID,
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
                "9".repeat(64),
                "publish:contract:existing",
                ACTOR_ID,
                AUTHENTICATED_AT
        );
    }

    private static EnterpriseAgent draftEnterpriseAgent() {
        return new EnterpriseAgent(
                VERSION_ID,
                TENANT_ID,
                TEMPLATE_ID,
                VERSION_ID,
                "DL-QUOTE-001",
                "待配置报价专员",
                "QUOTATION",
                EnterpriseAgentStatus.DRAFT,
                0,
                null,
                null,
                null,
                "hire-request-hash",
                "hire:contract:000001",
                ACTOR_ID,
                AUTHENTICATED_AT
        );
    }

    private static AuthenticatedPrincipal platformPrincipal(Set<String> permissions) {
        return principal(
                null,
                List.of(new SessionView.RoleGrant(
                        "PLATFORM_OPERATOR",
                        SessionView.DataScopeType.PLATFORM,
                        PLATFORM_SCOPE_ID
                )),
                permissions
        );
    }

    private static AuthenticatedPrincipal enterprisePrincipal(Set<String> permissions) {
        var tenant = new SessionView.Tenant(
                new TenantId(TENANT_ID),
                "测试企业",
                SessionView.TenantStatus.ACTIVE,
                SessionView.MembershipStatus.ACTIVE
        );
        return principal(
                tenant,
                List.of(new SessionView.RoleGrant(
                        "ENTERPRISE_OPERATOR",
                        SessionView.DataScopeType.TENANT,
                        TENANT_ID
                )),
                permissions
        );
    }

    private static AuthenticatedPrincipal principal(
            SessionView.Tenant activeTenant,
            List<SessionView.RoleGrant> roleGrants,
            Set<String> permissions
    ) {
        return new AuthenticatedPrincipal(
                SESSION_ID,
                new ActorId(ACTOR_ID),
                "测试用户",
                null,
                SessionView.AccountStatus.ACTIVE,
                activeTenant,
                roleGrants,
                permissions,
                "test-permissions-v1",
                AUTHENTICATED_AT,
                AUTHENTICATED_AT.plusSeconds(3600)
        );
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class TestDoubles {

        @Bean
        MutableSessionAuthenticationPort sessionAuthenticationPort() {
            return new MutableSessionAuthenticationPort();
        }

        @Bean
        TestStpLogic stpLogic() {
            return new TestStpLogic();
        }

        @Bean
        RecordingEmployeeRepository employeeRepository() {
            return new RecordingEmployeeRepository();
        }

        @Bean
        EmployeeApplicationService employeeApplicationService(
                EmployeeRepository employeeRepository,
                ObjectMapper objectMapper
        ) {
            return new EmployeeApplicationService(employeeRepository, objectMapper);
        }
    }

    private static final class TestStpLogic extends StpLogic {

        private TestStpLogic() {
            super("dianlian-employee-management-mvc-test");
        }

        @Override
        public void checkLogin() {
        }

        @Override
        public Object getExtra(String key) {
            return "sid".equals(key) ? SESSION_ID.toString() : null;
        }

        @Override
        public String getTokenValue() {
            return ACCESS_TOKEN;
        }

        @Override
        public String getLoginIdAsString() {
            return ACTOR_ID.toString();
        }
    }

    private static final class MutableSessionAuthenticationPort implements SessionAuthenticationPort {

        private AuthenticatedPrincipal principal;

        @Override
        public Optional<AuthenticatedPrincipal> authenticate(UUID sessionId, Instant observedAt) {
            if (!SESSION_ID.equals(sessionId)) {
                return Optional.empty();
            }
            return Optional.ofNullable(principal);
        }
    }

    private static final class RecordingEmployeeRepository implements EmployeeRepository {

        private int interactionCount;
        private int listPublishedCalls;
        private List<AgentVersion> publishedVersions = List.of();
        private AgentVersion insertedVersion;
        private AgentVersion agentVersion;
        private EnterpriseAgent enterpriseAgent;

        private void reset() {
            interactionCount = 0;
            listPublishedCalls = 0;
            publishedVersions = List.of();
            insertedVersion = null;
            agentVersion = null;
            enterpriseAgent = null;
        }

        @Override
        public Optional<AgentVersion> findVersionByIdempotency(UUID actorId, String idempotencyKey) {
            interactionCount++;
            return Optional.empty();
        }

        @Override
        public AgentTemplate getOrCreateTemplate(AgentTemplate proposedTemplate) {
            interactionCount++;
            return proposedTemplate;
        }

        @Override
        public Optional<AgentVersion> findVersionByTemplateAndLabel(UUID templateId, String version) {
            interactionCount++;
            return Optional.empty();
        }

        @Override
        public boolean insertVersionIfAbsent(AgentVersion version) {
            interactionCount++;
            insertedVersion = version;
            return true;
        }

        @Override
        public List<AgentVersion> listPublishedVersions(int limit) {
            interactionCount++;
            listPublishedCalls++;
            return publishedVersions;
        }

        @Override
        public List<AgentVersion> listRecruitableVersions(UUID enterpriseTenantId, int limit) {
            interactionCount++;
            return List.of();
        }

        @Override
        public Optional<AgentVersion> findRecruitableVersion(UUID agentVersionId, UUID enterpriseTenantId) {
            interactionCount++;
            return Optional.empty();
        }

        @Override
        public Optional<AgentVersion> lockRecruitableVersion(UUID agentVersionId, UUID enterpriseTenantId) {
            interactionCount++;
            return Optional.empty();
        }

        @Override
        public Optional<AgentVersion> findVersion(UUID agentVersionId) {
            interactionCount++;
            return Optional.ofNullable(agentVersion)
                    .filter(version -> version.agentVersionId().equals(agentVersionId));
        }

        @Override
        public Optional<EnterpriseAgent> findAgentByIdempotency(
                UUID tenantId,
                UUID actorId,
                String idempotencyKey
        ) {
            interactionCount++;
            return Optional.empty();
        }

        @Override
        public boolean insertAgentIfAbsent(EnterpriseAgent agent) {
            interactionCount++;
            return true;
        }

        @Override
        public boolean existsAgentByCode(UUID tenantId, String employeeCode) {
            interactionCount++;
            return false;
        }

        @Override
        public Optional<EnterpriseAgent> findAgent(UUID tenantId, UUID enterpriseAgentId) {
            interactionCount++;
            return Optional.ofNullable(enterpriseAgent)
                    .filter(agent -> agent.tenantId().equals(tenantId))
                    .filter(agent -> agent.enterpriseAgentId().equals(enterpriseAgentId));
        }

        @Override
        public Optional<EnterpriseAgent> lockAgent(UUID tenantId, UUID enterpriseAgentId) {
            interactionCount++;
            return findAgent(tenantId, enterpriseAgentId);
        }

        @Override
        public Optional<EnterpriseAgentConfigurationVersion> findConfigurationByCreateIdempotency(
                UUID tenantId,
                UUID actorId,
                String idempotencyKey
        ) {
            interactionCount++;
            return Optional.empty();
        }

        @Override
        public Optional<EnterpriseAgentConfigurationVersion> findConfigurationByActivationIdempotency(
                UUID tenantId,
                UUID actorId,
                String idempotencyKey
        ) {
            interactionCount++;
            return Optional.empty();
        }

        @Override
        public Optional<EnterpriseAgentConfigurationVersion> findConfiguration(
                UUID tenantId,
                UUID enterpriseAgentId,
                UUID configurationVersionId
        ) {
            interactionCount++;
            return Optional.empty();
        }

        @Override
        public Optional<EnterpriseAgentConfigurationVersion> findLatestConfiguration(
                UUID tenantId,
                UUID enterpriseAgentId
        ) {
            interactionCount++;
            return Optional.empty();
        }

        @Override
        public long nextConfigurationRevision(UUID tenantId, UUID enterpriseAgentId) {
            interactionCount++;
            return 1;
        }

        @Override
        public boolean insertConfigurationIfAbsent(EnterpriseAgentConfigurationVersion configuration) {
            interactionCount++;
            return false;
        }

        @Override
        public void supersedeOtherDraftConfigurations(
                UUID tenantId,
                UUID enterpriseAgentId,
                UUID retainedConfigurationVersionId,
                Instant now
        ) {
            interactionCount++;
        }

        @Override
        public boolean advanceAgentConfigurationState(
                UUID tenantId,
                UUID enterpriseAgentId,
                long expectedStateVersion,
                Instant now
        ) {
            interactionCount++;
            return false;
        }

        @Override
        public boolean activateConfiguration(
                UUID tenantId,
                UUID enterpriseAgentId,
                UUID configurationVersionId,
                UUID actorId,
                String requestHash,
                String idempotencyKey,
                long activationResultStateVersion,
                Instant now
        ) {
            interactionCount++;
            return false;
        }

        @Override
        public boolean activateAgent(
                UUID tenantId,
                UUID enterpriseAgentId,
                UUID configurationVersionId,
                String displayName,
                UUID actorId,
                long expectedStateVersion,
                Instant now
        ) {
            interactionCount++;
            return false;
        }

        @Override
        public void insertStateEvent(EnterpriseAgentStateEvent event) {
            interactionCount++;
        }

        @Override
        public List<EnterpriseAgentSummary> listManagedAgents(UUID tenantId, int limit) {
            interactionCount++;
            return List.of();
        }

        @Override
        public Optional<ExecutableAgentSummary> findExecutableAgent(UUID tenantId, UUID enterpriseAgentId) {
            interactionCount++;
            return Optional.empty();
        }

        @Override
        public List<ExecutableAgentSummary> listExecutableAgents(UUID tenantId, int limit) {
            interactionCount++;
            return List.of();
        }
    }
}

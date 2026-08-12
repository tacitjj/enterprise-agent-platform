package com.dianlian.platform.employee.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.employee.api.EmployeePermissions;
import com.dianlian.platform.employee.api.ActivateEnterpriseAgentCommand;
import com.dianlian.platform.employee.api.CreateEnterpriseAgentConfigurationCommand;
import com.dianlian.platform.employee.api.EmployeeCommandConflictException;
import com.dianlian.platform.employee.api.EnterpriseAgentKnowledgeScopeMode;
import com.dianlian.platform.employee.api.EnterpriseAgentModelPolicyMode;
import com.dianlian.platform.employee.api.EnterpriseAgentVisibilityScope;
import com.dianlian.platform.employee.api.EnterpriseVisibility;
import com.dianlian.platform.employee.api.ExecutionExecutorType;
import com.dianlian.platform.employee.api.ExecutionStepDescriptor;
import com.dianlian.platform.employee.api.ExecutionTemplateDescriptor;
import com.dianlian.platform.employee.api.HireEnterpriseAgentCommand;
import com.dianlian.platform.employee.api.InputSchemaDescriptor;
import com.dianlian.platform.employee.api.PublishAgentVersionCommand;
import com.dianlian.platform.employee.application.EmployeeApplicationService;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.TenantId;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.postgresql.ds.PGSimpleDataSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.simple.JdbcClient;

class JdbcEmployeeRepositoryIntegrationTests {

    private static final UUID PLATFORM_ACTOR = UUID.fromString("10000000-0000-4000-8000-000000000010");
    private static final UUID ENTERPRISE_TENANT = UUID.fromString("10000000-0000-4000-8000-000000000001");
    private static final UUID ENTERPRISE_ACTOR = UUID.fromString("10000000-0000-4000-8000-000000000011");

    @Test
    void publishHireAndReadExecutionProfileThroughPostgres() {
        String jdbcUrl = System.getProperty("dianlian.employee.jdbc.url", "");
        Assumptions.assumeTrue(!jdbcUrl.isBlank(), "PostgreSQL integration URL was not supplied");

        var dataSource = new PGSimpleDataSource();
        dataSource.setURL(jdbcUrl);
        dataSource.setUser(System.getProperty("dianlian.employee.jdbc.user", "dianlian_app"));
        dataSource.setPassword(System.getProperty("dianlian.employee.jdbc.password", ""));
        var repository = new JdbcEmployeeRepository(
                JdbcClient.create(new JdbcTemplate(dataSource)),
                new ObjectMapper()
        );
        var service = new EmployeeApplicationService(repository, new ObjectMapper());
        String suffix = UUID.randomUUID().toString().substring(0, 8);

        var published = service.publishVersion(
                new PublishAgentVersionCommand(
                        "jdbc-template-" + suffix,
                        "通用业务专员",
                        "验证 JDBC 发布、招聘和办公室读取链路",
                        "1.0.0",
                        "GENERIC_TASK",
                        new InputSchemaDescriptor(
                                "generic.task.input",
                                "1.0.0",
                                "{\"type\":\"object\"}"
                        ),
                        new ExecutionTemplateDescriptor(
                                "generic.task.flow",
                                "1.0.0",
                                List.of(new ExecutionStepDescriptor(
                                        "prepare",
                                        "准备",
                                        ExecutionExecutorType.MODEL,
                                        List.of(),
                                        "generic.task.input",
                                        "generic.task.output",
                                        false
                                ))
                        ),
                        40,
                        EnterpriseVisibility.allowlist(Set.of(ENTERPRISE_TENANT)),
                        "publish-" + suffix,
                        "sha256:publish-" + suffix
                ),
                PlatformAccessContext.fromAuthenticatedPrincipal(platformPrincipal())
        );

        AccessContext enterpriseContext = AccessContext.fromAuthenticatedPrincipal(enterprisePrincipal());
        var hired = service.hire(
                new HireEnterpriseAgentCommand(
                        published.resource().agentVersionId(),
                        "jdbc-agent-" + suffix,
                        "JDBC 专员",
                        "hire-" + suffix,
                        "sha256:hire-" + suffix
                ),
                enterpriseContext
        );
        var hireReplay = service.hire(
                new HireEnterpriseAgentCommand(
                        published.resource().agentVersionId(),
                        "jdbc-agent-" + suffix,
                        "JDBC 专员",
                        "hire-" + suffix,
                        "sha256:hire-" + suffix
                ),
                enterpriseContext
        );
        var configured = service.createConfigurationVersion(
                new CreateEnterpriseAgentConfigurationCommand(
                        hired.resource().enterpriseAgentId(),
                        hired.resource().stateVersion(),
                        "JDBC 专员",
                        "验证 JDBC 发布、招聘、配置、激活和办公室读取链路",
                        "仅使用当前企业授权数据。",
                        EnterpriseAgentModelPolicyMode.PLATFORM_DEFAULT,
                        EnterpriseAgentKnowledgeScopeMode.NONE,
                        EnterpriseAgentVisibilityScope.TENANT,
                        "configure-" + suffix,
                        "sha256:configure-" + suffix
                ),
                enterpriseContext
        );
        service.activate(
                new ActivateEnterpriseAgentCommand(
                        hired.resource().enterpriseAgentId(),
                        configured.resource().latestConfiguration().configurationVersionId(),
                        configured.resource().agent().stateVersion(),
                        "activate-" + suffix,
                        "sha256:activate-" + suffix
                ),
                enterpriseContext
        );

        var officeAgents = service.listExecutableForOffice(enterpriseContext);
        var executionProfile = service.requireExecutableForTask(
                hired.resource().enterpriseAgentId(),
                enterpriseContext
        );

        assertThat(published.replayed()).isFalse();
        assertThat(hireReplay.replayed()).isTrue();
        assertThat(officeAgents)
                .extracting(profile -> profile.enterpriseAgentId())
                .contains(hired.resource().enterpriseAgentId());
        assertThat(executionProfile.roleName()).isEqualTo("通用业务专员");
        assertThat(executionProfile.profile()).isEqualTo("验证 JDBC 发布、招聘、配置、激活和办公室读取链路");
        assertThat(executionProfile.enterpriseInstructions()).isEqualTo("仅使用当前企业授权数据。");
        assertThat(executionProfile.inputSchema().schemaId()).isEqualTo("generic.task.input");
        assertThat(executionProfile.executionTemplate().steps()).hasSize(1);
        assertThat(executionProfile.pointEstimate()).isEqualTo(40);
    }

    @Test
    void retiredVersionBlocksConfigurationAndActivationBeforeStateMutationThroughPostgres() {
        String jdbcUrl = System.getProperty("dianlian.employee.jdbc.url", "");
        Assumptions.assumeTrue(!jdbcUrl.isBlank(), "PostgreSQL integration URL was not supplied");

        var dataSource = new PGSimpleDataSource();
        dataSource.setURL(jdbcUrl);
        dataSource.setUser(System.getProperty("dianlian.employee.jdbc.user", "dianlian_app"));
        dataSource.setPassword(System.getProperty("dianlian.employee.jdbc.password", ""));
        var jdbcTemplate = new JdbcTemplate(dataSource);
        var service = new EmployeeApplicationService(
                new JdbcEmployeeRepository(JdbcClient.create(jdbcTemplate), new ObjectMapper()),
                new ObjectMapper()
        );
        AccessContext enterpriseContext = AccessContext.fromAuthenticatedPrincipal(enterprisePrincipal());
        String suffix = UUID.randomUUID().toString().substring(0, 8);

        var versionRetiredBeforeConfiguration = service.publishVersion(
                publishCommand("retired-before-config-" + suffix),
                PlatformAccessContext.fromAuthenticatedPrincipal(platformPrincipal())
        ).resource();
        var unconfiguredAgent = service.hire(
                new HireEnterpriseAgentCommand(
                        versionRetiredBeforeConfiguration.agentVersionId(),
                        "retired-config-" + suffix,
                        "待配置退休版本专员",
                        "hire-retired-config-" + suffix,
                        "sha256:hire-retired-config-" + suffix
                ),
                enterpriseContext
        ).resource();
        retireVersion(jdbcTemplate, versionRetiredBeforeConfiguration.agentVersionId());

        assertThatThrownBy(() -> service.createConfigurationVersion(
                configurationCommand(
                        unconfiguredAgent.enterpriseAgentId(),
                        unconfiguredAgent.stateVersion(),
                        "configure-retired-" + suffix
                ),
                enterpriseContext
        )).isInstanceOf(EmployeeCommandConflictException.class)
                .extracting("code")
                .isEqualTo("AGENT_VERSION_NOT_PUBLISHED");
        assertAgentState(jdbcTemplate, unconfiguredAgent.enterpriseAgentId(), 0, "DRAFT");
        assertThat(configurationCount(jdbcTemplate, unconfiguredAgent.enterpriseAgentId())).isZero();
        assertThat(eventCount(jdbcTemplate, unconfiguredAgent.enterpriseAgentId())).isEqualTo(1);

        var versionRetiredBeforeActivation = service.publishVersion(
                publishCommand("retired-before-activate-" + suffix),
                PlatformAccessContext.fromAuthenticatedPrincipal(platformPrincipal())
        ).resource();
        var configuredAgent = service.hire(
                new HireEnterpriseAgentCommand(
                        versionRetiredBeforeActivation.agentVersionId(),
                        "retired-activate-" + suffix,
                        "待激活退休版本专员",
                        "hire-retired-activate-" + suffix,
                        "sha256:hire-retired-activate-" + suffix
                ),
                enterpriseContext
        ).resource();
        var configured = service.createConfigurationVersion(
                configurationCommand(
                        configuredAgent.enterpriseAgentId(),
                        configuredAgent.stateVersion(),
                        "configure-before-retire-" + suffix
                ),
                enterpriseContext
        ).resource();
        retireVersion(jdbcTemplate, versionRetiredBeforeActivation.agentVersionId());

        assertThatThrownBy(() -> service.activate(
                new ActivateEnterpriseAgentCommand(
                        configuredAgent.enterpriseAgentId(),
                        configured.latestConfiguration().configurationVersionId(),
                        configured.agent().stateVersion(),
                        "activate-retired-" + suffix,
                        "sha256:activate-retired-" + suffix
                ),
                enterpriseContext
        )).isInstanceOf(EmployeeCommandConflictException.class)
                .extracting("code")
                .isEqualTo("AGENT_VERSION_NOT_PUBLISHED");
        assertAgentState(jdbcTemplate, configuredAgent.enterpriseAgentId(), 1, "DRAFT");
        assertThat(jdbcTemplate.queryForObject(
                """
                SELECT status
                  FROM dianlian_business.enterprise_agent_configuration_version
                 WHERE configuration_version_id = ?
                """,
                String.class,
                configured.latestConfiguration().configurationVersionId()
        )).isEqualTo("DRAFT");
        assertThat(jdbcTemplate.queryForObject(
                """
                SELECT COUNT(*)
                  FROM dianlian_business.enterprise_agent_configuration_version
                 WHERE configuration_version_id = ?
                   AND (activation_request_hash IS NOT NULL
                     OR activation_idempotency_key IS NOT NULL
                     OR activated_by IS NOT NULL
                     OR activated_at IS NOT NULL
                     OR activation_result_state_version IS NOT NULL)
                """,
                Integer.class,
                configured.latestConfiguration().configurationVersionId()
        )).isZero();
        assertThat(eventCount(jdbcTemplate, configuredAgent.enterpriseAgentId())).isEqualTo(2);
        assertThat(jdbcTemplate.queryForObject(
                """
                SELECT COUNT(*)
                  FROM dianlian_business.enterprise_agent_state_event
                 WHERE enterprise_agent_id = ?
                   AND event_type = 'ACTIVATED'
                """,
                Integer.class,
                configuredAgent.enterpriseAgentId()
        )).isZero();
    }

    private static PublishAgentVersionCommand publishCommand(String suffix) {
        return new PublishAgentVersionCommand(
                "jdbc-template-" + suffix,
                "通用业务专员",
                "验证模板退休后的配置与激活门禁",
                "1.0.0",
                "GENERIC_TASK",
                new InputSchemaDescriptor("generic.task.input", "1.0.0", "{\"type\":\"object\"}"),
                new ExecutionTemplateDescriptor(
                        "generic.task.flow",
                        "1.0.0",
                        List.of(new ExecutionStepDescriptor(
                                "prepare",
                                "准备",
                                ExecutionExecutorType.MODEL,
                                List.of(),
                                "generic.task.input",
                                "generic.task.output",
                                false
                        ))
                ),
                40,
                EnterpriseVisibility.allowlist(Set.of(ENTERPRISE_TENANT)),
                "publish-" + suffix,
                "sha256:publish-" + suffix
        );
    }

    private static CreateEnterpriseAgentConfigurationCommand configurationCommand(
            UUID enterpriseAgentId,
            long expectedStateVersion,
            String suffix
    ) {
        return new CreateEnterpriseAgentConfigurationCommand(
                enterpriseAgentId,
                expectedStateVersion,
                "企业通用业务专员",
                "验证模板退休后的配置与激活门禁",
                "仅使用当前企业授权数据。",
                EnterpriseAgentModelPolicyMode.PLATFORM_DEFAULT,
                EnterpriseAgentKnowledgeScopeMode.NONE,
                EnterpriseAgentVisibilityScope.TENANT,
                suffix,
                "sha256:" + suffix
        );
    }

    private static void retireVersion(JdbcTemplate jdbcTemplate, UUID agentVersionId) {
        assertThat(jdbcTemplate.update(
                """
                UPDATE dianlian_business.agent_version
                   SET status = 'RETIRED', updated_at = CURRENT_TIMESTAMP
                 WHERE agent_version_id = ?
                   AND status = 'PUBLISHED'
                """,
                agentVersionId
        )).isEqualTo(1);
    }

    private static void assertAgentState(
            JdbcTemplate jdbcTemplate,
            UUID enterpriseAgentId,
            long expectedStateVersion,
            String expectedStatus
    ) {
        assertThat(jdbcTemplate.queryForObject(
                "SELECT status FROM dianlian_business.enterprise_agent WHERE enterprise_agent_id = ?",
                String.class,
                enterpriseAgentId
        )).isEqualTo(expectedStatus);
        assertThat(jdbcTemplate.queryForObject(
                "SELECT state_version FROM dianlian_business.enterprise_agent WHERE enterprise_agent_id = ?",
                Long.class,
                enterpriseAgentId
        )).isEqualTo(expectedStateVersion);
        assertThat(jdbcTemplate.queryForObject(
                "SELECT active_configuration_version_id FROM dianlian_business.enterprise_agent WHERE enterprise_agent_id = ?",
                UUID.class,
                enterpriseAgentId
        )).isNull();
    }

    private static int configurationCount(JdbcTemplate jdbcTemplate, UUID enterpriseAgentId) {
        return jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM dianlian_business.enterprise_agent_configuration_version WHERE enterprise_agent_id = ?",
                Integer.class,
                enterpriseAgentId
        );
    }

    private static int eventCount(JdbcTemplate jdbcTemplate, UUID enterpriseAgentId) {
        return jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM dianlian_business.enterprise_agent_state_event WHERE enterprise_agent_id = ?",
                Integer.class,
                enterpriseAgentId
        );
    }

    private static AuthenticatedPrincipal platformPrincipal() {
        return principal(
                PLATFORM_ACTOR,
                null,
                Set.of(EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH)
        );
    }

    private static AuthenticatedPrincipal enterprisePrincipal() {
        return principal(
                ENTERPRISE_ACTOR,
                new SessionView.Tenant(
                        new TenantId(ENTERPRISE_TENANT),
                        "企业A",
                        SessionView.TenantStatus.ACTIVE,
                        SessionView.MembershipStatus.ACTIVE
                ),
                Set.of(
                        EmployeePermissions.ENTERPRISE_AGENT_HIRE,
                        EmployeePermissions.ENTERPRISE_AGENT_READ,
                        EmployeePermissions.ENTERPRISE_AGENT_CONFIGURE,
                        EmployeePermissions.ENTERPRISE_AGENT_ACTIVATE,
                        EmployeePermissions.ENTERPRISE_AGENT_EXECUTE
                )
        );
    }

    private static AuthenticatedPrincipal principal(
            UUID actorId,
            SessionView.Tenant activeTenant,
            Set<String> permissions
    ) {
        Instant authenticatedAt = Instant.parse("2026-08-11T00:00:00Z");
        return new AuthenticatedPrincipal(
                UUID.randomUUID(),
                new ActorId(actorId),
                "测试用户",
                null,
                SessionView.AccountStatus.ACTIVE,
                activeTenant,
                activeTenant == null
                        ? List.of(new SessionView.RoleGrant(
                                "PLATFORM_OPERATOR",
                                SessionView.DataScopeType.PLATFORM,
                                UUID.fromString("10000000-0000-0000-0000-000000000000")
                        ))
                        : List.of(),
                permissions,
                "jdbc-test-v1",
                authenticatedAt,
                authenticatedAt.plusSeconds(3600)
        );
    }
}

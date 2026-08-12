package com.dianlian.platform.bootstrap.application;

import static org.assertj.core.api.Assertions.assertThat;

import com.dianlian.platform.bootstrap.infrastructure.web.EmployeeWorkspaceController;
import com.dianlian.platform.bootstrap.infrastructure.web.OfficeController;
import com.dianlian.platform.employee.api.AgentVersionStatus;
import com.dianlian.platform.employee.api.EmployeePermissions;
import com.dianlian.platform.employee.api.EnterpriseAgentKnowledgeScopeMode;
import com.dianlian.platform.employee.api.EnterpriseAgentModelPolicyMode;
import com.dianlian.platform.employee.api.EnterpriseAgentStatus;
import com.dianlian.platform.employee.api.ExecutableAgentQuery;
import com.dianlian.platform.employee.api.ExecutableAgentSummary;
import com.dianlian.platform.employee.api.ExecutionExecutorType;
import com.dianlian.platform.employee.api.ExecutionStepDescriptor;
import com.dianlian.platform.employee.api.ExecutionTemplateDescriptor;
import com.dianlian.platform.employee.api.InputSchemaDescriptor;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorContextPort;
import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.TenantId;
import com.dianlian.platform.task.api.OfficeTaskSummary;
import com.dianlian.platform.task.api.OfficeTaskSummaryPort;
import com.dianlian.platform.task.api.TaskAllowedAction;
import com.dianlian.platform.task.api.TaskDisplayStatus;
import com.dianlian.platform.task.api.TaskPointSummary;
import com.dianlian.platform.task.api.TaskStatus;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;

class OfficeSnapshotApplicationServiceTests {

    private static final UUID ACTOR_ID = UUID.fromString("10000000-0000-0000-0000-000000000001");
    private static final UUID TENANT_ID = UUID.fromString("20000000-0000-0000-0000-000000000001");
    private static final UUID AGENT_ID = UUID.fromString("30000000-0000-0000-0000-000000000001");
    private static final UUID TASK_ID = UUID.fromString("40000000-0000-0000-0000-000000000001");

    @Test
    void projectsAuthorizedEmployeesAndTaskFactsWithoutCopyingBusinessState() {
        ActorContextPort actorContext = () -> Optional.of(principal());
        var agentQuery = new ExecutableAgentQuery() {
            @Override
            public List<ExecutableAgentSummary> listExecutableForOffice(AccessContext accessContext) {
                return List.of(agent());
            }

            @Override
            public ExecutableAgentSummary requireExecutableForTask(
                    UUID enterpriseAgentId,
                    AccessContext accessContext
            ) {
                return agent();
            }

            @Override
            public ExecutableAgentSummary requireExecutableForTask(
                    UUID enterpriseAgentId,
                    String requiredCapabilityCode,
                    AccessContext accessContext
            ) {
                return agent();
            }
        };
        OfficeTaskSummaryPort taskQuery = (accessContext, limit) -> List.of(failedTask());

        var service = new OfficeSnapshotApplicationService(actorContext, agentQuery, taskQuery);
        var first = service.currentSnapshot();
        var second = service.currentSnapshot();

        assertThat(first.snapshotVersion()).isEqualTo(second.snapshotVersion());
        assertThat(first.agents()).singleElement().satisfies(agent -> {
            assertThat(agent.agentId()).isEqualTo(AGENT_ID);
            assertThat(agent.officeStatus()).isEqualTo("NEEDS_ATTENTION");
            assertThat(agent.activeTaskCount()).isEqualTo(1);
            assertThat(agent.pendingActionCount()).isEqualTo(1);
            assertThat(agent.currentTaskTitle()).isEqualTo("工商银行展台报价");
            assertThat(agent.allowedActions()).containsExactly("VIEW", "START_WORK");
        });
        assertThat(first.tasks()).singleElement().satisfies(task -> {
            assertThat(task.pointSummary().estimatedUpperBound()).isEqualTo("12.5");
            assertThat(task.pointSummary().reserved()).isEqualTo("8");
            assertThat(task.currentStepTitle()).isEqualTo("复核价格规则");
        });
        assertThat(first.todos()).singleElement().satisfies(todo ->
                assertThat(todo.todoType()).isEqualTo("EXCEPTION")
        );
        assertThat(first.rooms()).isEmpty();
        assertThat(first.artifacts()).isEmpty();
        assertThat(first.resumeEventId()).isEqualTo("0");

        var controller = new OfficeController(service);
        var initialResponse = controller.currentOffice(null);
        var cachedResponse = controller.currentOffice(initialResponse.getHeaders().getFirst(HttpHeaders.ETAG));
        assertThat(initialResponse.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(cachedResponse.getStatusCode()).isEqualTo(HttpStatus.NOT_MODIFIED);
        assertThat(cachedResponse.getBody()).isNull();

        var workspaceController = new EmployeeWorkspaceController(actorContext, agentQuery, new ObjectMapper());
        var workspaceResponse = workspaceController.currentWorkspace(AGENT_ID, null);
        var cachedWorkspace = workspaceController.currentWorkspace(
                AGENT_ID,
                workspaceResponse.getHeaders().getFirst(HttpHeaders.ETAG)
        );
        assertThat(workspaceResponse.getBody()).satisfies(workspace -> {
            assertThat(workspace.capabilityCode()).isEqualTo("QUOTATION");
            assertThat(workspace.inputSchema().schemaId()).isEqualTo("quotation-input");
            assertThat(workspace.inputSchema().jsonSchema().isObject()).isTrue();
            assertThat(workspace.executionTemplate().steps()).hasSize(1);
            assertThat(workspace.pointEstimate()).isEqualTo("12.5");
        });
        assertThat(cachedWorkspace.getStatusCode()).isEqualTo(HttpStatus.NOT_MODIFIED);
    }

    private static AuthenticatedPrincipal principal() {
        var tenant = new SessionView.Tenant(
                new TenantId(TENANT_ID),
                "星海会展集团",
                SessionView.TenantStatus.ACTIVE,
                SessionView.MembershipStatus.ACTIVE
        );
        return new AuthenticatedPrincipal(
                UUID.fromString("50000000-0000-0000-0000-000000000001"),
                new ActorId(ACTOR_ID),
                "测试用户",
                null,
                SessionView.AccountStatus.ACTIVE,
                tenant,
                List.of(new SessionView.RoleGrant("TENANT_MEMBER", SessionView.DataScopeType.TENANT, TENANT_ID)),
                Set.of(
                        EmployeePermissions.ENTERPRISE_AGENT_READ,
                        EmployeePermissions.ENTERPRISE_AGENT_EXECUTE
                ),
                "permissions-v1",
                Instant.parse("2026-08-11T00:00:00Z"),
                Instant.parse("2026-08-12T00:00:00Z")
        );
    }

    private static ExecutableAgentSummary agent() {
        var inputSchema = new InputSchemaDescriptor(
                "quotation-input",
                "1",
                "{\"type\":\"object\"}"
        );
        var executionTemplate = new ExecutionTemplateDescriptor(
                "quotation-default",
                "1",
                List.of(new ExecutionStepDescriptor(
                        "price-review",
                        "复核价格规则",
                        ExecutionExecutorType.RULE_ENGINE,
                        List.of(),
                        null,
                        "quotation-result",
                        false
                ))
        );
        return new ExecutableAgentSummary(
                AGENT_ID,
                UUID.fromString("60000000-0000-0000-0000-000000000001"),
                UUID.fromString("70000000-0000-0000-0000-000000000001"),
                UUID.fromString("71000000-0000-0000-0000-000000000001"),
                "quotation",
                "点联报价专员",
                "报价专员",
                "依据企业规则生成可复核报价",
                "仅使用当前企业授权数据。",
                EnterpriseAgentModelPolicyMode.PLATFORM_DEFAULT,
                EnterpriseAgentKnowledgeScopeMode.NONE,
                List.of("历史案例", "确定性计价"),
                null,
                "QUOTATION",
                inputSchema,
                executionTemplate,
                12_500_000L,
                EnterpriseAgentStatus.ACTIVE,
                AgentVersionStatus.PUBLISHED
        );
    }

    private static OfficeTaskSummary failedTask() {
        return new OfficeTaskSummary(
                TASK_ID,
                "工商银行展台报价",
                TaskStatus.FAILED,
                TaskDisplayStatus.NEEDS_ATTENTION,
                List.of(AGENT_ID),
                "复核价格规则",
                1,
                3,
                new TaskPointSummary(12_500_000L, 8_000_000L, 4_000_000L, 500_000L, 3_500_000L),
                Instant.parse("2026-08-11T03:00:00Z"),
                Set.of(TaskAllowedAction.VIEW, TaskAllowedAction.RETRY_FROM_STEP)
        );
    }
}

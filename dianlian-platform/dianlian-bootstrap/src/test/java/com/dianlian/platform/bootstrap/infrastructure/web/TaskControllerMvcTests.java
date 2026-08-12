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
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.SessionAuthenticationPort;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.SessionViewApplicationApi;
import com.dianlian.platform.identity.api.TenantId;
import com.dianlian.platform.identity.infrastructure.PrincipalAccessContextAdapter;
import com.dianlian.platform.task.api.CollaborationMode;
import com.dianlian.platform.task.api.CreateTaskCommand;
import com.dianlian.platform.task.api.CreateTaskUseCase;
import com.dianlian.platform.task.api.TaskAllowedAction;
import com.dianlian.platform.task.api.TaskAccessDeniedException;
import com.dianlian.platform.task.api.TaskCommandAccepted;
import com.dianlian.platform.task.api.TaskPermissions;
import com.dianlian.platform.task.api.TaskPointSummary;
import com.dianlian.platform.task.api.TaskSnapshot;
import com.dianlian.platform.task.api.TaskSnapshotQuery;
import com.dianlian.platform.task.api.TaskStatus;
import com.dianlian.platform.task.infrastructure.web.TaskController;
import com.dianlian.platform.task.infrastructure.web.TaskEventSsePublisher;
import com.dianlian.platform.task.infrastructure.web.TaskProblemHandler;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
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
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@WebMvcTest(controllers = {SessionController.class, TaskController.class})
@TestExecutionListeners(
        listeners = {ServletTestExecutionListener.class, DependencyInjectionTestExecutionListener.class},
        mergeMode = TestExecutionListeners.MergeMode.REPLACE_DEFAULTS
)
@Import({
        SaTokenWebMvcConfiguration.class,
        SaTokenAuthenticationInterceptor.class,
        DianlianPrincipalContext.class,
        ApiSecurityProblemWriter.class,
        TaskProblemHandler.class,
        SaTokenActorContextAdapter.class,
        PrincipalAccessContextAdapter.class,
        TaskControllerMvcTests.TestDoubles.class
})
class TaskControllerMvcTests {

    private static final String ACCESS_TOKEN = "test-jwt-access-token";
    private static final String IDEMPOTENCY_KEY = "task-create-00000001";
    private static final String PRIVATE_REVALIDATE = "private, no-cache, must-revalidate";
    private static final UUID TASK_ID = UUID.fromString("40000000-0000-0000-0000-000000000001");
    private static final UUID AGENT_ID = UUID.fromString("50000000-0000-0000-0000-000000000001");
    private static final UUID RESUME_EVENT_ID = UUID.fromString("60000000-0000-0000-0000-000000000001");

    private final MockMvc mockMvc;
    private final ObjectMapper objectMapper;
    private final TestStpLogic stpLogic;
    private final MutableSessionAuthenticationPort sessionAuthenticationPort;
    private final RecordingCreateTaskUseCase createTaskUseCase;
    private final RecordingTaskSnapshotQuery taskSnapshotQuery;
    private final RecordingTaskEventSsePublisher taskEventSsePublisher;

    @Autowired
    TaskControllerMvcTests(
            MockMvc mockMvc,
            ObjectMapper objectMapper,
            TestStpLogic stpLogic,
            MutableSessionAuthenticationPort sessionAuthenticationPort,
            RecordingCreateTaskUseCase createTaskUseCase,
            RecordingTaskSnapshotQuery taskSnapshotQuery,
            RecordingTaskEventSsePublisher taskEventSsePublisher
    ) {
        this.mockMvc = mockMvc;
        this.objectMapper = objectMapper;
        this.stpLogic = stpLogic;
        this.sessionAuthenticationPort = sessionAuthenticationPort;
        this.createTaskUseCase = createTaskUseCase;
        this.taskSnapshotQuery = taskSnapshotQuery;
        this.taskEventSsePublisher = taskEventSsePublisher;
    }

    @BeforeEach
    void resetTestDoubles() {
        sessionAuthenticationPort.principal = null;
        createTaskUseCase.reset();
        taskSnapshotQuery.reset();
        taskEventSsePublisher.reset();
    }

    @Test
    void createTaskUsesServerIdentityExactPointConversionAndIdempotencyKey() throws Exception {
        stubAuthenticatedPrincipal();
        var acceptedAt = Instant.parse("2026-08-11T01:00:00Z");
        createTaskUseCase.response = new TaskCommandAccepted(
                        TASK_ID,
                        1,
                        TaskStatus.PLANNING,
                        acceptedAt,
                        "/api/v1/tasks/" + TASK_ID,
                        "/api/v1/tasks/" + TASK_ID + "/events",
                        RESUME_EVENT_ID,
                        false
                );

        mockMvc.perform(post("/api/v1/tasks")
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("Idempotency-Key", IDEMPOTENCY_KEY)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(taskRequest("12.5", TestIdentity.ACTOR_ID)))
                .andExpect(status().isAccepted())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(header().string("Location", "/api/v1/tasks/" + TASK_ID))
                .andExpect(header().string("Idempotency-Replayed", "false"))
                .andExpect(jsonPath("$.taskId").value(TASK_ID.toString()))
                .andExpect(jsonPath("$.status").value("PLANNING"))
                .andExpect(jsonPath("$.idempotencyReplayed").doesNotExist());

        assertThat(createTaskUseCase.callCount).isEqualTo(1);
        assertThat(createTaskUseCase.command.idempotencyKey()).isEqualTo(IDEMPOTENCY_KEY);
        assertThat(createTaskUseCase.command.maxPointCost()).isEqualTo(12_500_000L);
        assertThat(createTaskUseCase.command.ownership().ownerUserId()).isEqualTo(TestIdentity.ACTOR_ID);
        assertThat(createTaskUseCase.accessContext.actorId().value()).isEqualTo(TestIdentity.ACTOR_ID);
        assertThat(createTaskUseCase.accessContext.tenantId().value()).isEqualTo(TestIdentity.TENANT_ID);
    }

    @Test
    void createTaskRejectsClientOwnerDifferentFromCurrentActor() throws Exception {
        stubAuthenticatedPrincipal();
        var anotherActorId = UUID.fromString("20000000-0000-0000-0000-000000000099");

        mockMvc.perform(post("/api/v1/tasks")
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("Idempotency-Key", IDEMPOTENCY_KEY)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(taskRequest("1", anotherActorId)))
                .andExpect(status().isForbidden())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.code").value("TASK_OWNER_MISMATCH"))
                .andExpect(jsonPath("$.retryable").value(false))
                .andExpect(jsonPath("$.action").value("REFRESH_SESSION"))
                .andExpect(jsonPath("$.traceId").isNotEmpty());

        assertThat(createTaskUseCase.callCount).isZero();
    }

    @ParameterizedTest
    @ValueSource(strings = {"-1", "1.0000001", "9223372036854.775808"})
    void createTaskRejectsInvalidPublicPointStrings(String maxPointCost) throws Exception {
        stubAuthenticatedPrincipal();

        mockMvc.perform(post("/api/v1/tasks")
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("Idempotency-Key", IDEMPOTENCY_KEY)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(taskRequest(maxPointCost, TestIdentity.ACTOR_ID)))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

        assertThat(createTaskUseCase.callCount).isZero();
    }

    @Test
    void createTaskRejectsNumericPointValue() throws Exception {
        stubAuthenticatedPrincipal();

        mockMvc.perform(post("/api/v1/tasks")
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("Idempotency-Key", IDEMPOTENCY_KEY)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(taskRequest(12.5, TestIdentity.ACTOR_ID)))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

        assertThat(createTaskUseCase.callCount).isZero();
    }

    @Test
    void taskSnapshotFormatsPointsAndSupportsConditionalGet() throws Exception {
        stubAuthenticatedPrincipal();
        taskSnapshotQuery.response = taskSnapshot();

        var firstResponse = mockMvc.perform(get("/api/v1/tasks/{taskId}", TASK_ID)
                        .header("Authorization", "Bearer " + ACCESS_TOKEN))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(header().string("Cache-Control", PRIVATE_REVALIDATE))
                .andExpect(jsonPath("$.taskVersion").value(7))
                .andExpect(jsonPath("$.pointSummary.estimatedUpperBound").value("12.5"))
                .andExpect(jsonPath("$.pointSummary.reserved").value("1"))
                .andExpect(jsonPath("$.pointSummary.captured").value("0.000001"))
                .andExpect(jsonPath("$.pointSummary.released").value("0"))
                .andExpect(jsonPath("$.pointSummary.pendingSettlement").value("0.25"))
                .andReturn();

        var etag = firstResponse.getResponse().getHeader("ETag");
        assertThat(etag).isNotNull().matches("\"[0-9a-f]{64}\"");

        mockMvc.perform(get("/api/v1/tasks/{taskId}", TASK_ID)
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("If-None-Match", etag))
                .andExpect(status().isNotModified())
                .andExpect(header().string("ETag", etag))
                .andExpect(header().string("Cache-Control", PRIVATE_REVALIDATE))
                .andExpect(content().string(""));
    }

    @Test
    void taskEventsUseAuthenticatedContextCursorAndNonBufferedNoStoreResponse() throws Exception {
        stubAuthenticatedPrincipal();

        mockMvc.perform(get("/api/v1/tasks/{taskId}/events", TASK_ID)
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("Last-Event-ID", RESUME_EVENT_ID)
                        .queryParam("afterEventId", RESUME_EVENT_ID.toString())
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM))
                .andExpect(header().string("Cache-Control", "no-store, no-transform"))
                .andExpect(header().string("X-Accel-Buffering", "no"))
                .andExpect(header().exists("X-Trace-Id"));

        assertThat(taskEventSsePublisher.openCalls).isEqualTo(1);
        assertThat(taskEventSsePublisher.afterEventId).isEqualTo(RESUME_EVENT_ID.toString());
        assertThat(taskEventSsePublisher.sessionId).isEqualTo(TestIdentity.SESSION_ID);
        assertThat(taskEventSsePublisher.accessContext.tenantId().value()).isEqualTo(TestIdentity.TENANT_ID);
        assertThat(taskEventSsePublisher.accessContext.actorId().value()).isEqualTo(TestIdentity.ACTOR_ID);
    }

    @Test
    void taskEventsRejectConflictingHeaderAndQueryCursorsBeforeOpeningStream() throws Exception {
        stubAuthenticatedPrincipal();

        mockMvc.perform(get("/api/v1/tasks/{taskId}/events", TASK_ID)
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .header("Last-Event-ID", RESUME_EVENT_ID)
                        .queryParam("afterEventId", "60000000-0000-0000-0000-000000000099")
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));

        assertThat(taskEventSsePublisher.openCalls).isZero();
    }

    @Test
    void taskEventsDoNotOpenAnEventBodyWithoutTaskReadPermission() throws Exception {
        stubAuthenticatedPrincipal(Set.of(TaskPermissions.CREATE));

        mockMvc.perform(get("/api/v1/tasks/{taskId}/events", TASK_ID)
                        .header("Authorization", "Bearer " + ACCESS_TOKEN)
                        .accept(MediaType.TEXT_EVENT_STREAM))
                .andExpect(status().isForbidden())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(header().string("Cache-Control", "no-store"))
                .andExpect(jsonPath("$.code").value("TASK_ACCESS_DENIED"));

        assertThat(taskEventSsePublisher.openCalls).isZero();
    }

    private void stubAuthenticatedPrincipal() {
        sessionAuthenticationPort.principal = TestIdentity.authenticatedPrincipal();
    }

    private void stubAuthenticatedPrincipal(Set<String> permissions) {
        sessionAuthenticationPort.principal = TestIdentity.authenticatedPrincipal(permissions);
    }

    private byte[] taskRequest(Object maxPointCost, UUID ownerUserId) throws Exception {
        var ownership = new LinkedHashMap<String, Object>();
        ownership.put("ownerUserId", ownerUserId);
        ownership.put("billingScopeType", "TENANT");
        ownership.put("billingScopeId", TestIdentity.TENANT_ID);

        var request = new LinkedHashMap<String, Object>();
        request.put("goal", "整理本次活动的平面出图需求");
        request.put("collaborationMode", "SINGLE_TARGET");
        request.put("targetAgentIds", List.of(AGENT_ID));
        request.put("ownership", ownership);
        request.put("maxPointCost", maxPointCost);
        request.put("capabilityInput", Map.of(
                "schemaId", "graphic-design.request",
                "schemaVersion", "1.0",
                "values", Map.of("brief", "蓝色科技风主视觉")
        ));
        return objectMapper.writeValueAsBytes(request);
    }

    private TaskSnapshot taskSnapshot() {
        return new TaskSnapshot(
                TASK_ID,
                7,
                "活动主视觉设计",
                "完成展览活动主视觉平面出图",
                TaskStatus.RUNNING,
                null,
                2,
                CollaborationMode.SINGLE_TARGET,
                "GRAPHIC_DESIGN",
                Map.of("brief", "蓝色科技风主视觉"),
                List.of(AGENT_ID),
                null,
                List.of(),
                null,
                List.of(),
                null,
                null,
                new TaskPointSummary(12_500_000L, 1_000_000L, 1L, 0L, 250_000L),
                List.of(),
                Set.of(TaskAllowedAction.VIEW, TaskAllowedAction.PAUSE),
                RESUME_EVENT_ID,
                Instant.parse("2026-08-11T01:05:00Z")
        );
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class TestDoubles {

        @Bean
        MutableSessionAuthenticationPort sessionAuthenticationPort() {
            return new MutableSessionAuthenticationPort();
        }

        @Bean
        SessionViewApplicationApi sessionViewApplicationApi() {
            return TestIdentity::sessionView;
        }

        @Bean
        TestStpLogic stpLogic() {
            return new TestStpLogic();
        }

        @Bean
        RecordingCreateTaskUseCase createTaskUseCase() {
            return new RecordingCreateTaskUseCase();
        }

        @Bean
        RecordingTaskSnapshotQuery taskSnapshotQuery() {
            return new RecordingTaskSnapshotQuery();
        }

        @Bean
        RecordingTaskEventSsePublisher taskEventSsePublisher() {
            return new RecordingTaskEventSsePublisher();
        }
    }

    private static final class TestStpLogic extends StpLogic {

        private TestStpLogic() {
            super("dianlian-task-mvc-test");
        }

        @Override
        public void checkLogin() {
        }

        @Override
        public Object getExtra(String key) {
            return "sid".equals(key) ? TestIdentity.SESSION_ID.toString() : null;
        }

        @Override
        public String getTokenValue() {
            return ACCESS_TOKEN;
        }

        @Override
        public String getLoginIdAsString() {
            return TestIdentity.ACTOR_ID.toString();
        }
    }

    private static final class MutableSessionAuthenticationPort implements SessionAuthenticationPort {

        private AuthenticatedPrincipal principal;

        @Override
        public Optional<AuthenticatedPrincipal> authenticate(UUID sessionId, Instant observedAt) {
            if (!TestIdentity.SESSION_ID.equals(sessionId)) {
                return Optional.empty();
            }
            return Optional.ofNullable(principal);
        }
    }

    private static final class RecordingCreateTaskUseCase implements CreateTaskUseCase {

        private int callCount;
        private CreateTaskCommand command;
        private AccessContext accessContext;
        private TaskCommandAccepted response;

        @Override
        public TaskCommandAccepted create(CreateTaskCommand command, AccessContext accessContext) {
            callCount++;
            this.command = command;
            this.accessContext = accessContext;
            if (response == null) {
                throw new IllegalStateException("Task response was not configured");
            }
            return response;
        }

        private void reset() {
            callCount = 0;
            command = null;
            accessContext = null;
            response = null;
        }
    }

    private static final class RecordingTaskSnapshotQuery implements TaskSnapshotQuery {

        private TaskSnapshot response;

        @Override
        public TaskSnapshot requireSnapshot(UUID taskId, AccessContext accessContext) {
            if (!TASK_ID.equals(taskId) || response == null) {
                throw new IllegalStateException("Task snapshot was not configured");
            }
            return response;
        }

        private void reset() {
            response = null;
        }
    }

    private static final class RecordingTaskEventSsePublisher implements TaskEventSsePublisher {

        private int openCalls;
        private String afterEventId;
        private UUID sessionId;
        private AccessContext accessContext;

        @Override
        public SseEmitter open(
                UUID taskId,
                String afterEventId,
                UUID sessionId,
                AccessContext accessContext
        ) {
            if (!accessContext.authorities().contains(TaskPermissions.READ)) {
                throw new TaskAccessDeniedException(TaskPermissions.READ);
            }
            openCalls++;
            this.afterEventId = afterEventId;
            this.sessionId = sessionId;
            this.accessContext = accessContext;
            var emitter = new SseEmitter(1L);
            try {
                emitter.send(SseEmitter.event().comment("connected"));
                emitter.complete();
            } catch (IOException exception) {
                throw new IllegalStateException(exception);
            }
            return emitter;
        }

        private void reset() {
            openCalls = 0;
            afterEventId = null;
            sessionId = null;
            accessContext = null;
        }
    }

    private static final class TestIdentity {

        private static final UUID SESSION_ID = UUID.fromString("10000000-0000-0000-0000-000000000001");
        private static final UUID ACTOR_ID = UUID.fromString("20000000-0000-0000-0000-000000000001");
        private static final UUID TENANT_ID = UUID.fromString("30000000-0000-0000-0000-000000000001");
        private static final Instant AUTHENTICATED_AT = Instant.parse("2026-08-11T00:00:00Z");
        private static final Instant EXPIRES_AT = Instant.parse("2026-08-11T08:00:00Z");
        private static final Set<String> PERMISSIONS = Set.of("task.create", "task.read");

        private TestIdentity() {
        }

        static AuthenticatedPrincipal authenticatedPrincipal() {
            return authenticatedPrincipal(PERMISSIONS);
        }

        static AuthenticatedPrincipal authenticatedPrincipal(Set<String> permissions) {
            return new AuthenticatedPrincipal(
                    SESSION_ID,
                    new ActorId(ACTOR_ID),
                    "测试用户",
                    null,
                    SessionView.AccountStatus.ACTIVE,
                    activeTenant(),
                    roleGrants(),
                    permissions,
                    "test-permissions-v1",
                    AUTHENTICATED_AT,
                    EXPIRES_AT
            );
        }

        static SessionView sessionView() {
            return new SessionView(
                    SESSION_ID,
                    new SessionView.User(
                            new ActorId(ACTOR_ID),
                            "测试用户",
                            null,
                            SessionView.AccountStatus.ACTIVE
                    ),
                    activeTenant(),
                    roleGrants(),
                    PERMISSIONS,
                    "test-permissions-v1",
                    AUTHENTICATED_AT
            );
        }

        private static SessionView.Tenant activeTenant() {
            return new SessionView.Tenant(
                    new TenantId(TENANT_ID),
                    "测试企业",
                    SessionView.TenantStatus.ACTIVE,
                    SessionView.MembershipStatus.ACTIVE
            );
        }

        private static List<SessionView.RoleGrant> roleGrants() {
            return List.of(new SessionView.RoleGrant(
                    "TENANT_MEMBER",
                    SessionView.DataScopeType.TENANT,
                    TENANT_ID
            ));
        }
    }
}

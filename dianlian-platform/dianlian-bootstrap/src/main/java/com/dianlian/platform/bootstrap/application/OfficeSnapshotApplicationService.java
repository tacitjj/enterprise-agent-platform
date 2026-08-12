package com.dianlian.platform.bootstrap.application;

import com.dianlian.platform.billing.api.PointValues;
import com.dianlian.platform.employee.api.EmployeePermissions;
import com.dianlian.platform.employee.api.ExecutableAgentQuery;
import com.dianlian.platform.employee.api.ExecutableAgentSummary;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorContextPort;
import com.dianlian.platform.task.api.OfficeTaskSummary;
import com.dianlian.platform.task.api.OfficeTaskSummaryPort;
import com.dianlian.platform.task.api.TaskStatus;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Service;

@Service
public final class OfficeSnapshotApplicationService {

    private static final int SUMMARY_LIMIT = 50;
    private static final String MAPPING_VERSION = "office-v1";
    // This slice has no admitted OFFICE_USER event journal yet; zero is the durable empty-stream watermark.
    private static final String EMPTY_OFFICE_EVENT_WATERMARK = "0";

    private final ActorContextPort actorContextPort;
    private final ExecutableAgentQuery executableAgentQuery;
    private final OfficeTaskSummaryPort taskSummaryPort;

    public OfficeSnapshotApplicationService(
            ActorContextPort actorContextPort,
            ExecutableAgentQuery executableAgentQuery,
            OfficeTaskSummaryPort taskSummaryPort
    ) {
        this.actorContextPort = Objects.requireNonNull(actorContextPort, "actorContextPort must not be null");
        this.executableAgentQuery = Objects.requireNonNull(
                executableAgentQuery,
                "executableAgentQuery must not be null"
        );
        this.taskSummaryPort = Objects.requireNonNull(taskSummaryPort, "taskSummaryPort must not be null");
    }

    public OfficeSnapshotView currentSnapshot() {
        var principal = actorContextPort.requireCurrent();
        var accessContext = AccessContext.fromAuthenticatedPrincipal(principal);
        var agents = executableAgentQuery.listExecutableForOffice(accessContext);
        var tasks = taskSummaryPort.listVisibleTasks(accessContext, SUMMARY_LIMIT);
        var agentViews = agents.stream()
                .map(agent -> toAgentView(agent, tasks, accessContext))
                .toList();
        var taskViews = tasks.stream().map(OfficeSnapshotApplicationService::toTaskView).toList();
        var todos = tasks.stream()
                .filter(OfficeSnapshotApplicationService::requiresUserAction)
                .limit(SUMMARY_LIMIT)
                .map(OfficeSnapshotApplicationService::toTodoView)
                .toList();
        var snapshotVersion = snapshotVersion(
                principal.permissionVersion(),
                accessContext.tenantId().value(),
                accessContext.actorId().value(),
                agentViews,
                taskViews,
                todos
        );

        return new OfficeSnapshotView(
                snapshotVersion,
                Instant.now(),
                MAPPING_VERSION,
                EMPTY_OFFICE_EVENT_WATERMARK,
                EMPTY_OFFICE_EVENT_WATERMARK,
                agentViews,
                List.of(),
                taskViews,
                List.of(),
                todos,
                new HasMoreView(
                        agents.size() == SUMMARY_LIMIT,
                        false,
                        tasks.size() == SUMMARY_LIMIT,
                        false,
                        todos.size() == SUMMARY_LIMIT
                )
        );
    }

    private static OfficeAgentView toAgentView(
            ExecutableAgentSummary agent,
            List<OfficeTaskSummary> tasks,
            AccessContext accessContext
    ) {
        var agentTasks = tasks.stream()
                .filter(task -> task.responsibleAgentIds().contains(agent.enterpriseAgentId()))
                .toList();
        var primaryTask = agentTasks.stream()
                .filter(task -> officeStatus(task) != AgentOfficeStatus.IDLE)
                .max(Comparator
                        .comparingInt((OfficeTaskSummary task) -> officeStatus(task).priority())
                        .thenComparing(OfficeTaskSummary::updatedAt))
                .orElse(null);
        var highestStatus = primaryTask == null ? AgentOfficeStatus.IDLE : officeStatus(primaryTask);
        var activeTaskCount = Math.toIntExact(agentTasks.stream()
                .filter(task -> task.status() != TaskStatus.SUCCEEDED && task.status() != TaskStatus.CANCELLED)
                .count());
        var pendingActionCount = Math.toIntExact(agentTasks.stream()
                .filter(OfficeSnapshotApplicationService::requiresUserAction)
                .count());
        var allowedActions = new ArrayList<String>();
        allowedActions.add("VIEW");
        if (accessContext.authorities().contains(EmployeePermissions.ENTERPRISE_AGENT_EXECUTE)) {
            allowedActions.add("START_WORK");
        }

        return new OfficeAgentView(
                agent.enterpriseAgentId(),
                agent.displayName(),
                agent.roleName(),
                agent.capabilityCode(),
                agent.profile(),
                agent.skillLabels(),
                agent.avatarUrl(),
                highestStatus.name(),
                activeTaskCount,
                pendingActionCount,
                primaryTask == null ? null : statusReasonCode(primaryTask),
                primaryTask == null ? null : primaryTask.title(),
                allowedActions
        );
    }

    private static AgentOfficeStatus officeStatus(OfficeTaskSummary task) {
        return switch (task.status()) {
            case FAILED, PARTIAL_SUCCESS -> AgentOfficeStatus.NEEDS_ATTENTION;
            case WAITING_APPROVAL -> AgentOfficeStatus.WAITING_APPROVAL;
            case WAITING_USER, WAITING_CONFIRMATION, PAUSED -> AgentOfficeStatus.WAITING_USER;
            case SUCCEEDED, CANCELLED -> AgentOfficeStatus.IDLE;
            default -> AgentOfficeStatus.WORKING;
        };
    }

    private static String statusReasonCode(OfficeTaskSummary task) {
        return switch (task.status()) {
            case FAILED -> "TASK_FAILED";
            case PARTIAL_SUCCESS -> "TASK_PARTIAL_SUCCESS";
            case PAUSED -> "TASK_PAUSED";
            default -> null;
        };
    }

    private static boolean requiresUserAction(OfficeTaskSummary task) {
        return switch (task.status()) {
            case WAITING_USER, WAITING_CONFIRMATION, WAITING_APPROVAL, PAUSED, FAILED, PARTIAL_SUCCESS -> true;
            default -> false;
        };
    }

    private static OfficeTaskView toTaskView(OfficeTaskSummary task) {
        return new OfficeTaskView(
                task.taskId(),
                task.title(),
                task.status().name(),
                task.displayStatus().name(),
                task.responsibleAgentIds(),
                task.currentStepTitle(),
                task.completedStepCount(),
                task.totalStepCount(),
                PointSummaryView.from(task),
                task.updatedAt(),
                task.allowedActions().stream().map(Enum::name).sorted().toList()
        );
    }

    private static OfficeTodoView toTodoView(OfficeTaskSummary task) {
        var todoType = switch (task.status()) {
            case WAITING_APPROVAL -> "APPROVAL";
            case FAILED, PARTIAL_SUCCESS -> "EXCEPTION";
            default -> "TASK_INPUT";
        };
        return new OfficeTodoView(
                "task:" + task.taskId() + ':' + todoType.toLowerCase(),
                todoType,
                task.taskId().toString(),
                task.title(),
                "NORMAL"
        );
    }

    private static String snapshotVersion(
            String permissionVersion,
            UUID tenantId,
            UUID actorId,
            List<OfficeAgentView> agents,
            List<OfficeTaskView> tasks,
            List<OfficeTodoView> todos
    ) {
        var canonical = String.join(
                "\u001f",
                permissionVersion,
                tenantId.toString(),
                actorId.toString(),
                agents.toString(),
                tasks.toString(),
                todos.toString()
        );
        try {
            var digest = MessageDigest.getInstance("SHA-256").digest(canonical.getBytes(StandardCharsets.UTF_8));
            return MAPPING_VERSION + '-' + HexFormat.of().formatHex(digest, 0, 16);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is required by the Java runtime", exception);
        }
    }

    private enum AgentOfficeStatus {
        IDLE(1),
        WORKING(2),
        WAITING_USER(3),
        WAITING_APPROVAL(4),
        NEEDS_ATTENTION(5);

        private final int priority;

        AgentOfficeStatus(int priority) {
            this.priority = priority;
        }

        int priority() {
            return priority;
        }
    }

    public record OfficeSnapshotView(
            String snapshotVersion,
            Instant generatedAt,
            String mappingVersion,
            String lastOfficeEventId,
            String resumeEventId,
            List<OfficeAgentView> agents,
            List<OfficeRoomView> rooms,
            List<OfficeTaskView> tasks,
            List<OfficeArtifactView> artifacts,
            List<OfficeTodoView> todos,
            HasMoreView hasMore
    ) {

        public String etag() {
            return '"' + snapshotVersion + '"';
        }
    }

    public record OfficeAgentView(
            UUID agentId,
            String displayName,
            String roleName,
            String capabilityCode,
            String profile,
            List<String> skillLabels,
            String avatarUrl,
            String officeStatus,
            int activeTaskCount,
            int pendingActionCount,
            String statusReasonCode,
            String currentTaskTitle,
            List<String> allowedActions
    ) {
    }

    public record OfficeRoomView(
            String conversationId,
            String displayName,
            String conversationType,
            int unreadCount,
            List<String> allowedActions
    ) {
    }

    public record OfficeTaskView(
            UUID taskId,
            String title,
            String status,
            String displayStatus,
            List<UUID> responsibleAgentIds,
            String currentStepTitle,
            int completedStepCount,
            int totalStepCount,
            PointSummaryView pointSummary,
            Instant updatedAt,
            List<String> allowedActions
    ) {
    }

    public record OfficeArtifactView(
            String artifactVersionId,
            String title,
            String artifactType,
            String artifactStatus,
            Instant createdAt,
            List<String> allowedActions
    ) {
    }

    public record OfficeTodoView(
            String todoId,
            String todoType,
            String objectId,
            String title,
            String dueState
    ) {
    }

    public record PointSummaryView(
            String estimatedUpperBound,
            String reserved,
            String captured,
            String released,
            String pendingSettlement
    ) {

        static PointSummaryView from(OfficeTaskSummary task) {
            var points = task.pointSummary();
            return new PointSummaryView(
                    PointValues.formatDisplayValue(points.estimatedUpperBound()),
                    PointValues.formatDisplayValue(points.reserved()),
                    PointValues.formatDisplayValue(points.captured()),
                    PointValues.formatDisplayValue(points.released()),
                    PointValues.formatDisplayValue(points.pendingSettlement())
            );
        }
    }

    public record HasMoreView(
            boolean agents,
            boolean rooms,
            boolean tasks,
            boolean artifacts,
            boolean todos
    ) {
    }
}

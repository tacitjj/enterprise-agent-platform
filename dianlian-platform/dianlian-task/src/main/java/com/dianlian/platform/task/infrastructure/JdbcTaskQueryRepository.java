package com.dianlian.platform.task.infrastructure;

import com.dianlian.platform.task.api.CollaborationMode;
import com.dianlian.platform.task.api.OfficeTaskSummary;
import com.dianlian.platform.task.api.TaskSnapshot;
import com.dianlian.platform.task.api.TaskPointSummary;
import com.dianlian.platform.task.api.TaskStatus;
import com.dianlian.platform.task.application.TaskActionPolicy;
import com.dianlian.platform.task.application.TaskPayloadSerializer;
import com.dianlian.platform.task.application.TaskQueryRepository;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcTaskQueryRepository implements TaskQueryRepository {

    private final JdbcTemplate jdbcTemplate;
    private final TaskPayloadSerializer serializer;

    public JdbcTaskQueryRepository(JdbcTemplate jdbcTemplate, TaskPayloadSerializer serializer) {
        this.jdbcTemplate = jdbcTemplate;
        this.serializer = serializer;
    }

    @Override
    public Optional<TaskSnapshot> findVisibleSnapshot(UUID tenantId, UUID actorId, UUID taskId) {
        var rows = jdbcTemplate.query(
                """
                SELECT tr.task_id, tr.task_version, tr.title, tr.goal, tr.status,
                       tr.current_plan_version, tr.collaboration_mode, tr.capability_code,
                       tr.primary_agent_id, tr.resume_event_id, tr.updated_at,
                       pr.amount AS reservation_amount, pr.captured_amount, pr.released_amount,
                       GREATEST(pr.captured_amount, COALESCE((
                           SELECT SUM(execution.captured_amount)
                             FROM dianlian_business.task_step_execution execution
                             JOIN dianlian_business.task_step step
                               ON step.tenant_id = execution.tenant_id
                              AND step.step_id = execution.task_step_id
                            WHERE step.tenant_id = tr.tenant_id AND step.task_id = tr.task_id
                       ), 0)) AS visible_captured_amount,
                       COALESCE((SELECT SUM(tt.estimated_point_cost)
                                   FROM dianlian_business.task_target tt
                                  WHERE tt.tenant_id = tr.tenant_id
                                    AND tt.task_id = tr.task_id), 0) AS estimated_upper_bound
                  FROM dianlian_business.task_run tr
                  JOIN dianlian_business.point_reservation pr
                    ON pr.tenant_id = tr.tenant_id
                   AND pr.reservation_id = tr.point_reservation_id
                 WHERE tr.tenant_id = ? AND tr.task_id = ?
                   AND EXISTS (
                       SELECT 1
                         FROM dianlian_business.task_participant participant
                        WHERE participant.tenant_id = tr.tenant_id
                          AND participant.task_id = tr.task_id
                          AND participant.user_id = ?
                          AND participant.status = 'ACTIVE'
                   )
                """,
                (resultSet, rowNum) -> mapSnapshotHeader(resultSet),
                tenantId,
                taskId,
                actorId
        );
        if (rows.isEmpty()) {
            return Optional.empty();
        }
        var header = rows.getFirst();
        var targetAgentIds = findTargetAgentIds(tenantId, taskId);
        var steps = findSteps(tenantId, taskId, header.planVersion());
        var activeRun = findActiveRun(tenantId, taskId);
        var artifactData = findArtifacts(tenantId, taskId);
        var artifacts = artifactData.stream().map(ArtifactData::summary).toList();
        Map<String, Object> capabilityView = artifactData.isEmpty()
                ? Map.of()
                : Map.of(
                    "latestArtifactContent", artifactData.getLast().contentText(),
                    "latestArtifactUsageEstimated", artifactData.getLast().usageEstimated()
                );
        var blocker = steps.stream()
                .filter(step -> step.blockerCode() != null)
                .findFirst()
                .map(step -> new TaskSnapshot.TaskBlocker(
                        step.blockerCode(),
                        step.responsibleType(),
                        blockerMessage(step.blockerCode())
                ))
                .orElse(null);
        var trace = findBusinessTrace(tenantId, taskId);
        return Optional.of(new TaskSnapshot(
                header.taskId(),
                header.taskVersion(),
                header.title(),
                header.goal(),
                header.status(),
                blocker,
                header.planVersion(),
                header.collaborationMode(),
                header.capabilityCode(),
                capabilityView,
                targetAgentIds,
                header.primaryAgentId(),
                steps,
                activeRun,
                artifacts,
                null,
                null,
                new TaskPointSummary(
                        header.estimatedUpperBound(),
                        Math.max(0, header.reservationAmount()
                                - header.visibleCapturedAmount() - header.releasedAmount()),
                        header.visibleCapturedAmount(),
                        header.releasedAmount(),
                        Math.max(0, header.reservationAmount()
                                - header.visibleCapturedAmount() - header.releasedAmount())
                ),
                trace,
                TaskActionPolicy.allowedActions(header.status()),
                header.resumeEventId(),
                header.updatedAt()
        ));
    }

    @Override
    public List<OfficeTaskSummary> findVisibleOfficeTasks(UUID tenantId, UUID actorId, int limit) {
        return jdbcTemplate.query(
                """
                SELECT tr.task_id, tr.title, tr.status, tr.updated_at,
                       (SELECT jsonb_agg(tt.enterprise_agent_id ORDER BY tt.target_order)::text
                          FROM dianlian_business.task_target tt
                         WHERE tt.tenant_id = tr.tenant_id AND tt.task_id = tr.task_id) AS target_agent_ids,
                       (SELECT step.title
                          FROM dianlian_business.task_step step
                         WHERE step.tenant_id = tr.tenant_id
                           AND step.task_id = tr.task_id
                           AND step.plan_version = tr.current_plan_version
                           AND step.status IN ('READY', 'RUNNING', 'WAITING_EXTERNAL', 'RETRY_WAIT')
                         ORDER BY step.step_order
                         LIMIT 1) AS current_step_title,
                       (SELECT COUNT(*)
                          FROM dianlian_business.task_step step
                         WHERE step.tenant_id = tr.tenant_id
                           AND step.task_id = tr.task_id
                           AND step.plan_version = tr.current_plan_version
                           AND step.status IN ('SUCCEEDED', 'SKIPPED')) AS completed_step_count,
                       (SELECT COUNT(*)
                          FROM dianlian_business.task_step step
                         WHERE step.tenant_id = tr.tenant_id
                           AND step.task_id = tr.task_id
                           AND step.plan_version = tr.current_plan_version) AS total_step_count,
                       pr.amount AS reservation_amount, pr.captured_amount, pr.released_amount,
                       GREATEST(pr.captured_amount, COALESCE((
                           SELECT SUM(execution.captured_amount)
                             FROM dianlian_business.task_step_execution execution
                             JOIN dianlian_business.task_step cost_step
                               ON cost_step.tenant_id = execution.tenant_id
                              AND cost_step.step_id = execution.task_step_id
                            WHERE cost_step.tenant_id = tr.tenant_id AND cost_step.task_id = tr.task_id
                       ), 0)) AS visible_captured_amount,
                       COALESCE((SELECT SUM(tt.estimated_point_cost)
                                   FROM dianlian_business.task_target tt
                                  WHERE tt.tenant_id = tr.tenant_id AND tt.task_id = tr.task_id), 0)
                           AS estimated_upper_bound
                  FROM dianlian_business.task_run tr
                  JOIN dianlian_business.point_reservation pr
                    ON pr.tenant_id = tr.tenant_id
                   AND pr.reservation_id = tr.point_reservation_id
                 WHERE tr.tenant_id = ?
                   AND EXISTS (
                       SELECT 1
                         FROM dianlian_business.task_participant participant
                        WHERE participant.tenant_id = tr.tenant_id
                          AND participant.task_id = tr.task_id
                          AND participant.user_id = ?
                          AND participant.status = 'ACTIVE'
                   )
                 ORDER BY tr.updated_at DESC, tr.task_id
                 LIMIT ?
                """,
                (resultSet, rowNum) -> {
                    var status = TaskStatus.valueOf(resultSet.getString("status"));
                    return new OfficeTaskSummary(
                            resultSet.getObject("task_id", UUID.class),
                            resultSet.getString("title"),
                            status,
                            TaskActionPolicy.displayStatus(status),
                            serializer.readUuidList(resultSet.getString("target_agent_ids")),
                            resultSet.getString("current_step_title"),
                            resultSet.getInt("completed_step_count"),
                            resultSet.getInt("total_step_count"),
                            new TaskPointSummary(
                                    resultSet.getLong("estimated_upper_bound"),
                                    Math.max(0, resultSet.getLong("reservation_amount")
                                            - resultSet.getLong("visible_captured_amount")
                                            - resultSet.getLong("released_amount")),
                                    resultSet.getLong("visible_captured_amount"),
                                    resultSet.getLong("released_amount"),
                                    Math.max(0, resultSet.getLong("reservation_amount")
                                            - resultSet.getLong("visible_captured_amount")
                                            - resultSet.getLong("released_amount"))
                            ),
                            resultSet.getTimestamp("updated_at").toInstant(),
                            TaskActionPolicy.allowedActions(status)
                    );
                },
                tenantId,
                actorId,
                limit
        );
    }

    private List<UUID> findTargetAgentIds(UUID tenantId, UUID taskId) {
        return jdbcTemplate.query(
                """
                SELECT enterprise_agent_id
                  FROM dianlian_business.task_target
                 WHERE tenant_id = ? AND task_id = ?
                 ORDER BY target_order
                """,
                (resultSet, rowNum) -> resultSet.getObject("enterprise_agent_id", UUID.class),
                tenantId,
                taskId
        );
    }

    private List<TaskSnapshot.StepView> findSteps(UUID tenantId, UUID taskId, int planVersion) {
        return jdbcTemplate.query(
                """
                SELECT step_id, step_key, title, status, responsible_type, responsible_id,
                       depends_on::text AS depends_on, output_contract, blocker_code
                  FROM dianlian_business.task_step
                 WHERE tenant_id = ? AND task_id = ? AND plan_version = ?
                 ORDER BY step_order
                """,
                (resultSet, rowNum) -> new TaskSnapshot.StepView(
                        resultSet.getObject("step_id", UUID.class),
                        resultSet.getString("step_key"),
                        resultSet.getString("title"),
                        resultSet.getString("status"),
                        resultSet.getString("responsible_type"),
                        resultSet.getObject("responsible_id", UUID.class),
                        serializer.readUuidList(resultSet.getString("depends_on")),
                        resultSet.getString("output_contract"),
                        resultSet.getString("blocker_code")
                ),
                tenantId,
                taskId,
                planVersion
        );
    }

    private TaskSnapshot.RuntimeRunSummary findActiveRun(UUID tenantId, UUID taskId) {
        var rows = jdbcTemplate.query(
                """
                SELECT execution.runtime_run_id, execution.task_step_id,
                       execution.execution_generation, execution.status, execution.operation_kind,
                       execution.started_at, execution.terminal_at
                  FROM dianlian_business.task_step_execution execution
                  JOIN dianlian_business.task_step step
                    ON step.tenant_id = execution.tenant_id AND step.step_id = execution.task_step_id
                 WHERE step.tenant_id = ? AND step.task_id = ?
                   AND execution.status IN ('PREPARED', 'RUNNING', 'RESPONSE_RECEIVED', 'PROVIDER_FAILED')
                 ORDER BY execution.updated_at DESC, execution.runtime_run_id
                 LIMIT 1
                """,
                (resultSet, rowNum) -> new TaskSnapshot.RuntimeRunSummary(
                        resultSet.getObject("runtime_run_id", UUID.class),
                        resultSet.getObject("task_step_id", UUID.class),
                        resultSet.getLong("execution_generation"),
                        resultSet.getString("status"),
                        resultSet.getString("operation_kind"),
                        null,
                        resultSet.getTimestamp("started_at") == null
                                ? null : resultSet.getTimestamp("started_at").toInstant(),
                        resultSet.getTimestamp("terminal_at") == null
                                ? null : resultSet.getTimestamp("terminal_at").toInstant()
                ),
                tenantId,
                taskId
        );
        return rows.isEmpty() ? null : rows.getFirst();
    }

    private List<ArtifactData> findArtifacts(UUID tenantId, UUID taskId) {
        return jdbcTemplate.query(
                """
                SELECT artifact_version_id, artifact_type, title, status, content_hash,
                       source_step_id, parent_artifact_version_id, content_text,
                       usage_estimated, created_at
                  FROM dianlian_business.task_artifact_version
                 WHERE tenant_id = ? AND task_id = ?
                 ORDER BY created_at, artifact_version_id
                """,
                (resultSet, rowNum) -> new ArtifactData(
                        new TaskSnapshot.ArtifactSummary(
                                resultSet.getObject("artifact_version_id", UUID.class),
                                resultSet.getString("artifact_type"),
                                resultSet.getString("title"),
                                resultSet.getString("status"),
                                resultSet.getString("content_hash"),
                                resultSet.getObject("source_step_id", UUID.class),
                                resultSet.getObject("parent_artifact_version_id", UUID.class),
                                resultSet.getTimestamp("created_at").toInstant()
                        ),
                        resultSet.getString("content_text"),
                        resultSet.getBoolean("usage_estimated")
                ),
                tenantId,
                taskId
        );
    }

    private static String blockerMessage(String blockerCode) {
        return switch (blockerCode) {
            case "HUMAN_CONFIRMATION_REQUIRED" -> "等待人工确认当前阶段成果";
            case "PROVIDER_OUTCOME_UNKNOWN" -> "模型调用结果未知，需人工或账单对账后处理";
            case "FINALIZATION_RETRY_PENDING" -> "任务结果正在重试入账与落库";
            case "EXECUTOR_TYPE_UNRESOLVED" -> "历史步骤执行器类型无法确认，已安全阻断";
            default -> blockerCode.startsWith("EXECUTOR_NOT_CONNECTED_")
                    ? "该步骤执行器尚未接入 V1 Worker"
                    : "任务当前被安全阻断";
        };
    }

    private List<TaskSnapshot.BusinessTraceItem> findBusinessTrace(UUID tenantId, UUID taskId) {
        return jdbcTemplate.query(
                """
                SELECT trace_item_id, trace_type, occurred_at, responsible_type,
                       responsible_id, summary, reference_ids::text AS reference_ids
                  FROM dianlian_business.task_business_trace
                 WHERE tenant_id = ? AND task_id = ?
                 ORDER BY occurred_at, trace_item_id
                """,
                (resultSet, rowNum) -> new TaskSnapshot.BusinessTraceItem(
                        resultSet.getObject("trace_item_id", UUID.class),
                        resultSet.getString("trace_type"),
                        resultSet.getTimestamp("occurred_at").toInstant(),
                        resultSet.getString("responsible_type"),
                        resultSet.getObject("responsible_id", UUID.class),
                        resultSet.getString("summary"),
                        serializer.readUuidList(resultSet.getString("reference_ids"))
                ),
                tenantId,
                taskId
        );
    }

    private SnapshotHeader mapSnapshotHeader(ResultSet resultSet) throws SQLException {
        return new SnapshotHeader(
                resultSet.getObject("task_id", UUID.class),
                resultSet.getLong("task_version"),
                resultSet.getString("title"),
                resultSet.getString("goal"),
                TaskStatus.valueOf(resultSet.getString("status")),
                resultSet.getInt("current_plan_version"),
                CollaborationMode.valueOf(resultSet.getString("collaboration_mode")),
                resultSet.getString("capability_code"),
                resultSet.getObject("primary_agent_id", UUID.class),
                resultSet.getObject("resume_event_id", UUID.class),
                resultSet.getTimestamp("updated_at").toInstant(),
                resultSet.getLong("estimated_upper_bound"),
                resultSet.getLong("reservation_amount"),
                resultSet.getLong("captured_amount"),
                resultSet.getLong("released_amount"),
                resultSet.getLong("visible_captured_amount")
        );
    }

    private record SnapshotHeader(
            UUID taskId,
            long taskVersion,
            String title,
            String goal,
            TaskStatus status,
            int planVersion,
            CollaborationMode collaborationMode,
            String capabilityCode,
            UUID primaryAgentId,
            UUID resumeEventId,
            java.time.Instant updatedAt,
            long estimatedUpperBound,
            long reservationAmount,
            long capturedAmount,
            long releasedAmount,
            long visibleCapturedAmount
    ) {
    }

    private record ArtifactData(
            TaskSnapshot.ArtifactSummary summary,
            String contentText,
            boolean usageEstimated
    ) {
    }
}

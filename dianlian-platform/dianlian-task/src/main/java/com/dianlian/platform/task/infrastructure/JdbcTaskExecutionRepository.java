package com.dianlian.platform.task.infrastructure;

import com.dianlian.platform.model.api.ModelChatResponse;
import com.dianlian.platform.model.api.ResolvedModelRoute;
import com.dianlian.platform.task.application.TaskExecutionRepository;
import com.dianlian.platform.task.application.TaskPayloadSerializer;
import com.dianlian.platform.task.application.TaskActionPolicy;
import com.dianlian.platform.task.api.TaskStatus;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.HexFormat;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcTaskExecutionRepository implements TaskExecutionRepository {

    private static final String VISIBILITY_VERSION = "task-participants:v1";

    private final JdbcTemplate jdbcTemplate;
    private final TaskPayloadSerializer serializer;

    public JdbcTaskExecutionRepository(JdbcTemplate jdbcTemplate, TaskPayloadSerializer serializer) {
        this.jdbcTemplate = jdbcTemplate;
        this.serializer = serializer;
    }

    @Override
    public Optional<ClaimedExecution> claimNext(String workerId, Instant now, Instant leaseUntil) {
        var candidates = jdbcTemplate.query(
                """
                SELECT execution.task_step_id, execution.execution_generation,
                       execution.runtime_run_id, execution.status, execution.lease_epoch,
                       step.task_id, step.responsible_type, step.responsible_id
                  FROM dianlian_business.task_step_execution execution
                  JOIN dianlian_business.task_step step
                    ON step.tenant_id = execution.tenant_id
                   AND step.step_id = execution.task_step_id
                  JOIN dianlian_business.task_run task
                    ON task.tenant_id = step.tenant_id AND task.task_id = step.task_id
                 WHERE step.executor_type = 'MODEL'
                   AND step.active_execution_generation = execution.execution_generation
                   AND step.active_runtime_run_id = execution.runtime_run_id
                   AND task.status NOT IN ('SUCCEEDED', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELLED')
                   AND (
                       (execution.status IN ('PREPARED', 'RESPONSE_RECEIVED', 'PROVIDER_FAILED')
                           AND execution.next_attempt_at <= ?
                           AND (execution.lease_until IS NULL OR execution.lease_until <= ?))
                       OR
                       (execution.status = 'RUNNING' AND execution.lease_until <= ?)
                   )
                 ORDER BY execution.next_attempt_at, execution.created_at, execution.runtime_run_id
                 LIMIT 1
                 FOR UPDATE OF execution SKIP LOCKED
                """,
                (resultSet, rowNum) -> new Candidate(
                        resultSet.getObject("task_step_id", UUID.class),
                        resultSet.getLong("execution_generation"),
                        resultSet.getObject("runtime_run_id", UUID.class),
                        resultSet.getString("status"),
                        resultSet.getLong("lease_epoch"),
                        resultSet.getObject("task_id", UUID.class),
                        resultSet.getString("responsible_type"),
                        resultSet.getObject("responsible_id", UUID.class)
                ),
                Timestamp.from(now),
                Timestamp.from(now),
                Timestamp.from(now)
        );
        if (candidates.isEmpty()) {
            return Optional.empty();
        }
        var candidate = candidates.getFirst();
        var claimedStatus = "PREPARED".equals(candidate.status()) ? "RUNNING" : candidate.status();
        var changed = jdbcTemplate.update(
                """
                UPDATE dianlian_business.task_step_execution
                   SET status = ?, lease_owner = ?, lease_until = ?, lease_epoch = lease_epoch + 1,
                       attempt_count = attempt_count + CASE WHEN status IN ('PREPARED', 'RUNNING') THEN 1 ELSE 0 END,
                       started_at = CASE WHEN status = 'PREPARED' THEN COALESCE(started_at, ?) ELSE started_at END,
                       updated_at = ?
                 WHERE task_step_id = ? AND execution_generation = ?
                   AND runtime_run_id = ? AND status = ? AND lease_epoch = ?
                """,
                claimedStatus,
                workerId,
                Timestamp.from(leaseUntil),
                Timestamp.from(now),
                Timestamp.from(now),
                candidate.taskStepId(),
                candidate.executionGeneration(),
                candidate.runtimeRunId(),
                candidate.status(),
                candidate.leaseEpoch()
        );
        requireSingleRow(changed, "Task execution claim lost its fence");
        if ("PREPARED".equals(candidate.status())) {
            requireSingleRow(jdbcTemplate.update(
                    """
                    UPDATE dianlian_business.task_step
                       SET status = 'RUNNING', blocker_code = NULL, updated_at = ?
                     WHERE step_id = ? AND active_runtime_run_id = ? AND status = 'READY'
                    """,
                    Timestamp.from(now),
                    candidate.taskStepId(),
                    candidate.runtimeRunId()
            ), "Claimed execution could not start its task step");
            insertTrace(
                    candidate.taskId(),
                    candidate.taskStepId(),
                    "STEP_STARTED",
                    "SYSTEM",
                    candidate.runtimeRunId(),
                    "MODEL step execution started",
                    List.of(candidate.runtimeRunId()),
                    now
            );
            updateTaskAndEvent(
                    candidate.taskId(),
                    "RUNNING",
                    "task.progress",
                    progressPayload(
                            candidate.taskId(),
                            candidate.taskStepId(),
                            "RUNNING",
                            candidate.responsibleType(),
                            candidate.responsibleId(),
                            "MODEL step execution started",
                            List.of()
                    ),
                    now
            );
        }
        return Optional.of(loadClaim(
                candidate.taskStepId(),
                candidate.executionGeneration(),
                workerId,
                candidate.leaseEpoch() + 1,
                candidate.status()
        ));
    }

    @Override
    public ClaimedExecution freezeRoute(ClaimedExecution execution, ResolvedModelRoute route, Instant now) {
        var changed = jdbcTemplate.update(
                """
                UPDATE dianlian_business.task_step_execution
                   SET model_route_binding_id = ?, model_route_state_version = ?,
                       model_definition_id = ?, model_reservation_ceiling = ?, updated_at = ?
                 WHERE task_step_id = ? AND execution_generation = ? AND runtime_run_id = ?
                   AND status = 'RUNNING' AND lease_owner = ? AND lease_epoch = ?
                   AND model_route_binding_id IS NULL
                """,
                route.routeBindingId(),
                route.routeStateVersion(),
                route.model().modelDefinitionId(),
                route.model().reservationCeilingMicroCredit(),
                Timestamp.from(now),
                execution.taskStepId(),
                execution.executionGeneration(),
                execution.runtimeRunId(),
                execution.leaseOwner(),
                execution.leaseEpoch()
        );
        requireSingleRow(changed, "Task execution model route could not be frozen");
        return loadClaim(
                execution.taskStepId(),
                execution.executionGeneration(),
                execution.leaseOwner(),
                execution.leaseEpoch(),
                execution.claimedFromStatus()
        );
    }

    @Override
    public ClaimedExecution recordProviderResponse(
            ClaimedExecution execution,
            ModelChatResponse response,
            long desiredCapturedAmount,
            boolean usageEstimated,
            Instant startedAt,
            Instant completedAt
    ) {
        var capturedAmount = lockAndCapTaskCapture(execution, desiredCapturedAmount);
        var changed = jdbcTemplate.update(
                """
                UPDATE dianlian_business.task_step_execution
                   SET status = 'RESPONSE_RECEIVED', provider_response_text = ?, provider_request_id = ?,
                       input_tokens = ?, output_tokens = ?, usage_status = ?, usage_estimated = ?,
                       captured_amount = ?, failure_code = NULL,
                       started_at = COALESCE(started_at, ?), updated_at = ?
                 WHERE task_step_id = ? AND execution_generation = ? AND runtime_run_id = ?
                   AND status = 'RUNNING' AND lease_owner = ? AND lease_epoch = ?
                """,
                response.text(),
                bounded(response.providerRequestId(), 256),
                response.inputTokens(),
                response.outputTokens(),
                usageEstimated ? "ESTIMATED" : "CONFIRMED",
                usageEstimated,
                capturedAmount,
                Timestamp.from(startedAt),
                Timestamp.from(completedAt),
                execution.taskStepId(),
                execution.executionGeneration(),
                execution.runtimeRunId(),
                execution.leaseOwner(),
                execution.leaseEpoch()
        );
        requireSingleRow(changed, "Stale task worker cannot persist a provider response");
        return loadClaim(
                execution.taskStepId(),
                execution.executionGeneration(),
                execution.leaseOwner(),
                execution.leaseEpoch(),
                execution.claimedFromStatus()
        );
    }

    @Override
    public ClaimedExecution recordProviderFailure(
            ClaimedExecution execution,
            String failureCode,
            long desiredCapturedAmount,
            boolean usageEstimated,
            Instant startedAt,
            Instant completedAt
    ) {
        var capturedAmount = lockAndCapTaskCapture(execution, desiredCapturedAmount);
        var changed = jdbcTemplate.update(
                """
                UPDATE dianlian_business.task_step_execution
                   SET status = 'PROVIDER_FAILED', provider_response_text = NULL,
                       input_tokens = 0, output_tokens = 0, usage_status = ?, usage_estimated = ?,
                       captured_amount = ?, failure_code = ?,
                       started_at = COALESCE(started_at, ?), updated_at = ?
                 WHERE task_step_id = ? AND execution_generation = ? AND runtime_run_id = ?
                   AND status = 'RUNNING' AND lease_owner = ? AND lease_epoch = ?
                """,
                usageEstimated ? "ESTIMATED" : "CONFIRMED",
                usageEstimated,
                capturedAmount,
                bounded(failureCode, 128),
                Timestamp.from(startedAt),
                Timestamp.from(completedAt),
                execution.taskStepId(),
                execution.executionGeneration(),
                execution.runtimeRunId(),
                execution.leaseOwner(),
                execution.leaseEpoch()
        );
        requireSingleRow(changed, "Stale task worker cannot persist a provider failure");
        return loadClaim(
                execution.taskStepId(),
                execution.executionGeneration(),
                execution.leaseOwner(),
                execution.leaseEpoch(),
                execution.claimedFromStatus()
        );
    }

    @Override
    public SettlementIntent finalizeSuccess(ClaimedExecution execution, Instant now) {
        lockExecution(execution, "RESPONSE_RECEIVED");
        var artifactVersionId = UUID.randomUUID();
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.task_artifact_version
                    (artifact_version_id, tenant_id, task_id, source_step_id, execution_generation,
                     artifact_type, title, status, content_text, content_hash,
                     usage_estimated, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'READY', ?, ?, ?, ?)
                ON CONFLICT (task_id, source_step_id, execution_generation) DO NOTHING
                """,
                artifactVersionId,
                execution.tenantId(),
                execution.taskId(),
                execution.taskStepId(),
                execution.executionGeneration(),
                defaultArtifactType(execution.desiredArtifactType()),
                artifactTitle(execution.stepTitle()),
                execution.providerResponseText(),
                hashText(execution.providerResponseText()),
                execution.usageEstimated(),
                Timestamp.from(now)
        );
        requireSingleRow(jdbcTemplate.update(
                """
                UPDATE dianlian_business.task_step_execution
                   SET status = 'SUCCEEDED', lease_owner = NULL, lease_until = NULL,
                       terminal_at = ?, updated_at = ?
                 WHERE task_step_id = ? AND execution_generation = ? AND runtime_run_id = ?
                   AND status = 'RESPONSE_RECEIVED' AND lease_owner = ? AND lease_epoch = ?
                """,
                Timestamp.from(now),
                Timestamp.from(now),
                execution.taskStepId(),
                execution.executionGeneration(),
                execution.runtimeRunId(),
                execution.leaseOwner(),
                execution.leaseEpoch()
        ), "Task execution success lost its fence");
        requireSingleRow(jdbcTemplate.update(
                """
                UPDATE dianlian_business.task_step
                   SET status = 'SUCCEEDED', blocker_code = NULL, updated_at = ?
                 WHERE tenant_id = ? AND step_id = ? AND active_runtime_run_id = ? AND status = 'RUNNING'
                """,
                Timestamp.from(now),
                execution.tenantId(),
                execution.taskStepId(),
                execution.runtimeRunId()
        ), "Task step could not accept its successful execution");
        insertTrace(execution.taskId(), execution.taskStepId(), "STEP_COMPLETED", "AGENT",
                execution.enterpriseAgentId(), "MODEL step completed", List.of(execution.runtimeRunId()), now);
        insertTrace(execution.taskId(), execution.taskStepId(), "ARTIFACT_CREATED", "AGENT",
                execution.enterpriseAgentId(), "Stage artifact created", List.of(artifactVersionId), now);
        insertTrace(execution.taskId(), execution.taskStepId(), "COST_UPDATED", "SYSTEM",
                execution.runtimeRunId(), execution.usageEstimated()
                        ? "Model usage estimated conservatively" : "Confirmed model usage recorded",
                List.of(execution.runtimeRunId()), now);
        activateEligibleSuccessors(execution.tenantId(), execution.taskId(), now);
        var outcome = deriveTaskOutcome(execution.tenantId(), execution.taskId());
        var eventType = eventType(outcome.status());
        updateTaskAndEvent(
                execution.taskId(),
                outcome.status(),
                eventType,
                outcomePayload(
                        execution,
                        outcome,
                        "SUCCEEDED",
                        artifactVersionId,
                        null
                ),
                now
        );
        return settlementIntent(execution, outcome);
    }

    @Override
    public SettlementIntent finalizeFailure(ClaimedExecution execution, Instant now) {
        lockExecution(execution, "PROVIDER_FAILED");
        var outcomeUnknown = "PROVIDER_OUTCOME_UNKNOWN".equals(execution.failureCode());
        var executionStatus = outcomeUnknown ? "BLOCKED_SIDE_EFFECT_RECONCILIATION" : "FAILED_PROVIDER";
        var stepStatus = outcomeUnknown ? "BLOCKED_SIDE_EFFECT_RECONCILIATION" : "FAILED_FINAL";
        requireSingleRow(jdbcTemplate.update(
                """
                UPDATE dianlian_business.task_step_execution
                   SET status = ?, lease_owner = NULL, lease_until = NULL, terminal_at = ?, updated_at = ?
                 WHERE task_step_id = ? AND execution_generation = ? AND runtime_run_id = ?
                   AND status = 'PROVIDER_FAILED' AND lease_owner = ? AND lease_epoch = ?
                """,
                executionStatus,
                Timestamp.from(now),
                Timestamp.from(now),
                execution.taskStepId(),
                execution.executionGeneration(),
                execution.runtimeRunId(),
                execution.leaseOwner(),
                execution.leaseEpoch()
        ), "Task execution failure lost its fence");
        requireSingleRow(jdbcTemplate.update(
                """
                UPDATE dianlian_business.task_step
                   SET status = ?, blocker_code = ?, updated_at = ?
                 WHERE tenant_id = ? AND step_id = ? AND active_runtime_run_id = ? AND status = 'RUNNING'
                """,
                stepStatus,
                execution.failureCode(),
                Timestamp.from(now),
                execution.tenantId(),
                execution.taskStepId(),
                execution.runtimeRunId()
        ), "Task step could not accept its failed execution");
        insertTrace(execution.taskId(), execution.taskStepId(), "FAILURE", "SYSTEM",
                execution.runtimeRunId(), "MODEL step failed: " + execution.failureCode(),
                List.of(execution.runtimeRunId()), now);
        if (!outcomeUnknown) {
            skipFailedDependents(execution.tenantId(), execution.taskId(), now);
        }
        var outcome = deriveTaskOutcome(execution.tenantId(), execution.taskId());
        updateTaskAndEvent(
                execution.taskId(),
                outcome.status(),
                eventType(outcome.status()),
                outcomePayload(
                        execution,
                        outcome,
                        stepStatus,
                        null,
                        execution.failureCode()
                ),
                now
        );
        return settlementIntent(execution, outcome);
    }

    @Override
    public void deferFinalization(
            ClaimedExecution execution,
            Instant nextAttemptAt,
            String blockerCode,
            Instant now
    ) {
        var changed = jdbcTemplate.update(
                """
                UPDATE dianlian_business.task_step_execution
                   SET lease_owner = NULL, lease_until = NULL, next_attempt_at = ?, updated_at = ?
                 WHERE task_step_id = ? AND execution_generation = ? AND runtime_run_id = ?
                   AND status IN ('RESPONSE_RECEIVED', 'PROVIDER_FAILED')
                   AND lease_owner = ? AND lease_epoch = ?
                """,
                Timestamp.from(nextAttemptAt),
                Timestamp.from(now),
                execution.taskStepId(),
                execution.executionGeneration(),
                execution.runtimeRunId(),
                execution.leaseOwner(),
                execution.leaseEpoch()
        );
        if (changed == 1) {
            jdbcTemplate.update(
                    """
                    UPDATE dianlian_business.task_step
                       SET blocker_code = ?, updated_at = ?
                     WHERE tenant_id = ? AND step_id = ? AND active_runtime_run_id = ?
                    """,
                    blockerCode,
                    Timestamp.from(now),
                    execution.tenantId(),
                    execution.taskStepId(),
                    execution.runtimeRunId()
            );
        }
    }

    private ClaimedExecution loadClaim(
            UUID taskStepId,
            long executionGeneration,
            String leaseOwner,
            long leaseEpoch,
            String claimedFromStatus
    ) {
        var rows = jdbcTemplate.query(
                """
                SELECT execution.runtime_run_id, execution.tenant_id, step.task_id,
                       execution.task_step_id, execution.execution_generation, execution.status,
                       execution.lease_owner, execution.lease_epoch,
                       task.owner_user_id, step.responsible_id,
                       (profile.agent ->> 'agentVersionId')::UUID AS agent_version_id,
                       (profile.agent ->> 'configurationVersionId')::UUID AS configuration_version_id,
                       profile.agent ->> 'roleName' AS role_name,
                       profile.agent ->> 'profile' AS platform_profile,
                       profile.agent ->> 'enterpriseInstructions' AS enterprise_instructions,
                       profile.agent ->> 'modelPolicyMode' AS model_policy_mode,
                       profile.agent ->> 'knowledgeScopeMode' AS knowledge_scope_mode,
                       task.goal, step.title, step.output_contract,
                       input.input_payload ->> 'desiredArtifactType' AS desired_artifact_type,
                       input.input_payload::TEXT AS input_snapshot_json,
                       dependencies.content AS dependency_artifacts,
                       task.point_reservation_id,
                       execution.model_route_binding_id, execution.model_route_state_version,
                       execution.model_definition_id, execution.model_reservation_ceiling,
                       execution.provider_response_text, execution.input_tokens, execution.output_tokens,
                       execution.usage_estimated, execution.captured_amount, execution.failure_code
                  FROM dianlian_business.task_step_execution execution
                  JOIN dianlian_business.task_step step
                    ON step.tenant_id = execution.tenant_id AND step.step_id = execution.task_step_id
                  JOIN dianlian_business.task_run task
                    ON task.tenant_id = step.tenant_id AND task.task_id = step.task_id
                  JOIN dianlian_business.execution_plan_version plan
                    ON plan.tenant_id = task.tenant_id AND plan.task_id = task.task_id
                   AND plan.plan_version = task.current_plan_version AND plan.status = 'ACTIVE'
                  JOIN dianlian_business.task_input_snapshot input
                    ON input.tenant_id = task.tenant_id AND input.task_id = task.task_id
                   AND input.plan_version = task.current_plan_version
                  JOIN LATERAL (
                       SELECT profile_agent.agent
                         FROM jsonb_array_elements(plan.execution_profile_snapshot -> 'agents')
                              AS profile_agent(agent)
                        WHERE profile_agent.agent ->> 'enterpriseAgentId' = step.responsible_id::TEXT
                        LIMIT 1
                  ) profile ON TRUE
                  LEFT JOIN LATERAL (
                       SELECT string_agg(artifact.content_text, E'\n\n---\n\n' ORDER BY artifact.created_at)
                                  AS content
                         FROM jsonb_array_elements_text(step.depends_on) dependency(step_id)
                         JOIN dianlian_business.task_artifact_version artifact
                           ON artifact.tenant_id = step.tenant_id
                          AND artifact.source_step_id = dependency.step_id::UUID
                          AND artifact.status = 'READY'
                  ) dependencies ON TRUE
                 WHERE execution.task_step_id = ? AND execution.execution_generation = ?
                   AND execution.lease_owner = ? AND execution.lease_epoch = ?
                """,
                (resultSet, rowNum) -> mapClaim(resultSet, claimedFromStatus),
                taskStepId,
                executionGeneration,
                leaseOwner,
                leaseEpoch
        );
        if (rows.size() != 1) {
            throw new IllegalStateException("Claimed task execution snapshot is missing or ambiguous");
        }
        return rows.getFirst();
    }

    private ClaimedExecution mapClaim(ResultSet resultSet, String claimedFromStatus) throws SQLException {
        return new ClaimedExecution(
                resultSet.getObject("runtime_run_id", UUID.class),
                resultSet.getObject("tenant_id", UUID.class),
                resultSet.getObject("task_id", UUID.class),
                resultSet.getObject("task_step_id", UUID.class),
                resultSet.getLong("execution_generation"),
                claimedFromStatus,
                resultSet.getString("status"),
                resultSet.getString("lease_owner"),
                resultSet.getLong("lease_epoch"),
                resultSet.getObject("owner_user_id", UUID.class),
                resultSet.getObject("responsible_id", UUID.class),
                resultSet.getObject("agent_version_id", UUID.class),
                resultSet.getObject("configuration_version_id", UUID.class),
                resultSet.getString("role_name"),
                resultSet.getString("platform_profile"),
                resultSet.getString("enterprise_instructions"),
                resultSet.getString("model_policy_mode"),
                resultSet.getString("knowledge_scope_mode"),
                resultSet.getString("goal"),
                resultSet.getString("title"),
                resultSet.getString("output_contract"),
                resultSet.getString("desired_artifact_type"),
                resultSet.getString("input_snapshot_json"),
                resultSet.getString("dependency_artifacts"),
                resultSet.getObject("point_reservation_id", UUID.class),
                resultSet.getObject("model_route_binding_id", UUID.class),
                resultSet.getObject("model_route_state_version", Long.class),
                resultSet.getObject("model_definition_id", UUID.class),
                resultSet.getObject("model_reservation_ceiling", Long.class),
                resultSet.getString("provider_response_text"),
                resultSet.getInt("input_tokens"),
                resultSet.getInt("output_tokens"),
                resultSet.getBoolean("usage_estimated"),
                resultSet.getLong("captured_amount"),
                resultSet.getString("failure_code")
        );
    }

    private long lockAndCapTaskCapture(ClaimedExecution execution, long desiredCapturedAmount) {
        if (desiredCapturedAmount < 0) {
            throw new IllegalArgumentException("desiredCapturedAmount cannot be negative");
        }
        var tasks = jdbcTemplate.query(
                """
                SELECT point_reservation_id
                  FROM dianlian_business.task_run
                 WHERE tenant_id = ? AND task_id = ?
                 FOR UPDATE
                """,
                (resultSet, rowNum) -> resultSet.getObject("point_reservation_id", UUID.class),
                execution.tenantId(),
                execution.taskId()
        );
        if (tasks.size() != 1 || !tasks.getFirst().equals(execution.pointReservationId())) {
            throw new IllegalStateException("Task point reservation changed during execution");
        }
        var budgetRows = jdbcTemplate.query(
                """
                SELECT reservation.amount - reservation.captured_amount - reservation.released_amount
                           - COALESCE((
                               SELECT SUM(other.captured_amount)
                                 FROM dianlian_business.task_step_execution other
                                 JOIN dianlian_business.task_step other_step
                                   ON other_step.tenant_id = other.tenant_id
                                  AND other_step.step_id = other.task_step_id
                                WHERE other_step.tenant_id = task.tenant_id
                                  AND other_step.task_id = task.task_id
                                  AND other.runtime_run_id <> ?
                           ), 0) AS remaining
                  FROM dianlian_business.task_run task
                  JOIN dianlian_business.point_reservation reservation
                    ON reservation.tenant_id = task.tenant_id
                   AND reservation.reservation_id = task.point_reservation_id
                 WHERE task.tenant_id = ? AND task.task_id = ?
                """,
                (resultSet, rowNum) -> resultSet.getLong("remaining"),
                execution.runtimeRunId(),
                execution.tenantId(),
                execution.taskId()
        );
        if (budgetRows.size() != 1) {
            throw new IllegalStateException("Task capture budget is unavailable");
        }
        var available = Math.max(0, budgetRows.getFirst());
        if (desiredCapturedAmount > 0 && available == 0) {
            throw new IllegalStateException("Task reservation has no remaining capture budget");
        }
        return Math.min(desiredCapturedAmount, available);
    }

    private void lockExecution(ClaimedExecution execution, String expectedStatus) {
        var rows = jdbcTemplate.query(
                """
                SELECT runtime_run_id
                  FROM dianlian_business.task_step_execution
                 WHERE task_step_id = ? AND execution_generation = ? AND runtime_run_id = ?
                   AND status = ? AND lease_owner = ? AND lease_epoch = ?
                 FOR UPDATE
                """,
                (resultSet, rowNum) -> resultSet.getObject("runtime_run_id", UUID.class),
                execution.taskStepId(),
                execution.executionGeneration(),
                execution.runtimeRunId(),
                expectedStatus,
                execution.leaseOwner(),
                execution.leaseEpoch()
        );
        if (rows.size() != 1) {
            throw new IllegalStateException("Task execution finalization lost its fence");
        }
    }

    private void activateEligibleSuccessors(UUID tenantId, UUID taskId, Instant now) {
        var candidates = jdbcTemplate.query(
                """
                SELECT candidate.step_id, candidate.executor_type
                  FROM dianlian_business.task_step candidate
                 WHERE candidate.tenant_id = ? AND candidate.task_id = ? AND candidate.status = 'PENDING'
                   AND NOT EXISTS (
                       SELECT 1
                         FROM jsonb_array_elements_text(candidate.depends_on) dependency(step_id)
                         JOIN dianlian_business.task_step predecessor
                           ON predecessor.tenant_id = candidate.tenant_id
                          AND predecessor.step_id = dependency.step_id::UUID
                        WHERE predecessor.status <> 'SUCCEEDED'
                   )
                 ORDER BY candidate.step_order
                 FOR UPDATE
                """,
                (resultSet, rowNum) -> new Successor(
                        resultSet.getObject("step_id", UUID.class),
                        resultSet.getString("executor_type")
                ),
                tenantId,
                taskId
        );
        for (var candidate : candidates) {
            if ("MODEL".equals(candidate.executorType())) {
                createPreparedExecution(tenantId, taskId, candidate.stepId(), now);
            } else {
                var blockerCode = "HUMAN_CHECKPOINT".equals(candidate.executorType())
                        ? "HUMAN_CONFIRMATION_REQUIRED"
                        : "EXECUTOR_NOT_CONNECTED_" + candidate.executorType();
                jdbcTemplate.update(
                        """
                        UPDATE dianlian_business.task_step
                           SET status = 'WAITING_EXTERNAL', blocker_code = ?, updated_at = ?
                         WHERE tenant_id = ? AND step_id = ? AND status = 'PENDING'
                        """,
                        blockerCode,
                        Timestamp.from(now),
                        tenantId,
                        candidate.stepId()
                );
            }
        }
    }

    private void createPreparedExecution(UUID tenantId, UUID taskId, UUID stepId, Instant now) {
        var generation = jdbcTemplate.queryForObject(
                """
                SELECT COALESCE(MAX(execution_generation), 0) + 1
                  FROM dianlian_business.task_step_execution
                 WHERE task_step_id = ?
                """,
                Long.class,
                stepId
        );
        var runtimeRunId = UUID.randomUUID();
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.task_step_execution
                    (task_step_id, tenant_id, execution_generation, runtime_run_id, status,
                     idempotency_key, request_hash, next_attempt_at, created_at, updated_at)
                SELECT ?, ?, ?, ?, 'PREPARED', ?, input.request_hash, ?, ?, ?
                  FROM dianlian_business.task_input_snapshot input
                 WHERE input.tenant_id = ? AND input.task_id = ?
                   AND input.plan_version = (
                       SELECT current_plan_version FROM dianlian_business.task_run WHERE task_id = ?
                   )
                """,
                stepId,
                tenantId,
                generation,
                runtimeRunId,
                "task-step:" + taskId + ":" + stepId + ":" + generation,
                Timestamp.from(now),
                Timestamp.from(now),
                Timestamp.from(now),
                tenantId,
                taskId,
                taskId
        );
        requireSingleRow(jdbcTemplate.update(
                """
                UPDATE dianlian_business.task_step
                   SET status = 'READY', blocker_code = NULL, active_execution_generation = ?,
                       active_runtime_run_id = ?, updated_at = ?
                 WHERE tenant_id = ? AND step_id = ? AND status = 'PENDING' AND executor_type = 'MODEL'
                """,
                generation,
                runtimeRunId,
                Timestamp.from(now),
                tenantId,
                stepId
        ), "MODEL successor could not bind its prepared execution");
    }

    private void skipFailedDependents(UUID tenantId, UUID taskId, Instant now) {
        int changed;
        do {
            changed = jdbcTemplate.update(
                    """
                    UPDATE dianlian_business.task_step candidate
                       SET status = 'SKIPPED', blocker_code = 'DEPENDENCY_FAILED', updated_at = ?
                     WHERE candidate.tenant_id = ? AND candidate.task_id = ? AND candidate.status = 'PENDING'
                       AND EXISTS (
                           SELECT 1
                             FROM jsonb_array_elements_text(candidate.depends_on) dependency(step_id)
                             JOIN dianlian_business.task_step predecessor
                               ON predecessor.tenant_id = candidate.tenant_id
                              AND predecessor.step_id = dependency.step_id::UUID
                            WHERE predecessor.status IN ('FAILED_FINAL', 'SKIPPED',
                                                         'BLOCKED_SIDE_EFFECT_RECONCILIATION')
                       )
                    """,
                    Timestamp.from(now),
                    tenantId,
                    taskId
            );
        } while (changed > 0);
    }

    private TaskOutcome deriveTaskOutcome(UUID tenantId, UUID taskId) {
        var rows = jdbcTemplate.query(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status IN ('READY', 'RUNNING', 'RETRY_WAIT')) AS active,
                       COUNT(*) FILTER (WHERE status = 'PENDING') AS pending,
                       COUNT(*) FILTER (WHERE status = 'WAITING_EXTERNAL'
                           AND executor_type = 'HUMAN_CHECKPOINT') AS waiting_human,
                       COUNT(*) FILTER (WHERE status = 'WAITING_EXTERNAL'
                           AND executor_type <> 'HUMAN_CHECKPOINT') AS waiting_external,
                       COUNT(*) FILTER (WHERE status = 'FAILED_FINAL') AS failed,
                       COUNT(*) FILTER (WHERE status = 'BLOCKED_SIDE_EFFECT_RECONCILIATION') AS blocked,
                       COUNT(*) FILTER (WHERE status = 'SUCCEEDED') AS succeeded
                  FROM dianlian_business.task_step
                 WHERE tenant_id = ? AND task_id = ?
                   AND plan_version = (
                       SELECT current_plan_version
                         FROM dianlian_business.task_run
                        WHERE tenant_id = ? AND task_id = ?
                   )
                """,
                (resultSet, rowNum) -> new StepCounts(
                        resultSet.getLong("total"),
                        resultSet.getLong("active"),
                        resultSet.getLong("pending"),
                        resultSet.getLong("waiting_human"),
                        resultSet.getLong("waiting_external"),
                        resultSet.getLong("failed"),
                        resultSet.getLong("blocked"),
                        resultSet.getLong("succeeded")
                ),
                tenantId,
                taskId,
                tenantId,
                taskId
        );
        if (rows.size() != 1 || rows.getFirst().total() == 0) {
            throw new IllegalStateException("Task execution plan is unavailable");
        }
        var counts = rows.getFirst();
        if (counts.active() > 0) return new TaskOutcome("RUNNING", false);
        if (counts.blocked() > 0) {
            return new TaskOutcome("PAUSED", false);
        }
        if (counts.waitingExternal() > 0 || counts.pending() > 0) {
            return new TaskOutcome("PAUSED", false);
        }
        if (counts.waitingHuman() > 0) return new TaskOutcome("WAITING_CONFIRMATION", false);
        if (counts.failed() > 0) {
            return new TaskOutcome(counts.succeeded() > 0 ? "PARTIAL_SUCCESS" : "FAILED", true);
        }
        if (counts.succeeded() == counts.total()) return new TaskOutcome("SUCCEEDED", true);
        return new TaskOutcome("PAUSED", false);
    }

    private SettlementIntent settlementIntent(ClaimedExecution execution, TaskOutcome outcome) {
        if (!outcome.settle() || !settlementAllowed(outcome.status())) {
            return SettlementIntent.none();
        }
        var captured = jdbcTemplate.queryForObject(
                """
                SELECT COALESCE(SUM(candidate.captured_amount), 0)
                  FROM dianlian_business.task_step_execution candidate
                  JOIN dianlian_business.task_step step
                    ON step.tenant_id = candidate.tenant_id AND step.step_id = candidate.task_step_id
                 WHERE step.tenant_id = ? AND step.task_id = ?
                """,
                Long.class,
                execution.tenantId(),
                execution.taskId()
        );
        var capturedAmount = captured == null ? 0 : captured;
        var reasonCode = "TASK_" + outcome.status();
        return new SettlementIntent(
                true,
                execution.tenantId(),
                execution.requestedBy(),
                execution.pointReservationId(),
                capturedAmount,
                "task-settlement:" + execution.taskId(),
                hashText(
                        execution.taskId() + ":" + capturedAmount + ":" + reasonCode
                ),
                reasonCode
        );
    }

    private void updateTaskAndEvent(
            UUID taskId,
            String status,
            String eventType,
            Map<String, ?> details,
            Instant now
    ) {
        var eventId = UUID.randomUUID();
        var updates = jdbcTemplate.query(
                """
                UPDATE dianlian_business.task_run
                   SET status = ?, task_version = task_version + 1, resume_event_id = ?, updated_at = ?
                 WHERE task_id = ?
                RETURNING tenant_id, task_version
                """,
                (resultSet, rowNum) -> new TaskUpdate(
                        resultSet.getObject("tenant_id", UUID.class),
                        resultSet.getLong("task_version")
                ),
                status,
                eventId,
                Timestamp.from(now),
                taskId
        );
        if (updates.size() != 1) {
            throw new IllegalStateException("Task state could not be versioned");
        }
        var update = updates.getFirst();
        var payloadJson = serializer.serialize(details);
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.task_event
                    (event_id, tenant_id, task_id, task_version, event_type, visibility_version,
                     trace_id, payload, occurred_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CAST(? AS JSONB), ?)
                """,
                eventId,
                update.tenantId(),
                taskId,
                update.taskVersion(),
                eventType,
                VISIBILITY_VERSION,
                eventId,
                payloadJson,
                Timestamp.from(now)
        );
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.outbox_event
                    (event_id, tenant_id, aggregate_type, aggregate_id, event_type, payload, occurred_at)
                VALUES (?, ?, 'TASK', ?, ?, CAST(? AS JSONB), ?)
                """,
                eventId,
                update.tenantId(),
                taskId,
                eventType,
                payloadJson,
                Timestamp.from(now)
        );
    }

    private void insertTrace(
            UUID taskId,
            UUID stepId,
            String traceType,
            String responsibleType,
            UUID responsibleId,
            String summary,
            List<UUID> referenceIds,
            Instant occurredAt
    ) {
        var tenants = jdbcTemplate.query(
                "SELECT tenant_id FROM dianlian_business.task_run WHERE task_id = ?",
                (resultSet, rowNum) -> resultSet.getObject("tenant_id", UUID.class),
                taskId
        );
        if (tenants.size() != 1) {
            throw new IllegalStateException("Task trace tenant is unavailable");
        }
        var refs = new ArrayList<>(referenceIds);
        if (!refs.contains(stepId)) refs.addFirst(stepId);
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.task_business_trace
                    (trace_item_id, tenant_id, task_id, trace_type, responsible_type,
                     responsible_id, summary, reference_ids, occurred_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CAST(? AS JSONB), ?)
                """,
                UUID.randomUUID(),
                tenants.getFirst(),
                taskId,
                traceType,
                responsibleType,
                responsibleId,
                summary,
                serializer.serialize(refs),
                Timestamp.from(occurredAt)
        );
    }

    private static String defaultArtifactType(String artifactType) {
        return artifactType == null || artifactType.isBlank() ? "STAGE_TEXT" : artifactType;
    }

    private static String artifactTitle(String stepTitle) {
        var suffix = " 阶段成果";
        var maxStepLength = 200 - suffix.length();
        return (stepTitle.length() <= maxStepLength ? stepTitle : stepTitle.substring(0, maxStepLength)) + suffix;
    }

    private static String bounded(String value, int maxLength) {
        return value == null || value.length() <= maxLength ? value : value.substring(0, maxLength);
    }

    private static String hashText(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is required", exception);
        }
    }

    private static String eventType(String status) {
        return switch (status) {
            case "SUCCEEDED", "PARTIAL_SUCCESS" -> "task.completed";
            case "FAILED" -> "task.failed";
            case "WAITING_CONFIRMATION" -> "checkpoint.required";
            case "PAUSED" -> "task.paused";
            default -> "task.progress";
        };
    }

    private Map<String, Object> outcomePayload(
            ClaimedExecution execution,
            TaskOutcome outcome,
            String stepStatus,
            UUID artifactVersionId,
            String failureCode
    ) {
        var eventType = eventType(outcome.status());
        if ("task.progress".equals(eventType)) {
            return progressPayload(
                    execution.taskId(),
                    execution.taskStepId(),
                    stepStatus,
                    "AGENT",
                    execution.enterpriseAgentId(),
                    failureCode == null ? "MODEL step completed" : "MODEL step failed: " + failureCode,
                    artifactVersionId == null ? List.of() : List.of(artifactVersionId)
            );
        }
        if ("checkpoint.required".equals(eventType)) {
            return checkpointPayload(execution.tenantId(), execution.taskId());
        }
        return lifecyclePayload(execution.taskId(), outcome.status(), failureCode);
    }

    private Map<String, Object> progressPayload(
            UUID taskId,
            UUID stepId,
            String stepStatus,
            String responsibleType,
            UUID responsibleId,
            String summary,
            List<UUID> artifactVersionIds
    ) {
        var payload = new LinkedHashMap<String, Object>();
        payload.put("taskId", taskId);
        payload.put("stepId", stepId);
        payload.put("stepStatus", stepStatus);
        payload.put("responsibleType", responsibleType);
        payload.put("responsibleId", responsibleId);
        payload.put("summary", summary);
        if (!artifactVersionIds.isEmpty()) payload.put("artifactVersionIds", artifactVersionIds);
        payload.put("allowedActions", TaskActionPolicy.allowedActions(TaskStatus.RUNNING));
        return payload;
    }

    private Map<String, Object> checkpointPayload(UUID tenantId, UUID taskId) {
        var rows = jdbcTemplate.query(
                """
                SELECT step_id, title
                  FROM dianlian_business.task_step
                 WHERE tenant_id = ? AND task_id = ? AND status = 'WAITING_EXTERNAL'
                   AND executor_type = 'HUMAN_CHECKPOINT'
                 ORDER BY step_order
                 LIMIT 1
                """,
                (resultSet, rowNum) -> Map.<String, Object>of(
                        "taskId", taskId,
                        "checkpointId", resultSet.getObject("step_id", UUID.class),
                        "checkpointType", "CONFIRMATION",
                        "status", "OPEN",
                        "prompt", resultSet.getString("title"),
                        "allowedActions", TaskActionPolicy.allowedActions(TaskStatus.WAITING_CONFIRMATION)
                ),
                tenantId,
                taskId
        );
        if (rows.size() != 1) {
            throw new IllegalStateException("WAITING_CONFIRMATION task has no visible checkpoint step");
        }
        return rows.getFirst();
    }

    private Map<String, Object> lifecyclePayload(UUID taskId, String status, String failureCode) {
        var taskStatus = TaskStatus.valueOf(status);
        var payload = new LinkedHashMap<String, Object>();
        payload.put("taskId", taskId);
        payload.put("taskStatus", taskStatus);
        if ("PAUSED".equals(status) && failureCode != null) payload.put("blockerCode", failureCode);
        if (("FAILED".equals(status) || "PARTIAL_SUCCESS".equals(status)) && failureCode != null) {
            payload.put("failureCode", failureCode);
        }
        payload.put("allowedActions", TaskActionPolicy.allowedActions(taskStatus));
        return payload;
    }

    static boolean settlementAllowed(String status) {
        return switch (status) {
            case "SUCCEEDED", "PARTIAL_SUCCESS", "FAILED", "CANCELLED" -> true;
            default -> false;
        };
    }

    private static void requireSingleRow(int changed, String message) {
        if (changed != 1) throw new IllegalStateException(message);
    }

    private record Candidate(
            UUID taskStepId,
            long executionGeneration,
            UUID runtimeRunId,
            String status,
            long leaseEpoch,
            UUID taskId,
            String responsibleType,
            UUID responsibleId
    ) {
    }

    private record Successor(UUID stepId, String executorType) {
    }

    private record StepCounts(
            long total,
            long active,
            long pending,
            long waitingHuman,
            long waitingExternal,
            long failed,
            long blocked,
            long succeeded
    ) {
    }

    private record TaskOutcome(String status, boolean settle) {
    }

    private record TaskUpdate(UUID tenantId, long taskVersion) {
    }
}

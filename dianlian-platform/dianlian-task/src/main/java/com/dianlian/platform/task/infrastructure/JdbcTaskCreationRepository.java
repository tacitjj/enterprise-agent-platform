package com.dianlian.platform.task.infrastructure;

import com.dianlian.platform.task.api.IdempotencyRequestConflictException;
import com.dianlian.platform.task.api.TaskCommandAccepted;
import com.dianlian.platform.task.api.TaskStatus;
import com.dianlian.platform.task.application.IdempotencyDecision;
import com.dianlian.platform.task.application.TaskCreation;
import com.dianlian.platform.task.application.TaskCreationRepository;
import com.dianlian.platform.task.application.TaskActionPolicy;
import com.dianlian.platform.task.application.TaskPayloadSerializer;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcTaskCreationRepository implements TaskCreationRepository {

    private static final String OPERATION = "TASK_CREATE";
    private static final Duration IDEMPOTENCY_RETENTION = Duration.ofHours(24);

    private final JdbcTemplate jdbcTemplate;
    private final TaskPayloadSerializer serializer;

    public JdbcTaskCreationRepository(JdbcTemplate jdbcTemplate, TaskPayloadSerializer serializer) {
        this.jdbcTemplate = jdbcTemplate;
        this.serializer = serializer;
    }

    @Override
    public IdempotencyDecision claim(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey,
            String requestHash,
            Instant occurredAt
    ) {
        var inserted = jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.idempotency_record
                    (tenant_id, actor_id, operation, idempotency_key, request_hash,
                     created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (tenant_id, actor_id, operation, idempotency_key) DO NOTHING
                """,
                tenantId,
                actorId,
                OPERATION,
                idempotencyKey,
                requestHash,
                Timestamp.from(occurredAt),
                Timestamp.from(occurredAt.plus(IDEMPOTENCY_RETENTION))
        );
        if (inserted == 1) {
            return IdempotencyDecision.newClaim();
        }

        var records = jdbcTemplate.query(
                """
                SELECT request_hash,
                       response_payload ->> 'taskId' AS task_id,
                       response_payload ->> 'taskVersion' AS task_version,
                       response_payload ->> 'status' AS status,
                       response_payload ->> 'acceptedAt' AS accepted_at,
                       response_payload ->> 'statusUrl' AS status_url,
                       response_payload ->> 'eventsUrl' AS events_url,
                       response_payload ->> 'resumeEventId' AS resume_event_id,
                       completed_at
                  FROM dianlian_business.idempotency_record
                 WHERE tenant_id = ? AND actor_id = ? AND operation = ? AND idempotency_key = ?
                 FOR UPDATE
                """,
                (resultSet, rowNum) -> {
                    var completedAt = resultSet.getTimestamp("completed_at");
                    TaskCommandAccepted response = null;
                    if (completedAt != null) {
                        response = new TaskCommandAccepted(
                                UUID.fromString(resultSet.getString("task_id")),
                                Long.parseLong(resultSet.getString("task_version")),
                                TaskStatus.valueOf(resultSet.getString("status")),
                                Instant.parse(resultSet.getString("accepted_at")),
                                resultSet.getString("status_url"),
                                resultSet.getString("events_url"),
                                UUID.fromString(resultSet.getString("resume_event_id")),
                                true
                        );
                    }
                    return new ExistingIdempotency(resultSet.getString("request_hash"), response);
                },
                tenantId,
                actorId,
                OPERATION,
                idempotencyKey
        );
        if (records.isEmpty()) {
            throw new IllegalStateException("Idempotency record disappeared after a uniqueness conflict");
        }
        var existing = records.getFirst();
        if (!existing.requestHash().equals(requestHash)) {
            throw new IdempotencyRequestConflictException();
        }
        if (existing.response() == null) {
            throw new IllegalStateException("Idempotency record is incomplete");
        }
        return IdempotencyDecision.replay(existing.response());
    }

    @Override
    public void insert(TaskCreation creation) {
        insertTask(creation);
        insertPlan(creation);
        insertSteps(creation);
        insertInitialExecutions(creation);
        insertParticipant(creation);
        insertTargets(creation);
        insertInputSnapshot(creation);
        insertBusinessTrace(creation);
        insertOutbox(creation);
        completeIdempotency(creation);
    }

    private void insertTask(TaskCreation creation) {
        var command = creation.command();
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.task_run
                    (task_id, tenant_id, task_version, title, goal, status, current_plan_version,
                     collaboration_mode, capability_code, primary_agent_id, source_conversation_id,
                     source_message_id, expected_membership_version, owner_user_id, project_id,
                     billing_scope_type, billing_scope_id, max_point_cost, point_reservation_id,
                     resume_event_id, created_by, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                creation.taskId(),
                creation.tenantId(),
                creation.title(),
                command.goal(),
                creation.response().status().name(),
                command.collaborationMode().name(),
                creation.capabilityCode(),
                command.primaryAgentId(),
                command.sourceConversationId(),
                command.sourceMessageId(),
                command.expectedMembershipVersion(),
                command.ownership().ownerUserId(),
                command.ownership().projectId(),
                command.ownership().billingScopeType().name(),
                command.ownership().billingScopeId(),
                command.maxPointCost(),
                creation.pointReservation().reservationId(),
                creation.response().resumeEventId(),
                creation.actorId(),
                Timestamp.from(creation.occurredAt()),
                Timestamp.from(creation.occurredAt())
        );
    }

    private void insertPlan(TaskCreation creation) {
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.execution_plan_version
                    (task_id, tenant_id, plan_version, status, execution_profile_snapshot,
                     created_by, created_at)
                VALUES (?, ?, 1, 'ACTIVE', CAST(? AS JSONB), ?, ?)
                """,
                creation.taskId(),
                creation.tenantId(),
                creation.executionProfileJson(),
                creation.actorId(),
                Timestamp.from(creation.occurredAt())
        );
    }

    private void insertSteps(TaskCreation creation) {
        for (var step : creation.steps()) {
            jdbcTemplate.update(
                    """
                    INSERT INTO dianlian_business.task_step
                        (step_id, tenant_id, task_id, plan_version, step_key, title, status,
                         executor_type, responsible_type, responsible_id, depends_on, input_contract,
                         output_contract, human_checkpoint, blocker_code, step_order, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, CAST(? AS JSONB), ?, ?, ?, ?, ?, ?, ?)
                    """,
                    step.stepId(),
                    creation.tenantId(),
                    creation.taskId(),
                    step.stepKey(),
                    step.title(),
                    step.status(),
                    step.executorType().name(),
                    step.responsibleType(),
                    step.responsibleId(),
                    serializer.serialize(step.dependsOn()),
                    step.inputContract(),
                    step.outputContract(),
                    step.humanCheckpoint(),
                    step.blockerCode(),
                    step.stepOrder(),
                    Timestamp.from(creation.occurredAt()),
                    Timestamp.from(creation.occurredAt())
            );
        }
    }

    private void insertInitialExecutions(TaskCreation creation) {
        for (var step : creation.steps()) {
            if (!"READY".equals(step.status()) || !"MODEL".equals(step.executorType().name())) {
                continue;
            }
            var runtimeRunId = UUID.randomUUID();
            jdbcTemplate.update(
                    """
                    INSERT INTO dianlian_business.task_step_execution
                        (task_step_id, tenant_id, execution_generation, runtime_run_id, status,
                         idempotency_key, request_hash, next_attempt_at, created_at, updated_at)
                    VALUES (?, ?, 1, ?, 'PREPARED', ?, ?, ?, ?, ?)
                    """,
                    step.stepId(),
                    creation.tenantId(),
                    runtimeRunId,
                    "task-step:" + creation.taskId() + ":" + step.stepId() + ":1",
                    creation.requestHash(),
                    Timestamp.from(creation.occurredAt()),
                    Timestamp.from(creation.occurredAt()),
                    Timestamp.from(creation.occurredAt())
            );
            var changed = jdbcTemplate.update(
                    """
                    UPDATE dianlian_business.task_step
                       SET active_execution_generation = 1, active_runtime_run_id = ?, updated_at = ?
                     WHERE tenant_id = ? AND step_id = ? AND status = 'READY'
                       AND executor_type = 'MODEL' AND active_runtime_run_id IS NULL
                    """,
                    runtimeRunId,
                    Timestamp.from(creation.occurredAt()),
                    creation.tenantId(),
                    step.stepId()
            );
            if (changed != 1) {
                throw new IllegalStateException("Initial task execution could not be bound to its MODEL step");
            }
        }
    }

    private void insertParticipant(TaskCreation creation) {
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.task_participant
                    (task_id, tenant_id, user_id, participant_role, status, granted_by, created_at)
                VALUES (?, ?, ?, 'OWNER', 'ACTIVE', ?, ?)
                """,
                creation.taskId(),
                creation.tenantId(),
                creation.command().ownership().ownerUserId(),
                creation.actorId(),
                Timestamp.from(creation.occurredAt())
        );
    }

    private void insertTargets(TaskCreation creation) {
        for (var target : creation.targets()) {
            jdbcTemplate.update(
                    """
                    INSERT INTO dianlian_business.task_target
                        (task_id, tenant_id, enterprise_agent_id, agent_version_id, target_role,
                         target_order, capability_code, execution_template_code,
                         execution_template_version, estimated_point_cost, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    creation.taskId(),
                    creation.tenantId(),
                    target.enterpriseAgentId(),
                    target.agentVersionId(),
                    target.targetRole().name(),
                    target.targetOrder(),
                    target.capabilityCode(),
                    target.executionTemplateCode(),
                    target.executionTemplateVersion(),
                    target.estimatedPointCost(),
                    Timestamp.from(creation.occurredAt())
            );
        }
    }

    private void insertInputSnapshot(TaskCreation creation) {
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.task_input_snapshot
                    (input_snapshot_id, tenant_id, task_id, plan_version, schema_id, schema_version,
                     request_hash, input_payload, created_by, created_at)
                VALUES (?, ?, ?, 1, ?, ?, ?, CAST(? AS JSONB), ?, ?)
                """,
                UUID.randomUUID(),
                creation.tenantId(),
                creation.taskId(),
                creation.command().capabilityInput().schemaId(),
                creation.command().capabilityInput().schemaVersion(),
                creation.requestHash(),
                creation.inputPayloadJson(),
                creation.actorId(),
                Timestamp.from(creation.occurredAt())
        );
    }

    private void insertBusinessTrace(TaskCreation creation) {
        insertTrace(
                creation,
                UUID.randomUUID(),
                "GOAL_CONFIRMED",
                "USER",
                creation.actorId(),
                "Task goal confirmed",
                serializer.serialize(java.util.List.of())
        );
        insertTrace(
                creation,
                UUID.randomUUID(),
                "PLAN_CREATED",
                "SYSTEM",
                creation.taskId(),
                "Initial execution plan created from the employee execution profile",
                serializer.serialize(creation.steps().stream().map(step -> step.stepId()).toList())
        );
    }

    private void insertTrace(
            TaskCreation creation,
            UUID traceItemId,
            String traceType,
            String responsibleType,
            UUID responsibleId,
            String summary,
            String referenceIdsJson
    ) {
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.task_business_trace
                    (trace_item_id, tenant_id, task_id, trace_type, responsible_type,
                     responsible_id, summary, reference_ids, occurred_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CAST(? AS JSONB), ?)
                """,
                traceItemId,
                creation.tenantId(),
                creation.taskId(),
                traceType,
                responsibleType,
                responsibleId,
                summary,
                referenceIdsJson,
                Timestamp.from(creation.occurredAt())
        );
    }

    private void insertOutbox(TaskCreation creation) {
        var eventType = switch (creation.response().status()) {
            case WAITING_CONFIRMATION -> "checkpoint.required";
            case PAUSED -> "task.paused";
            default -> "task.started";
        };
        var payload = serializer.serialize(initialEventPayload(creation, eventType));
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.outbox_event
                    (event_id, tenant_id, aggregate_type, aggregate_id, event_type, payload, occurred_at)
                VALUES (?, ?, 'TASK', ?, ?, CAST(? AS JSONB), ?)
                """,
                creation.response().resumeEventId(),
                creation.tenantId(),
                creation.taskId(),
                eventType,
                payload,
                Timestamp.from(creation.occurredAt())
        );
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.task_event
                    (event_id, tenant_id, task_id, task_version, event_type, visibility_version,
                     trace_id, payload, occurred_at)
                VALUES (?, ?, ?, ?, ?, 'task-participants:v1', ?, CAST(? AS JSONB), ?)
                """,
                creation.response().resumeEventId(),
                creation.tenantId(),
                creation.taskId(),
                creation.response().taskVersion(),
                eventType,
                creation.response().resumeEventId(),
                payload,
                Timestamp.from(creation.occurredAt())
        );
    }

    private Map<String, Object> initialEventPayload(TaskCreation creation, String eventType) {
        if ("checkpoint.required".equals(eventType)) {
            var step = creation.steps().stream()
                    .filter(candidate -> "WAITING_EXTERNAL".equals(candidate.status())
                            && candidate.humanCheckpoint())
                    .findFirst()
                    .orElseThrow(() -> new IllegalStateException("WAITING_CONFIRMATION task has no checkpoint step"));
            return Map.of(
                    "taskId", creation.taskId(),
                    "checkpointId", step.stepId(),
                    "checkpointType", "CONFIRMATION",
                    "status", "OPEN",
                    "prompt", step.title(),
                    "allowedActions", TaskActionPolicy.allowedActions(creation.response().status())
            );
        }
        var payload = new LinkedHashMap<String, Object>();
        payload.put("taskId", creation.taskId());
        payload.put("taskStatus", creation.response().status());
        creation.steps().stream()
                .map(step -> step.blockerCode())
                .filter(java.util.Objects::nonNull)
                .findFirst()
                .ifPresent(blockerCode -> payload.put("blockerCode", blockerCode));
        payload.put("allowedActions", TaskActionPolicy.allowedActions(creation.response().status()));
        return payload;
    }

    private void completeIdempotency(TaskCreation creation) {
        var response = creation.response();
        var payload = serializer.serialize(Map.of(
                "taskId", response.taskId(),
                "taskVersion", response.taskVersion(),
                "status", response.status(),
                "acceptedAt", response.acceptedAt(),
                "statusUrl", response.statusUrl(),
                "eventsUrl", response.eventsUrl(),
                "resumeEventId", response.resumeEventId()
        ));
        var changed = jdbcTemplate.update(
                """
                UPDATE dianlian_business.idempotency_record
                   SET resource_type = 'TASK', resource_id = ?, response_http_status = 202,
                       response_payload = CAST(? AS JSONB), completed_at = ?
                 WHERE tenant_id = ? AND actor_id = ? AND operation = ? AND idempotency_key = ?
                   AND request_hash = ? AND completed_at IS NULL
                """,
                creation.taskId(),
                payload,
                Timestamp.from(creation.occurredAt()),
                creation.tenantId(),
                creation.actorId(),
                OPERATION,
                creation.command().idempotencyKey(),
                creation.requestHash()
        );
        if (changed != 1) {
            throw new IllegalStateException("Task idempotency result could not be completed");
        }
    }

    private record ExistingIdempotency(String requestHash, TaskCommandAccepted response) {
    }
}

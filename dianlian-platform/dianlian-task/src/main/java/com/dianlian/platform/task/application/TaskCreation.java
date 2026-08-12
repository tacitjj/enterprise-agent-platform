package com.dianlian.platform.task.application;

import com.dianlian.platform.billing.api.PointReservationResult;
import com.dianlian.platform.task.api.CreateTaskCommand;
import com.dianlian.platform.task.api.TaskCommandAccepted;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record TaskCreation(
        UUID tenantId,
        UUID actorId,
        UUID taskId,
        String title,
        String capabilityCode,
        String requestHash,
        String inputPayloadJson,
        String executionProfileJson,
        long estimatedUpperBound,
        CreateTaskCommand command,
        PointReservationResult pointReservation,
        List<TaskTargetCreation> targets,
        List<TaskStepCreation> steps,
        TaskCommandAccepted response,
        Instant occurredAt
) {

    public TaskCreation {
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(actorId, "actorId must not be null");
        Objects.requireNonNull(taskId, "taskId must not be null");
        title = requireText(title, "title");
        capabilityCode = requireText(capabilityCode, "capabilityCode");
        requestHash = requireText(requestHash, "requestHash");
        inputPayloadJson = requireText(inputPayloadJson, "inputPayloadJson");
        executionProfileJson = requireText(executionProfileJson, "executionProfileJson");
        if (estimatedUpperBound < 1) {
            throw new IllegalArgumentException("estimatedUpperBound must be positive");
        }
        Objects.requireNonNull(command, "command must not be null");
        Objects.requireNonNull(pointReservation, "pointReservation must not be null");
        targets = List.copyOf(Objects.requireNonNull(targets, "targets must not be null"));
        steps = List.copyOf(Objects.requireNonNull(steps, "steps must not be null"));
        if (targets.isEmpty() || steps.isEmpty()) {
            throw new IllegalArgumentException("targets and steps must not be empty");
        }
        Objects.requireNonNull(response, "response must not be null");
        Objects.requireNonNull(occurredAt, "occurredAt must not be null");
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}

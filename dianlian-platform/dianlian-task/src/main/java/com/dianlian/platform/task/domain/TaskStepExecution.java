package com.dianlian.platform.task.domain;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record TaskStepExecution(
        UUID taskStepId,
        ExecutionGeneration executionGeneration,
        UUID runtimeRunId,
        TaskStepExecutionStatus status,
        Instant createdAt
) {

    public TaskStepExecution {
        Objects.requireNonNull(taskStepId, "taskStepId must not be null");
        Objects.requireNonNull(executionGeneration, "executionGeneration must not be null");
        Objects.requireNonNull(runtimeRunId, "runtimeRunId must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }

    public static TaskStepExecution prepare(
            UUID taskStepId,
            ExecutionGeneration executionGeneration,
            UUID runtimeRunId,
            Instant createdAt
    ) {
        return new TaskStepExecution(
                taskStepId,
                executionGeneration,
                runtimeRunId,
                TaskStepExecutionStatus.PREPARED,
                createdAt
        );
    }
}

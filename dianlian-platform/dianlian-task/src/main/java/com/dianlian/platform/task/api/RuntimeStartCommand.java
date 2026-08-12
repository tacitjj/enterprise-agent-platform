package com.dianlian.platform.task.api;

import java.util.Objects;
import java.util.UUID;

public record RuntimeStartCommand(
        UUID taskStepId,
        long executionGeneration,
        UUID runtimeRunId,
        String idempotencyKey,
        String requestHash
) {

    public RuntimeStartCommand {
        Objects.requireNonNull(taskStepId, "taskStepId must not be null");
        if (executionGeneration < 1) {
            throw new IllegalArgumentException("executionGeneration must be positive");
        }
        Objects.requireNonNull(runtimeRunId, "runtimeRunId must not be null");
        idempotencyKey = requireText(idempotencyKey, "idempotencyKey");
        requestHash = requireText(requestHash, "requestHash");
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}

package com.dianlian.platform.task.application;

import com.dianlian.platform.employee.api.ExecutionExecutorType;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record TaskStepCreation(
        UUID stepId,
        String stepKey,
        String title,
        String status,
        ExecutionExecutorType executorType,
        String responsibleType,
        UUID responsibleId,
        List<UUID> dependsOn,
        String inputContract,
        String outputContract,
        boolean humanCheckpoint,
        String blockerCode,
        int stepOrder
) {

    public TaskStepCreation {
        Objects.requireNonNull(stepId, "stepId must not be null");
        stepKey = requireText(stepKey, "stepKey");
        title = requireText(title, "title");
        status = requireText(status, "status");
        Objects.requireNonNull(executorType, "executorType must not be null");
        responsibleType = requireText(responsibleType, "responsibleType");
        Objects.requireNonNull(responsibleId, "responsibleId must not be null");
        dependsOn = List.copyOf(Objects.requireNonNull(dependsOn, "dependsOn must not be null"));
        inputContract = requireText(inputContract, "inputContract");
        outputContract = requireText(outputContract, "outputContract");
        blockerCode = blockerCode == null ? null : requireText(blockerCode, "blockerCode");
        if (stepOrder < 1) {
            throw new IllegalArgumentException("stepOrder must be positive");
        }
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}

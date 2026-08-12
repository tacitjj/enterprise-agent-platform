package com.dianlian.platform.employee.api;

import java.util.List;
import java.util.Objects;

public record ExecutionStepDescriptor(
        String stepKey,
        String title,
        ExecutionExecutorType executorType,
        List<String> dependsOn,
        String inputSchemaRef,
        String outputSchemaRef,
        boolean humanCheckpoint
) {

    public ExecutionStepDescriptor {
        stepKey = EmployeeValueChecks.stableCode(stepKey, "stepKey", 96);
        title = EmployeeValueChecks.nonBlank(title, "title", 160);
        Objects.requireNonNull(executorType, "executorType must not be null");
        dependsOn = List.copyOf(Objects.requireNonNull(dependsOn, "dependsOn must not be null"));
        dependsOn = dependsOn.stream()
                .map(value -> EmployeeValueChecks.stableCode(value, "dependsOn", 96))
                .toList();
        inputSchemaRef = EmployeeValueChecks.optional(inputSchemaRef, "inputSchemaRef", 128);
        outputSchemaRef = EmployeeValueChecks.optional(outputSchemaRef, "outputSchemaRef", 128);
    }
}

package com.dianlian.platform.task.api;

import java.time.Instant;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

public record OfficeTaskSummary(
        UUID taskId,
        String title,
        TaskStatus status,
        TaskDisplayStatus displayStatus,
        List<UUID> responsibleAgentIds,
        String currentStepTitle,
        int completedStepCount,
        int totalStepCount,
        TaskPointSummary pointSummary,
        Instant updatedAt,
        Set<TaskAllowedAction> allowedActions
) {

    public OfficeTaskSummary {
        Objects.requireNonNull(taskId, "taskId must not be null");
        Objects.requireNonNull(title, "title must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(displayStatus, "displayStatus must not be null");
        responsibleAgentIds = List.copyOf(Objects.requireNonNull(
                responsibleAgentIds,
                "responsibleAgentIds must not be null"
        ));
        if (responsibleAgentIds.isEmpty()) {
            throw new IllegalArgumentException("responsibleAgentIds must not be empty");
        }
        if (completedStepCount < 0 || totalStepCount < 0 || completedStepCount > totalStepCount) {
            throw new IllegalArgumentException("step counts are inconsistent");
        }
        Objects.requireNonNull(pointSummary, "pointSummary must not be null");
        Objects.requireNonNull(updatedAt, "updatedAt must not be null");
        allowedActions = Set.copyOf(new LinkedHashSet<>(Objects.requireNonNull(
                allowedActions,
                "allowedActions must not be null"
        )));
    }
}

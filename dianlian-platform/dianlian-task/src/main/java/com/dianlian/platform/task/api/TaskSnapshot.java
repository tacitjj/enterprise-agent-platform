package com.dianlian.platform.task.api;

import java.time.Instant;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

public record TaskSnapshot(
        UUID taskId,
        long taskVersion,
        String title,
        String goal,
        TaskStatus status,
        TaskBlocker blocker,
        int planVersion,
        CollaborationMode collaborationMode,
        String capabilityCode,
        Map<String, Object> capabilityView,
        List<UUID> targetAgentIds,
        UUID primaryAgentId,
        List<StepView> steps,
        RuntimeRunSummary activeRun,
        List<ArtifactSummary> artifacts,
        ApprovalSummary approval,
        DeliverySummary delivery,
        TaskPointSummary pointSummary,
        List<BusinessTraceItem> businessTrace,
        Set<TaskAllowedAction> allowedActions,
        UUID resumeEventId,
        Instant updatedAt
) {

    public TaskSnapshot {
        Objects.requireNonNull(taskId, "taskId must not be null");
        if (taskVersion < 1 || planVersion < 1) {
            throw new IllegalArgumentException("taskVersion and planVersion must be positive");
        }
        title = requireText(title, "title");
        goal = requireText(goal, "goal");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(collaborationMode, "collaborationMode must not be null");
        capabilityCode = requireText(capabilityCode, "capabilityCode");
        capabilityView = Map.copyOf(Objects.requireNonNull(capabilityView, "capabilityView must not be null"));
        targetAgentIds = List.copyOf(Objects.requireNonNull(targetAgentIds, "targetAgentIds must not be null"));
        steps = List.copyOf(Objects.requireNonNull(steps, "steps must not be null"));
        artifacts = List.copyOf(Objects.requireNonNull(artifacts, "artifacts must not be null"));
        Objects.requireNonNull(pointSummary, "pointSummary must not be null");
        businessTrace = List.copyOf(Objects.requireNonNull(businessTrace, "businessTrace must not be null"));
        allowedActions = Set.copyOf(new LinkedHashSet<>(Objects.requireNonNull(
                allowedActions,
                "allowedActions must not be null"
        )));
        Objects.requireNonNull(resumeEventId, "resumeEventId must not be null");
        Objects.requireNonNull(updatedAt, "updatedAt must not be null");
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }

    public record TaskBlocker(String code, String responsibleParty, String message) {
    }

    public record StepView(
            UUID stepId,
            String stepKey,
            String title,
            String status,
            String responsibleType,
            UUID responsibleId,
            List<UUID> dependsOn,
            String outputContract,
            String blockerCode
    ) {

        public StepView {
            Objects.requireNonNull(stepId, "stepId must not be null");
            stepKey = requireText(stepKey, "stepKey");
            title = requireText(title, "title");
            status = requireText(status, "status");
            responsibleType = requireText(responsibleType, "responsibleType");
            Objects.requireNonNull(responsibleId, "responsibleId must not be null");
            dependsOn = List.copyOf(Objects.requireNonNull(dependsOn, "dependsOn must not be null"));
            outputContract = requireText(outputContract, "outputContract");
        }
    }

    public record RuntimeRunSummary(
            UUID runtimeRunId,
            UUID taskStepId,
            long executionGeneration,
            String status,
            String operationKind,
            UUID checkpointId,
            Instant startedAt,
            Instant terminalAt
    ) {
    }

    public record ArtifactSummary(
            UUID artifactVersionId,
            String artifactType,
            String title,
            String status,
            String contentHash,
            UUID sourceStepId,
            UUID parentArtifactVersionId,
            Instant createdAt
    ) {
    }

    public record ApprovalSummary(UUID approvalId, UUID artifactVersionId, String status, Instant updatedAt) {
    }

    public record DeliverySummary(
            UUID deliveryId,
            UUID artifactVersionId,
            String status,
            String destinationType,
            String reasonCode,
            Instant updatedAt
    ) {
    }

    public record BusinessTraceItem(
            UUID traceItemId,
            String type,
            Instant occurredAt,
            String responsibleType,
            UUID responsibleId,
            String summary,
            List<UUID> referenceIds
    ) {

        public BusinessTraceItem {
            Objects.requireNonNull(traceItemId, "traceItemId must not be null");
            type = requireText(type, "type");
            Objects.requireNonNull(occurredAt, "occurredAt must not be null");
            summary = requireText(summary, "summary");
            referenceIds = List.copyOf(Objects.requireNonNull(referenceIds, "referenceIds must not be null"));
        }
    }
}

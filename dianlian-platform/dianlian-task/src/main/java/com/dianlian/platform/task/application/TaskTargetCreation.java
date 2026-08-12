package com.dianlian.platform.task.application;

import java.util.Objects;
import java.util.UUID;

public record TaskTargetCreation(
        UUID enterpriseAgentId,
        UUID agentVersionId,
        TaskTargetRole targetRole,
        int targetOrder,
        String capabilityCode,
        String executionTemplateCode,
        String executionTemplateVersion,
        long estimatedPointCost
) {

    public TaskTargetCreation {
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(agentVersionId, "agentVersionId must not be null");
        Objects.requireNonNull(targetRole, "targetRole must not be null");
        if (targetOrder < 1 || estimatedPointCost < 0) {
            throw new IllegalArgumentException("targetOrder must be positive and estimatedPointCost must not be negative");
        }
        capabilityCode = requireText(capabilityCode, "capabilityCode");
        executionTemplateCode = requireText(executionTemplateCode, "executionTemplateCode");
        executionTemplateVersion = requireText(executionTemplateVersion, "executionTemplateVersion");
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}

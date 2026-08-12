package com.dianlian.platform.employee.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record EnterpriseAgentConfigurationSummary(
        UUID configurationVersionId,
        long revision,
        String displayNameSnapshot,
        String profile,
        String enterpriseInstructions,
        EnterpriseAgentModelPolicyMode modelPolicyMode,
        EnterpriseAgentKnowledgeScopeMode knowledgeScopeMode,
        EnterpriseAgentVisibilityScope visibilityScope,
        EnterpriseAgentConfigurationStatus status,
        UUID createdBy,
        Instant createdAt,
        UUID activatedBy,
        Instant activatedAt
) {

    public EnterpriseAgentConfigurationSummary {
        Objects.requireNonNull(configurationVersionId, "configurationVersionId must not be null");
        if (revision <= 0) {
            throw new IllegalArgumentException("revision must be positive");
        }
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(createdBy, "createdBy must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }
}

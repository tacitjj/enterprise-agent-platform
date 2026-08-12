package com.dianlian.platform.employee.api;

import java.util.Objects;
import java.util.UUID;

public record CreateEnterpriseAgentConfigurationCommand(
        UUID enterpriseAgentId,
        long expectedStateVersion,
        String displayNameSnapshot,
        String profile,
        String enterpriseInstructions,
        EnterpriseAgentModelPolicyMode modelPolicyMode,
        EnterpriseAgentKnowledgeScopeMode knowledgeScopeMode,
        EnterpriseAgentVisibilityScope visibilityScope,
        String idempotencyKey,
        String requestHash
) {

    public CreateEnterpriseAgentConfigurationCommand {
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        if (expectedStateVersion < 0) {
            throw new IllegalArgumentException("expectedStateVersion must not be negative");
        }
        displayNameSnapshot = EmployeeValueChecks.nonBlank(displayNameSnapshot, "displayNameSnapshot", 100);
        profile = EmployeeValueChecks.nonBlank(profile, "profile", 2000);
        if (enterpriseInstructions == null) {
            throw new IllegalArgumentException("enterpriseInstructions must not be null");
        }
        enterpriseInstructions = enterpriseInstructions.trim();
        if (enterpriseInstructions.length() > 20000) {
            throw new IllegalArgumentException("enterpriseInstructions exceeds 20000 characters");
        }
        if (modelPolicyMode == null || knowledgeScopeMode == null || visibilityScope == null) {
            throw new IllegalArgumentException("configuration modes must not be null");
        }
        idempotencyKey = EmployeeValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 200);
        requestHash = EmployeeValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

package com.dianlian.platform.employee.domain;

import com.dianlian.platform.employee.api.EnterpriseAgentConfigurationStatus;
import com.dianlian.platform.employee.api.EnterpriseAgentKnowledgeScopeMode;
import com.dianlian.platform.employee.api.EnterpriseAgentModelPolicyMode;
import com.dianlian.platform.employee.api.EnterpriseAgentVisibilityScope;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record EnterpriseAgentConfigurationVersion(
        UUID configurationVersionId,
        UUID tenantId,
        UUID enterpriseAgentId,
        long revision,
        String displayNameSnapshot,
        String profile,
        String enterpriseInstructions,
        EnterpriseAgentModelPolicyMode modelPolicyMode,
        EnterpriseAgentKnowledgeScopeMode knowledgeScopeMode,
        EnterpriseAgentVisibilityScope visibilityScope,
        EnterpriseAgentConfigurationStatus status,
        String createRequestHash,
        String createIdempotencyKey,
        UUID createdBy,
        Instant createdAt,
        long createResultStateVersion,
        String activationRequestHash,
        String activationIdempotencyKey,
        UUID activatedBy,
        Instant activatedAt,
        Long activationResultStateVersion
) {

    public EnterpriseAgentConfigurationVersion {
        Objects.requireNonNull(configurationVersionId, "configurationVersionId must not be null");
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(modelPolicyMode, "modelPolicyMode must not be null");
        Objects.requireNonNull(knowledgeScopeMode, "knowledgeScopeMode must not be null");
        Objects.requireNonNull(visibilityScope, "visibilityScope must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(createdBy, "createdBy must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
        if (revision <= 0 || createResultStateVersion <= 0) {
            throw new IllegalArgumentException("configuration revision and result state version must be positive");
        }
    }
}

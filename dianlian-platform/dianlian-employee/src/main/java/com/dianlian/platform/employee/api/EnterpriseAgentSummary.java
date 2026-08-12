package com.dianlian.platform.employee.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record EnterpriseAgentSummary(
        UUID enterpriseAgentId,
        UUID tenantId,
        UUID templateId,
        UUID agentVersionId,
        String employeeCode,
        String displayName,
        String capabilityCode,
        EnterpriseAgentStatus status,
        long stateVersion,
        UUID activeConfigurationVersionId,
        UUID activatedBy,
        Instant activatedAt,
        Instant hiredAt
) {

    public EnterpriseAgentSummary {
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(templateId, "templateId must not be null");
        Objects.requireNonNull(agentVersionId, "agentVersionId must not be null");
        Objects.requireNonNull(status, "status must not be null");
        if (stateVersion < 0) {
            throw new IllegalArgumentException("stateVersion must not be negative");
        }
        if (status == EnterpriseAgentStatus.DRAFT
                && (activeConfigurationVersionId != null || activatedBy != null || activatedAt != null)) {
            throw new IllegalArgumentException("draft employee cannot have an active configuration");
        }
        if (status != EnterpriseAgentStatus.DRAFT
                && (activeConfigurationVersionId == null || activatedBy == null || activatedAt == null)) {
            throw new IllegalArgumentException("non-draft employee requires activation audit");
        }
        Objects.requireNonNull(hiredAt, "hiredAt must not be null");
    }
}

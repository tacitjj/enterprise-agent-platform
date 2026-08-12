package com.dianlian.platform.employee.domain;

import com.dianlian.platform.employee.api.EnterpriseAgentStatus;
import com.dianlian.platform.employee.api.EnterpriseAgentSummary;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record EnterpriseAgent(
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
        String requestHash,
        String hireIdempotencyKey,
        UUID hiredBy,
        Instant hiredAt
) {

    public EnterpriseAgent {
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(templateId, "templateId must not be null");
        Objects.requireNonNull(agentVersionId, "agentVersionId must not be null");
        Objects.requireNonNull(status, "status must not be null");
        if (stateVersion < 0) {
            throw new IllegalArgumentException("stateVersion must not be negative");
        }
        Objects.requireNonNull(hiredBy, "hiredBy must not be null");
        Objects.requireNonNull(hiredAt, "hiredAt must not be null");
    }

    public EnterpriseAgentSummary toSummary() {
        return new EnterpriseAgentSummary(
                enterpriseAgentId,
                tenantId,
                templateId,
                agentVersionId,
                employeeCode,
                displayName,
                capabilityCode,
                status,
                stateVersion,
                activeConfigurationVersionId,
                activatedBy,
                activatedAt,
                hiredAt
        );
    }
}

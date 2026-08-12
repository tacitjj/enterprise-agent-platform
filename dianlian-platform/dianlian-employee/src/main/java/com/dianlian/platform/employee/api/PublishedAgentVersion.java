package com.dianlian.platform.employee.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record PublishedAgentVersion(
        UUID templateId,
        UUID agentVersionId,
        String templateCode,
        String templateName,
        String templateDescription,
        String version,
        String capabilityCode,
        InputSchemaDescriptor inputSchema,
        ExecutionTemplateDescriptor executionTemplate,
        long pointEstimate,
        AgentVersionStatus status,
        EnterpriseVisibility enterpriseVisibility,
        Instant publishedAt
) {

    public PublishedAgentVersion {
        Objects.requireNonNull(templateId, "templateId must not be null");
        Objects.requireNonNull(agentVersionId, "agentVersionId must not be null");
        capabilityCode = EmployeeValueChecks.capabilityCode(capabilityCode);
        Objects.requireNonNull(inputSchema, "inputSchema must not be null");
        Objects.requireNonNull(executionTemplate, "executionTemplate must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(enterpriseVisibility, "enterpriseVisibility must not be null");
        Objects.requireNonNull(publishedAt, "publishedAt must not be null");
    }
}

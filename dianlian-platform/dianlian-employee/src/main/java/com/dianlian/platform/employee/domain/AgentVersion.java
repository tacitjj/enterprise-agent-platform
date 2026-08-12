package com.dianlian.platform.employee.domain;

import com.dianlian.platform.employee.api.AgentVersionStatus;
import com.dianlian.platform.employee.api.EnterpriseVisibility;
import com.dianlian.platform.employee.api.ExecutionTemplateDescriptor;
import com.dianlian.platform.employee.api.InputSchemaDescriptor;
import com.dianlian.platform.employee.api.PublishedAgentVersion;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record AgentVersion(
        UUID agentVersionId,
        UUID templateId,
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
        String requestHash,
        String publishIdempotencyKey,
        UUID publishedBy,
        Instant publishedAt
) {

    public AgentVersion {
        Objects.requireNonNull(agentVersionId, "agentVersionId must not be null");
        Objects.requireNonNull(templateId, "templateId must not be null");
        Objects.requireNonNull(inputSchema, "inputSchema must not be null");
        Objects.requireNonNull(executionTemplate, "executionTemplate must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(enterpriseVisibility, "enterpriseVisibility must not be null");
        Objects.requireNonNull(publishedBy, "publishedBy must not be null");
        Objects.requireNonNull(publishedAt, "publishedAt must not be null");
        if (pointEstimate < 1) {
            throw new IllegalArgumentException("pointEstimate must be positive");
        }
    }

    public PublishedAgentVersion toPublishedView() {
        return new PublishedAgentVersion(
                templateId,
                agentVersionId,
                templateCode,
                templateName,
                templateDescription,
                version,
                capabilityCode,
                inputSchema,
                executionTemplate,
                pointEstimate,
                status,
                enterpriseVisibility,
                publishedAt
        );
    }
}

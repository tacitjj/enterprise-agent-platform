package com.dianlian.platform.employee.api;

import java.util.Objects;
import java.util.List;
import java.util.UUID;

public record ExecutableAgentSummary(
        UUID enterpriseAgentId,
        UUID templateId,
        UUID agentVersionId,
        UUID configurationVersionId,
        String templateCode,
        String displayName,
        String roleName,
        String profile,
        String enterpriseInstructions,
        EnterpriseAgentModelPolicyMode modelPolicyMode,
        EnterpriseAgentKnowledgeScopeMode knowledgeScopeMode,
        List<String> skillLabels,
        String avatarUrl,
        String capabilityCode,
        InputSchemaDescriptor inputSchema,
        ExecutionTemplateDescriptor executionTemplate,
        long pointEstimate,
        EnterpriseAgentStatus status,
        AgentVersionStatus versionStatus
) {

    public ExecutableAgentSummary {
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(templateId, "templateId must not be null");
        Objects.requireNonNull(agentVersionId, "agentVersionId must not be null");
        Objects.requireNonNull(configurationVersionId, "configurationVersionId must not be null");
        Objects.requireNonNull(roleName, "roleName must not be null");
        Objects.requireNonNull(profile, "profile must not be null");
        Objects.requireNonNull(enterpriseInstructions, "enterpriseInstructions must not be null");
        Objects.requireNonNull(modelPolicyMode, "modelPolicyMode must not be null");
        Objects.requireNonNull(knowledgeScopeMode, "knowledgeScopeMode must not be null");
        skillLabels = List.copyOf(Objects.requireNonNull(skillLabels, "skillLabels must not be null"));
        capabilityCode = EmployeeValueChecks.capabilityCode(capabilityCode);
        Objects.requireNonNull(inputSchema, "inputSchema must not be null");
        Objects.requireNonNull(executionTemplate, "executionTemplate must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(versionStatus, "versionStatus must not be null");
        if (!status.executable() || versionStatus != AgentVersionStatus.PUBLISHED) {
            throw new IllegalArgumentException("executable summary requires active agent and published version");
        }
    }
}

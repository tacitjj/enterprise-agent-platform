package com.dianlian.platform.employee.api;

public record EnterpriseAgentTemplateSnapshot(
        String templateName,
        String templateDescription,
        String version,
        AgentVersionStatus status
) {

    public EnterpriseAgentTemplateSnapshot {
        templateName = EmployeeValueChecks.nonBlank(templateName, "templateName", 100);
        templateDescription = EmployeeValueChecks.nonBlank(templateDescription, "templateDescription", 500);
        version = EmployeeValueChecks.nonBlank(version, "version", 32);
        if (status == null) {
            throw new IllegalArgumentException("status must not be null");
        }
    }
}

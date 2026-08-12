package com.dianlian.platform.employee.api;

import java.util.Objects;

public record PublishAgentVersionCommand(
        String templateCode,
        String templateName,
        String templateDescription,
        String version,
        String capabilityCode,
        InputSchemaDescriptor inputSchema,
        ExecutionTemplateDescriptor executionTemplate,
        long pointEstimate,
        EnterpriseVisibility enterpriseVisibility,
        String idempotencyKey,
        String requestHash
) {

    public PublishAgentVersionCommand {
        templateCode = EmployeeValueChecks.stableCode(templateCode, "templateCode", 64);
        templateName = EmployeeValueChecks.nonBlank(templateName, "templateName", 100);
        templateDescription = EmployeeValueChecks.nonBlank(templateDescription, "templateDescription", 500);
        version = EmployeeValueChecks.nonBlank(version, "version", 32);
        capabilityCode = EmployeeValueChecks.capabilityCode(capabilityCode);
        Objects.requireNonNull(inputSchema, "inputSchema must not be null");
        Objects.requireNonNull(executionTemplate, "executionTemplate must not be null");
        if (pointEstimate < 1) {
            throw new IllegalArgumentException("pointEstimate must be positive");
        }
        Objects.requireNonNull(enterpriseVisibility, "enterpriseVisibility must not be null");
        idempotencyKey = EmployeeValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 200);
        requestHash = EmployeeValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

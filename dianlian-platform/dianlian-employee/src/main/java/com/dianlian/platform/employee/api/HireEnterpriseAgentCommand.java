package com.dianlian.platform.employee.api;

import java.util.Objects;
import java.util.UUID;

public record HireEnterpriseAgentCommand(
        UUID agentVersionId,
        String employeeCode,
        String displayName,
        String idempotencyKey,
        String requestHash
) {

    public HireEnterpriseAgentCommand {
        Objects.requireNonNull(agentVersionId, "agentVersionId must not be null");
        employeeCode = EmployeeValueChecks.stableCode(employeeCode, "employeeCode", 64);
        displayName = EmployeeValueChecks.nonBlank(displayName, "displayName", 100);
        idempotencyKey = EmployeeValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 200);
        requestHash = EmployeeValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

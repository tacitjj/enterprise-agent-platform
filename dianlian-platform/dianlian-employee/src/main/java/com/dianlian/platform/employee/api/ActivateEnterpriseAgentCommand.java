package com.dianlian.platform.employee.api;

import java.util.Objects;
import java.util.UUID;

public record ActivateEnterpriseAgentCommand(
        UUID enterpriseAgentId,
        UUID configurationVersionId,
        long expectedStateVersion,
        String idempotencyKey,
        String requestHash
) {

    public ActivateEnterpriseAgentCommand {
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(configurationVersionId, "configurationVersionId must not be null");
        if (expectedStateVersion < 0) {
            throw new IllegalArgumentException("expectedStateVersion must not be negative");
        }
        idempotencyKey = EmployeeValueChecks.nonBlank(idempotencyKey, "idempotencyKey", 200);
        requestHash = EmployeeValueChecks.nonBlank(requestHash, "requestHash", 128);
    }
}

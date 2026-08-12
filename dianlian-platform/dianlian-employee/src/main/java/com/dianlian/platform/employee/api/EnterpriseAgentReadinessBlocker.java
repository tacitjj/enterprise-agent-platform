package com.dianlian.platform.employee.api;

import java.util.Objects;

public record EnterpriseAgentReadinessBlocker(String code, String message) {

    public EnterpriseAgentReadinessBlocker {
        code = EmployeeValueChecks.stableCode(code, "code", 64);
        message = EmployeeValueChecks.nonBlank(message, "message", 500);
    }
}

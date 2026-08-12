package com.dianlian.platform.employee.api;

public enum EnterpriseAgentStatus {
    DRAFT,
    ACTIVE,
    RESTRICTED,
    DISABLED;

    public boolean executable() {
        return this == ACTIVE;
    }
}

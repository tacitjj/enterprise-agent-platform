package com.dianlian.platform.employee.api;

import java.util.List;
import java.util.Objects;

public record EnterpriseAgentReadiness(boolean ready, List<EnterpriseAgentReadinessBlocker> blockers) {

    public EnterpriseAgentReadiness {
        blockers = List.copyOf(Objects.requireNonNull(blockers, "blockers must not be null"));
        if (ready != blockers.isEmpty()) {
            throw new IllegalArgumentException("ready must match blocker presence");
        }
    }
}

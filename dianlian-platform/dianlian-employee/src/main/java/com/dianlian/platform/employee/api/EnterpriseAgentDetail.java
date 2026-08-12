package com.dianlian.platform.employee.api;

import java.util.Objects;
import java.util.Set;

public record EnterpriseAgentDetail(
        EnterpriseAgentSummary agent,
        EnterpriseAgentTemplateSnapshot template,
        EnterpriseAgentConfigurationSummary latestConfiguration,
        EnterpriseAgentReadiness readiness,
        Set<EnterpriseAgentAllowedAction> allowedActions
) {

    public EnterpriseAgentDetail {
        Objects.requireNonNull(agent, "agent must not be null");
        Objects.requireNonNull(template, "template must not be null");
        Objects.requireNonNull(readiness, "readiness must not be null");
        allowedActions = Set.copyOf(Objects.requireNonNull(allowedActions, "allowedActions must not be null"));
    }
}

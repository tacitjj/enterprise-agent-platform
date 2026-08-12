package com.dianlian.platform.employee.api;

import com.dianlian.platform.identity.api.AccessContext;

public interface EnterpriseAgentCommands {

    CommandOutcome<EnterpriseAgentSummary> hire(
            HireEnterpriseAgentCommand command,
            AccessContext accessContext
    );

    CommandOutcome<EnterpriseAgentDetail> createConfigurationVersion(
            CreateEnterpriseAgentConfigurationCommand command,
            AccessContext accessContext
    );

    CommandOutcome<EnterpriseAgentDetail> activate(
            ActivateEnterpriseAgentCommand command,
            AccessContext accessContext
    );
}

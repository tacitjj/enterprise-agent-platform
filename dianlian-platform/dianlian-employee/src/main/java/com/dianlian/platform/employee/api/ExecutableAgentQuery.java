package com.dianlian.platform.employee.api;

import com.dianlian.platform.identity.api.AccessContext;
import java.util.List;
import java.util.UUID;

public interface ExecutableAgentQuery {

    List<ExecutableAgentSummary> listExecutableForOffice(AccessContext accessContext);

    ExecutableAgentSummary requireExecutableForTask(
            UUID enterpriseAgentId,
            AccessContext accessContext
    );

    ExecutableAgentSummary requireExecutableForTask(
            UUID enterpriseAgentId,
            String requiredCapabilityCode,
            AccessContext accessContext
    );
}

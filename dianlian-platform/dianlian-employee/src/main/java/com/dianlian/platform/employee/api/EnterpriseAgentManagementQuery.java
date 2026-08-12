package com.dianlian.platform.employee.api;

import com.dianlian.platform.identity.api.AccessContext;
import java.util.List;
import java.util.UUID;

public interface EnterpriseAgentManagementQuery {

    List<EnterpriseAgentSummary> listManaged(AccessContext accessContext);

    EnterpriseAgentDetail getManagedDetail(UUID enterpriseAgentId, AccessContext accessContext);
}

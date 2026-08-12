package com.dianlian.platform.employee.api;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import java.util.List;

public interface AgentVersionQuery {

    List<PublishedAgentVersion> listPublished(PlatformAccessContext accessContext);

    List<PublishedAgentVersion> listRecruitable(AccessContext accessContext);
}

package com.dianlian.platform.task.api;

import com.dianlian.platform.identity.api.AccessContext;

public interface AgentRuntimePort {

    RuntimeAdmission start(RuntimeStartCommand command, AccessContext accessContext);
}

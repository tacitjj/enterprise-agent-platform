package com.dianlian.platform.integration.infrastructure.runtime;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.task.api.AgentRuntimePort;
import com.dianlian.platform.task.api.RuntimeAdmission;
import com.dianlian.platform.task.api.RuntimeStartCommand;
import com.dianlian.platform.task.api.RuntimeUnavailableException;

public final class DisabledAgentRuntimePort implements AgentRuntimePort {

    @Override
    public RuntimeAdmission start(RuntimeStartCommand command, AccessContext accessContext) {
        throw new RuntimeUnavailableException("Python Agent Runtime is disabled");
    }
}

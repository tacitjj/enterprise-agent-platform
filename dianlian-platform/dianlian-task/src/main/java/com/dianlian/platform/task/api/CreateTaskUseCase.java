package com.dianlian.platform.task.api;

import com.dianlian.platform.identity.api.AccessContext;

public interface CreateTaskUseCase {

    TaskCommandAccepted create(CreateTaskCommand command, AccessContext accessContext);
}

package com.dianlian.platform.task.api;

import com.dianlian.platform.identity.api.AccessContext;
import java.util.UUID;

public interface TaskEventStreamQuery {

    TaskEventBatch read(UUID taskId, String afterEventId, int limit, AccessContext accessContext);
}

package com.dianlian.platform.task.api;

import com.dianlian.platform.identity.api.AccessContext;
import java.util.UUID;

public interface TaskSnapshotQuery {

    TaskSnapshot requireSnapshot(UUID taskId, AccessContext accessContext);
}

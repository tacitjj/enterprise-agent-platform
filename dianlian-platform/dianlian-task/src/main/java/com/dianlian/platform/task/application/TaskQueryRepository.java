package com.dianlian.platform.task.application;

import com.dianlian.platform.task.api.OfficeTaskSummary;
import com.dianlian.platform.task.api.TaskSnapshot;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface TaskQueryRepository {

    Optional<TaskSnapshot> findVisibleSnapshot(UUID tenantId, UUID actorId, UUID taskId);

    List<OfficeTaskSummary> findVisibleOfficeTasks(UUID tenantId, UUID actorId, int limit);
}

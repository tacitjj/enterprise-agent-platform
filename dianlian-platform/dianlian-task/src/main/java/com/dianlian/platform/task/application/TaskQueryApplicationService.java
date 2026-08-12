package com.dianlian.platform.task.application;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.task.api.OfficeTaskSummary;
import com.dianlian.platform.task.api.OfficeTaskSummaryPort;
import com.dianlian.platform.task.api.TaskNotFoundException;
import com.dianlian.platform.task.api.TaskSnapshot;
import com.dianlian.platform.task.api.TaskSnapshotQuery;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional(readOnly = true)
public class TaskQueryApplicationService implements TaskSnapshotQuery, OfficeTaskSummaryPort {

    private static final int MAX_OFFICE_TASKS = 50;

    private final TaskQueryRepository repository;

    public TaskQueryApplicationService(TaskQueryRepository repository) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
    }

    @Override
    public TaskSnapshot requireSnapshot(UUID taskId, AccessContext accessContext) {
        Objects.requireNonNull(taskId, "taskId must not be null");
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        return repository.findVisibleSnapshot(
                        accessContext.tenantId().value(),
                        accessContext.actorId().value(),
                        taskId
                )
                .orElseThrow(TaskNotFoundException::new);
    }

    @Override
    public List<OfficeTaskSummary> listVisibleTasks(AccessContext accessContext, int limit) {
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        if (limit < 1 || limit > MAX_OFFICE_TASKS) {
            throw new IllegalArgumentException("limit must be between 1 and " + MAX_OFFICE_TASKS);
        }
        return repository.findVisibleOfficeTasks(
                accessContext.tenantId().value(),
                accessContext.actorId().value(),
                limit
        );
    }
}

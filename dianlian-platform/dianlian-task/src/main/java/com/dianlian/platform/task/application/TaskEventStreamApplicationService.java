package com.dianlian.platform.task.application;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.task.api.TaskAccessDeniedException;
import com.dianlian.platform.task.api.TaskEventBatch;
import com.dianlian.platform.task.api.TaskEventEnvelope;
import com.dianlian.platform.task.api.TaskEventStreamQuery;
import com.dianlian.platform.task.api.TaskNotFoundException;
import com.dianlian.platform.task.api.TaskPermissions;
import java.time.Clock;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@Transactional(readOnly = true)
public class TaskEventStreamApplicationService implements TaskEventStreamQuery {

    public static final int MAX_BATCH_SIZE = 100;

    private final TaskEventQueryRepository repository;
    private final Clock clock;

    @Autowired
    public TaskEventStreamApplicationService(TaskEventQueryRepository repository) {
        this(repository, Clock.systemUTC());
    }

    TaskEventStreamApplicationService(TaskEventQueryRepository repository, Clock clock) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
    }

    @Override
    public TaskEventBatch read(UUID taskId, String afterEventId, int limit, AccessContext accessContext) {
        Objects.requireNonNull(taskId, "taskId must not be null");
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        if (!accessContext.authorities().contains(TaskPermissions.READ)) {
            throw new TaskAccessDeniedException(TaskPermissions.READ);
        }
        if (limit < 1 || limit > MAX_BATCH_SIZE) {
            throw new IllegalArgumentException("event replay limit must be between 1 and " + MAX_BATCH_SIZE);
        }

        var tenantId = accessContext.tenantId().value();
        var actorId = accessContext.actorId().value();
        var state = repository.findVisibleState(tenantId, actorId, taskId)
                .orElseThrow(TaskNotFoundException::new);

        long afterSequence = 0;
        if (afterEventId != null) {
            var cursor = repository.findCursor(tenantId, taskId, afterEventId);
            if (cursor.isEmpty()) {
                return reset(taskId, state, "CURSOR_EXPIRED");
            }
            if (!state.visibilityVersion().equals(cursor.get().visibilityVersion())) {
                return reset(taskId, state, "VISIBILITY_CHANGED");
            }
            afterSequence = cursor.get().streamSequence();
        }

        // The event query repeats the active-participant predicate, closing the revoke race
        // between state lookup and payload delivery.
        var events = repository.findVisibleAfter(tenantId, actorId, taskId, afterSequence, limit).stream()
                .map(event -> TaskEventEnvelope.persisted(
                        event.eventId(),
                        event.taskId(),
                        event.taskVersion(),
                        event.occurredAt(),
                        event.visibilityVersion(),
                        event.traceId()
                ))
                .toList();
        return new TaskEventBatch(events, false);
    }

    private TaskEventBatch reset(
            UUID taskId,
            TaskEventQueryRepository.TaskStreamState state,
            String reason
    ) {
        var resetId = "reset:" + UUID.randomUUID();
        var envelope = new TaskEventEnvelope(
                1,
                resetId,
                "TASK",
                taskId.toString(),
                "stream.reset_required",
                "STREAM",
                taskId.toString(),
                state.taskVersion(),
                clock.instant(),
                state.visibilityVersion(),
                UUID.randomUUID().toString(),
                Map.of(
                        "reason", reason,
                        "recoveryResource", "/api/v1/tasks/" + taskId,
                        "message", "任务事件游标不可继续使用，请重新获取任务快照。"
                )
        );
        return new TaskEventBatch(List.of(envelope), true);
    }
}

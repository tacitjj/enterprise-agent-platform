package com.dianlian.platform.task.application;

import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface TaskEventQueryRepository {

    Optional<TaskStreamState> findVisibleState(UUID tenantId, UUID actorId, UUID taskId);

    Optional<TaskEventCursor> findCursor(UUID tenantId, UUID taskId, String eventId);

    List<PersistedTaskEvent> findVisibleAfter(
            UUID tenantId,
            UUID actorId,
            UUID taskId,
            long streamSequence,
            int limit
    );

    record TaskStreamState(long taskVersion, String visibilityVersion) {
    }

    record TaskEventCursor(long streamSequence, String visibilityVersion) {
    }

    record PersistedTaskEvent(
            long streamSequence,
            UUID eventId,
            UUID taskId,
            long taskVersion,
            String visibilityVersion,
            UUID traceId,
            Instant occurredAt
    ) {
    }
}

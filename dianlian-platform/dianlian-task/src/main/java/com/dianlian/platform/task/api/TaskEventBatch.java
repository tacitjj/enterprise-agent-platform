package com.dianlian.platform.task.api;

import java.util.List;
import java.util.Objects;

public record TaskEventBatch(List<TaskEventEnvelope> events, boolean resetRequired) {

    public TaskEventBatch {
        events = List.copyOf(Objects.requireNonNull(events, "events must not be null"));
        if (resetRequired && (events.size() != 1
                || !"stream.reset_required".equals(events.getFirst().eventType()))) {
            throw new IllegalArgumentException("reset batch must contain exactly one reset event");
        }
    }

    public String lastEventId(String fallback) {
        return events.isEmpty() ? fallback : events.getLast().eventId();
    }
}

package com.dianlian.platform.task.api;

import java.time.Instant;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/**
 * A persisted task-stream notification. The task snapshot remains the authoritative business state.
 */
public record TaskEventEnvelope(
        int schemaVersion,
        String eventId,
        String streamType,
        String streamId,
        String eventType,
        String aggregateType,
        String aggregateId,
        long aggregateVersion,
        Instant occurredAt,
        String visibilityVersion,
        String traceId,
        Map<String, Object> payload
) {

    public TaskEventEnvelope {
        if (schemaVersion != 1) {
            throw new IllegalArgumentException("task event schemaVersion must be 1");
        }
        eventId = requireText(eventId, "eventId");
        streamType = requireText(streamType, "streamType");
        streamId = requireText(streamId, "streamId");
        eventType = requireText(eventType, "eventType");
        aggregateType = requireText(aggregateType, "aggregateType");
        aggregateId = requireText(aggregateId, "aggregateId");
        if (aggregateVersion < 0) {
            throw new IllegalArgumentException("aggregateVersion must not be negative");
        }
        Objects.requireNonNull(occurredAt, "occurredAt must not be null");
        visibilityVersion = requireText(visibilityVersion, "visibilityVersion");
        traceId = requireText(traceId, "traceId");
        payload = Collections.unmodifiableMap(new LinkedHashMap<>(Objects.requireNonNull(
                payload,
                "payload must not be null"
        )));
    }

    public static TaskEventEnvelope persisted(
            UUID eventId,
            UUID taskId,
            long taskVersion,
            Instant occurredAt,
            String visibilityVersion,
            UUID traceId
    ) {
        return new TaskEventEnvelope(
                1,
                eventId.toString(),
                "TASK",
                taskId.toString(),
                "task.snapshot.invalidated",
                "TASK",
                taskId.toString(),
                taskVersion,
                occurredAt,
                visibilityVersion,
                traceId.toString(),
                Map.of(
                        "taskId", taskId,
                        "reason", "TASK_CHANGED"
                )
        );
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}

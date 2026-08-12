package com.dianlian.platform.task.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record TaskCommandAccepted(
        UUID taskId,
        long taskVersion,
        TaskStatus status,
        Instant acceptedAt,
        String statusUrl,
        String eventsUrl,
        UUID resumeEventId,
        boolean idempotencyReplayed
) {

    public TaskCommandAccepted {
        Objects.requireNonNull(taskId, "taskId must not be null");
        if (taskVersion < 1) {
            throw new IllegalArgumentException("taskVersion must be positive");
        }
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(acceptedAt, "acceptedAt must not be null");
        statusUrl = requireText(statusUrl, "statusUrl");
        eventsUrl = requireText(eventsUrl, "eventsUrl");
        Objects.requireNonNull(resumeEventId, "resumeEventId must not be null");
    }

    public TaskCommandAccepted asReplay() {
        return idempotencyReplayed ? this : new TaskCommandAccepted(
                taskId,
                taskVersion,
                status,
                acceptedAt,
                statusUrl,
                eventsUrl,
                resumeEventId,
                true
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

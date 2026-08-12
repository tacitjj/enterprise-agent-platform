package com.dianlian.platform.task.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record RuntimeAdmission(UUID runtimeRunId, Instant acceptedAt) {

    public RuntimeAdmission {
        Objects.requireNonNull(runtimeRunId, "runtimeRunId must not be null");
        Objects.requireNonNull(acceptedAt, "acceptedAt must not be null");
    }
}

package com.dianlian.platform.employee.api;

import java.util.Objects;

public record CommandOutcome<T>(T resource, boolean replayed) {

    public CommandOutcome {
        Objects.requireNonNull(resource, "resource must not be null");
    }
}

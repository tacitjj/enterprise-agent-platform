package com.dianlian.platform.model.api;

import java.util.Objects;

public record ModelCommandOutcome<T>(T resource, boolean replayed) {
    public ModelCommandOutcome {
        Objects.requireNonNull(resource, "resource must not be null");
    }
}

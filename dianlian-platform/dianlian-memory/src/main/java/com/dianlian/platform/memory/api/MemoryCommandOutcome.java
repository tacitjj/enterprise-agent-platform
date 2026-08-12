package com.dianlian.platform.memory.api;

import java.util.Objects;

public record MemoryCommandOutcome<T>(T value, boolean replayed) {

    public MemoryCommandOutcome {
        Objects.requireNonNull(value, "value must not be null");
    }
}

package com.dianlian.platform.memory.api;

import java.util.Objects;
import java.util.UUID;

public record MemoryScopeRef(MemoryScopeType scopeType, UUID scopeId) {

    public MemoryScopeRef {
        Objects.requireNonNull(scopeType, "scopeType must not be null");
        Objects.requireNonNull(scopeId, "scopeId must not be null");
    }
}

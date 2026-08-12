package com.dianlian.platform.memory.api;

import java.util.Objects;

public final class MemoryCommandConflictException extends RuntimeException {

    private final String code;

    public MemoryCommandConflictException(String code, String message) {
        super(message);
        this.code = Objects.requireNonNull(code, "code must not be null");
    }

    public String code() {
        return code;
    }
}

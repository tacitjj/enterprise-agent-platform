package com.dianlian.platform.memory.api;

public final class MemoryAccessDeniedException extends RuntimeException {

    public MemoryAccessDeniedException(String permission) {
        super("missing memory permission: " + permission);
    }
}

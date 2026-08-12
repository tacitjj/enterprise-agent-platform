package com.dianlian.platform.memory.api;

public final class MemoryResourceNotDiscoverableException extends RuntimeException {

    public MemoryResourceNotDiscoverableException() {
        super("memory resource is not discoverable");
    }
}

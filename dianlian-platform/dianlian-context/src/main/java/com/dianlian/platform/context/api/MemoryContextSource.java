package com.dianlian.platform.context.api;

public interface MemoryContextSource {
    ContextSourceResult recall(MemoryContextRequest request);
}

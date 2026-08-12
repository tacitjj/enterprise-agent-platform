package com.dianlian.platform.knowledge.api;

public final class KnowledgeResourceNotDiscoverableException extends RuntimeException {

    public KnowledgeResourceNotDiscoverableException() {
        super("knowledge resource is not discoverable");
    }
}

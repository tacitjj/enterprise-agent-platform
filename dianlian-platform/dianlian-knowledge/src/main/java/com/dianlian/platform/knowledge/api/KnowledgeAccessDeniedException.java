package com.dianlian.platform.knowledge.api;

public final class KnowledgeAccessDeniedException extends RuntimeException {

    public KnowledgeAccessDeniedException(String permission) {
        super("missing knowledge permission: " + permission);
    }
}

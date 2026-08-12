package com.dianlian.platform.knowledge.api;

import java.util.Objects;

public final class KnowledgeCommandConflictException extends RuntimeException {

    private final String code;

    public KnowledgeCommandConflictException(String code, String message) {
        super(message);
        this.code = Objects.requireNonNull(code, "code must not be null");
    }

    public String code() {
        return code;
    }
}

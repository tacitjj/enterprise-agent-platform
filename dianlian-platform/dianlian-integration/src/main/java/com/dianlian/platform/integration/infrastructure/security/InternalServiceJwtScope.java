package com.dianlian.platform.integration.infrastructure.security;

public enum InternalServiceJwtScope {
    CONTEXT_INDEX_WRITE("context.index.write"),
    CONTEXT_RETRIEVE("context.retrieve");

    private final String value;

    InternalServiceJwtScope(String value) {
        this.value = value;
    }

    public String value() {
        return value;
    }
}

package com.dianlian.platform.context.api;

public final class ContextAuthorityViolationException extends RuntimeException {

    private final String code;

    public ContextAuthorityViolationException(String code) {
        super("Context authority rejected the invocation: " + code);
        if (code == null || !code.matches("^[A-Z0-9_]{1,128}$")) {
            throw new IllegalArgumentException("context authority failure code is invalid");
        }
        this.code = code;
    }

    public String code() {
        return code;
    }
}

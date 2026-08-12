package com.dianlian.platform.integration.infrastructure.context;

final class ContextIndexingRuntimeException extends RuntimeException {

    private final String code;
    private final boolean retryable;

    private ContextIndexingRuntimeException(String code, boolean retryable, Throwable cause) {
        super(code, cause);
        this.code = code;
        this.retryable = retryable;
    }

    static ContextIndexingRuntimeException retryable(String code, Throwable cause) {
        return new ContextIndexingRuntimeException(code, true, cause);
    }

    static ContextIndexingRuntimeException permanent(String code, Throwable cause) {
        return new ContextIndexingRuntimeException(code, false, cause);
    }

    String code() {
        return code;
    }

    boolean retryable() {
        return retryable;
    }

    String safeMessage() {
        return "Context indexing runtime failure: " + code;
    }
}

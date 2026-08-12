package com.dianlian.platform.task.api;

public final class RuntimeUnavailableException extends RuntimeException {

    public static final String ERROR_CODE = "RUNTIME_UNAVAILABLE";

    public RuntimeUnavailableException(String message) {
        super(message);
    }

    public String errorCode() {
        return ERROR_CODE;
    }
}

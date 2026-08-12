package com.dianlian.platform.task.api;

public final class IdempotencyRequestConflictException extends RuntimeException {

    public static final String ERROR_CODE = "IDEMPOTENCY_REQUEST_CONFLICT";

    public IdempotencyRequestConflictException() {
        super("The idempotency key was already used for a different task request");
    }

    public String errorCode() {
        return ERROR_CODE;
    }
}

package com.dianlian.platform.task.api;

public final class TaskAdmissionRejectedException extends RuntimeException {

    private final String errorCode;

    public TaskAdmissionRejectedException(String errorCode, String message) {
        super(message);
        if (errorCode == null || errorCode.isBlank()) {
            throw new IllegalArgumentException("errorCode must not be blank");
        }
        this.errorCode = errorCode;
    }

    public String errorCode() {
        return errorCode;
    }
}

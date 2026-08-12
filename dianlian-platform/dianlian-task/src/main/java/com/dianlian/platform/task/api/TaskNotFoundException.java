package com.dianlian.platform.task.api;

public final class TaskNotFoundException extends RuntimeException {

    public static final String ERROR_CODE = "RESOURCE_NOT_DISCOVERABLE";

    public TaskNotFoundException() {
        super("Task was not found or is not visible to the current actor");
    }

    public String errorCode() {
        return ERROR_CODE;
    }
}

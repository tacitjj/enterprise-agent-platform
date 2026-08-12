package com.dianlian.platform.task.api;

public final class TaskAccessDeniedException extends RuntimeException {

    private final String permission;

    public TaskAccessDeniedException(String permission) {
        super("Missing task permission: " + permission);
        this.permission = permission;
    }

    public String permission() {
        return permission;
    }
}

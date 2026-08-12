package com.dianlian.platform.task.api;

public final class TaskEventStreamUnavailableException extends RuntimeException {

    public TaskEventStreamUnavailableException() {
        super("Task event stream capacity is temporarily unavailable");
    }
}

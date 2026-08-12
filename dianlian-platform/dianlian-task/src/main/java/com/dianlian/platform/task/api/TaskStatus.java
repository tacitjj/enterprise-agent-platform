package com.dianlian.platform.task.api;

public enum TaskStatus {
    DRAFT,
    PLANNING,
    WAITING_USER,
    QUEUED,
    RUNNING,
    APPLYING_GUIDANCE,
    REPLANNING,
    WAITING_CONFIRMATION,
    WAITING_APPROVAL,
    PAUSED,
    SUCCEEDED,
    PARTIAL_SUCCESS,
    FAILED,
    CANCELLED
}

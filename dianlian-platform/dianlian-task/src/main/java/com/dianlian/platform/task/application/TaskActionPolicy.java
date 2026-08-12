package com.dianlian.platform.task.application;

import com.dianlian.platform.task.api.TaskAllowedAction;
import com.dianlian.platform.task.api.TaskDisplayStatus;
import com.dianlian.platform.task.api.TaskStatus;
import java.util.EnumSet;
import java.util.Set;

public final class TaskActionPolicy {

    private TaskActionPolicy() {
    }

    public static Set<TaskAllowedAction> allowedActions(TaskStatus status) {
        return switch (status) {
            case DRAFT, PLANNING -> EnumSet.of(
                    TaskAllowedAction.VIEW,
                    TaskAllowedAction.ADD_CONTEXT,
                    TaskAllowedAction.CHANGE_CONSTRAINT,
                    TaskAllowedAction.CHANGE_GOAL,
                    TaskAllowedAction.CANCEL
            );
            case WAITING_USER, WAITING_CONFIRMATION -> EnumSet.of(
                    TaskAllowedAction.VIEW,
                    TaskAllowedAction.ADD_CONTEXT,
                    TaskAllowedAction.CORRECT_FACT,
                    TaskAllowedAction.ANSWER_CHECKPOINT,
                    TaskAllowedAction.CANCEL
            );
            case QUEUED, RUNNING, APPLYING_GUIDANCE, REPLANNING -> EnumSet.of(
                    TaskAllowedAction.VIEW,
                    TaskAllowedAction.ADD_CONTEXT,
                    TaskAllowedAction.CORRECT_FACT,
                    TaskAllowedAction.CHANGE_CONSTRAINT,
                    TaskAllowedAction.STYLE_GUIDANCE,
                    TaskAllowedAction.PAUSE,
                    TaskAllowedAction.CANCEL
            );
            case WAITING_APPROVAL -> EnumSet.of(TaskAllowedAction.VIEW, TaskAllowedAction.CANCEL);
            case PAUSED -> EnumSet.of(
                    TaskAllowedAction.VIEW,
                    TaskAllowedAction.ADD_CONTEXT,
                    TaskAllowedAction.RESUME,
                    TaskAllowedAction.CANCEL
            );
            case FAILED -> EnumSet.of(
                    TaskAllowedAction.VIEW,
                    TaskAllowedAction.RETRY_FROM_STEP,
                    TaskAllowedAction.CANCEL
            );
            case SUCCEEDED, PARTIAL_SUCCESS, CANCELLED -> EnumSet.of(TaskAllowedAction.VIEW);
        };
    }

    public static TaskDisplayStatus displayStatus(TaskStatus status) {
        return switch (status) {
            case DRAFT, PLANNING -> TaskDisplayStatus.DRAFT;
            case WAITING_USER, WAITING_CONFIRMATION -> TaskDisplayStatus.WAITING_USER;
            case WAITING_APPROVAL -> TaskDisplayStatus.WAITING_APPROVAL;
            case FAILED -> TaskDisplayStatus.NEEDS_ATTENTION;
            case SUCCEEDED, PARTIAL_SUCCESS, CANCELLED -> TaskDisplayStatus.ENDED;
            default -> TaskDisplayStatus.PROCESSING;
        };
    }
}

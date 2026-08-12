package com.dianlian.platform.task.application;

import com.dianlian.platform.task.api.TaskCommandAccepted;

public record IdempotencyDecision(boolean claimed, TaskCommandAccepted replayedResponse) {

    public IdempotencyDecision {
        if (claimed == (replayedResponse != null)) {
            throw new IllegalArgumentException("claimed and replayedResponse must describe exactly one outcome");
        }
    }

    public static IdempotencyDecision newClaim() {
        return new IdempotencyDecision(true, null);
    }

    public static IdempotencyDecision replay(TaskCommandAccepted response) {
        return new IdempotencyDecision(false, response.asReplay());
    }
}

package com.dianlian.platform.task.domain;

public record ExecutionGeneration(long value) {

    public ExecutionGeneration {
        if (value < 1) {
            throw new IllegalArgumentException("execution generation must be positive");
        }
    }

    public static ExecutionGeneration initial() {
        return new ExecutionGeneration(1);
    }

    public ExecutionGeneration next() {
        return new ExecutionGeneration(Math.addExact(value, 1));
    }
}

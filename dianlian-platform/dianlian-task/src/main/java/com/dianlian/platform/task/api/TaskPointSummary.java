package com.dianlian.platform.task.api;

public record TaskPointSummary(
        long estimatedUpperBound,
        long reserved,
        long captured,
        long released,
        long pendingSettlement
) {

    public TaskPointSummary {
        if (estimatedUpperBound < 0 || reserved < 0 || captured < 0 || released < 0 || pendingSettlement < 0) {
            throw new IllegalArgumentException("point summary values must not be negative");
        }
    }
}

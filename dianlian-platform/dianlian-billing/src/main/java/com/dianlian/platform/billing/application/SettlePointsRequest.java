package com.dianlian.platform.billing.application;

import com.dianlian.platform.billing.api.SettlePointsCommand;
import java.time.Instant;
import java.util.Objects;

public record SettlePointsRequest(SettlePointsCommand command, Instant occurredAt) {
    public SettlePointsRequest {
        Objects.requireNonNull(command, "command must not be null");
        Objects.requireNonNull(occurredAt, "occurredAt must not be null");
    }
}

package com.dianlian.platform.billing.domain;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record PointLot(
        UUID id,
        UUID accountId,
        long availableAmount,
        long reservedAmount,
        Instant expiresAt,
        int priority,
        PointLotStatus status
) {

    public PointLot {
        Objects.requireNonNull(id, "id must not be null");
        Objects.requireNonNull(accountId, "accountId must not be null");
        Objects.requireNonNull(status, "status must not be null");
        if (availableAmount < 0 || reservedAmount < 0) {
            throw new IllegalArgumentException("point lot amounts must not be negative");
        }
    }
}

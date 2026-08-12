package com.dianlian.platform.billing.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record PointReservationResult(
        UUID reservationId,
        UUID accountId,
        long reservedAmount,
        String status,
        Instant createdAt,
        boolean idempotencyReplayed
) {

    public PointReservationResult {
        Objects.requireNonNull(reservationId, "reservationId must not be null");
        Objects.requireNonNull(accountId, "accountId must not be null");
        if (reservedAmount < 1) {
            throw new IllegalArgumentException("reservedAmount must be positive");
        }
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }
}

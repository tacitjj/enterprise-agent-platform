package com.dianlian.platform.billing.domain;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record PointReservation(
        UUID id,
        UUID accountId,
        long amount,
        PointReservationStatus status,
        Instant createdAt
) {

    public PointReservation {
        Objects.requireNonNull(id, "id must not be null");
        Objects.requireNonNull(accountId, "accountId must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
        if (amount < 1) {
            throw new IllegalArgumentException("amount must be positive");
        }
    }
}

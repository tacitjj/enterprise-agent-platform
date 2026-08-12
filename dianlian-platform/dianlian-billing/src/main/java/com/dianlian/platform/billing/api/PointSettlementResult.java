package com.dianlian.platform.billing.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record PointSettlementResult(
        UUID settlementId,
        UUID reservationId,
        long capturedAmount,
        long releasedAmount,
        String reservationStatus,
        Instant settledAt,
        boolean replayed
) {
    public PointSettlementResult {
        Objects.requireNonNull(settlementId, "settlementId must not be null");
        Objects.requireNonNull(reservationId, "reservationId must not be null");
        if (capturedAmount < 0 || releasedAmount < 0) {
            throw new IllegalArgumentException("settlement amounts cannot be negative");
        }
        Objects.requireNonNull(reservationStatus, "reservationStatus must not be null");
        Objects.requireNonNull(settledAt, "settledAt must not be null");
    }
}

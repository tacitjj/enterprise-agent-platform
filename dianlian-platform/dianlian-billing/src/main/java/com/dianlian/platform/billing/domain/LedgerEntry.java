package com.dianlian.platform.billing.domain;

import java.util.Objects;
import java.util.UUID;

public record LedgerEntry(
        UUID ledgerAccountId,
        UUID pointLotId,
        LedgerDirection direction,
        long amount,
        int sequence
) {

    public LedgerEntry {
        Objects.requireNonNull(ledgerAccountId, "ledgerAccountId must not be null");
        Objects.requireNonNull(pointLotId, "pointLotId must not be null");
        Objects.requireNonNull(direction, "direction must not be null");
        if (amount < 1 || sequence < 1) {
            throw new IllegalArgumentException("amount and sequence must be positive");
        }
    }
}

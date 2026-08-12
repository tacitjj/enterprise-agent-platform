package com.dianlian.platform.billing.domain;

import java.util.Objects;
import java.util.UUID;

public record PointAccount(
        UUID id,
        UUID tenantId,
        UUID ledgerScopeId,
        PointAccountStatus status,
        long availableAmount,
        long reservedAmount,
        long version
) {

    public PointAccount {
        Objects.requireNonNull(id, "id must not be null");
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(ledgerScopeId, "ledgerScopeId must not be null");
        Objects.requireNonNull(status, "status must not be null");
        if (availableAmount < 0 || reservedAmount < 0 || version < 0) {
            throw new IllegalArgumentException("point account amounts and version must not be negative");
        }
    }
}

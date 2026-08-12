package com.dianlian.platform.billing.api;

import java.util.Objects;
import java.util.UUID;

public record SettlePointsCommand(
        UUID tenantId,
        UUID actorId,
        UUID reservationId,
        long capturedAmount,
        String idempotencyKey,
        String requestHash,
        String reasonCode
) {
    public SettlePointsCommand {
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(actorId, "actorId must not be null");
        Objects.requireNonNull(reservationId, "reservationId must not be null");
        if (capturedAmount < 0) throw new IllegalArgumentException("capturedAmount cannot be negative");
        idempotencyKey = requireText(idempotencyKey, "idempotencyKey", 160);
        requestHash = requireText(requestHash, "requestHash", 128);
        reasonCode = requireText(reasonCode, "reasonCode", 64);
    }

    private static String requireText(String value, String fieldName, int maxLength) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        var normalized = value.trim();
        if (normalized.isEmpty() || normalized.length() > maxLength) {
            throw new IllegalArgumentException(fieldName + " is invalid");
        }
        return normalized;
    }
}

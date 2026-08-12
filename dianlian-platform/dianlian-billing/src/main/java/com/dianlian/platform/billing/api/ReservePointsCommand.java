package com.dianlian.platform.billing.api;

import java.util.Objects;
import java.util.UUID;
import java.util.regex.Pattern;

public record ReservePointsCommand(
        String businessType,
        UUID businessId,
        String billingScopeType,
        UUID billingScopeId,
        long amount,
        String idempotencyKey
) {

    private static final Pattern CODE_PATTERN = Pattern.compile("^[A-Z][A-Z0-9_]{1,63}$");

    public ReservePointsCommand {
        businessType = requireCode(businessType, "businessType");
        Objects.requireNonNull(businessId, "businessId must not be null");
        billingScopeType = requireCode(billingScopeType, "billingScopeType");
        Objects.requireNonNull(billingScopeId, "billingScopeId must not be null");
        if (amount < 1) {
            throw new IllegalArgumentException("amount must be positive");
        }
        idempotencyKey = requireText(idempotencyKey, "idempotencyKey", 200);
    }

    private static String requireCode(String value, String name) {
        value = requireText(value, name, 64);
        if (!CODE_PATTERN.matcher(value).matches()) {
            throw new IllegalArgumentException(name + " must be an uppercase stable code");
        }
        return value;
    }

    private static String requireText(String value, String name, int maxLength) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank() || value.length() > maxLength) {
            throw new IllegalArgumentException(name + " must contain 1 to " + maxLength + " characters");
        }
        return value;
    }
}

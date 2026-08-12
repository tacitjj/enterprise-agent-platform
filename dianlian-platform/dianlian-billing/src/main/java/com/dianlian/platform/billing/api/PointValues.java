package com.dianlian.platform.billing.api;

import java.math.BigDecimal;
import java.util.Objects;
import java.util.regex.Pattern;

/**
 * Converts between the public fixed-point point value and the integer ledger unit.
 */
public final class PointValues {

    public static final long MICRO_CREDITS_PER_POINT = 1_000_000L;

    private static final int DISPLAY_SCALE = 6;
    private static final Pattern DISPLAY_PATTERN = Pattern.compile("^(0|[1-9][0-9]*)(\\.[0-9]{1,6})?$");

    private PointValues() {
    }

    public static long parseDisplayValue(String value) {
        Objects.requireNonNull(value, "point value must not be null");
        if (!DISPLAY_PATTERN.matcher(value).matches()) {
            throw new IllegalArgumentException("point value must be a non-negative decimal with at most 6 decimals");
        }
        try {
            return new BigDecimal(value).movePointRight(DISPLAY_SCALE).longValueExact();
        } catch (ArithmeticException exception) {
            throw new IllegalArgumentException("point value exceeds the supported ledger range", exception);
        }
    }

    public static String formatDisplayValue(long microCredits) {
        if (microCredits < 0) {
            throw new IllegalArgumentException("microCredits must not be negative");
        }
        return BigDecimal.valueOf(microCredits, DISPLAY_SCALE)
                .stripTrailingZeros()
                .toPlainString();
    }
}

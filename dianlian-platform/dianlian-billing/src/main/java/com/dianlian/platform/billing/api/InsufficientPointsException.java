package com.dianlian.platform.billing.api;

public final class InsufficientPointsException extends RuntimeException {

    public static final String ERROR_CODE = "POINT_BALANCE_INSUFFICIENT";

    private final long available;
    private final long required;

    public InsufficientPointsException(long available, long required) {
        super("Available points are lower than the requested reservation");
        this.available = available;
        this.required = required;
    }

    public String errorCode() {
        return ERROR_CODE;
    }

    public long available() {
        return available;
    }

    public long required() {
        return required;
    }
}

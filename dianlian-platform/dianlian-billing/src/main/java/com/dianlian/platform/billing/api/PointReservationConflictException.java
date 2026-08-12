package com.dianlian.platform.billing.api;

public final class PointReservationConflictException extends RuntimeException {

    public static final String ERROR_CODE = "POINT_RESERVATION_CONFLICT";

    public PointReservationConflictException(String message) {
        super(message);
    }

    public String errorCode() {
        return ERROR_CODE;
    }
}

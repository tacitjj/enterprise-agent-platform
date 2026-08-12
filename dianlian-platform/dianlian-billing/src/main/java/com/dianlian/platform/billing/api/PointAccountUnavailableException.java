package com.dianlian.platform.billing.api;

public final class PointAccountUnavailableException extends RuntimeException {

    public static final String ERROR_CODE = "POINT_ACCOUNT_UNAVAILABLE";

    public PointAccountUnavailableException(String message) {
        super(message);
    }

    public String errorCode() {
        return ERROR_CODE;
    }
}

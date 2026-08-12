package com.dianlian.platform.identity.api;

public final class InvalidRefreshTokenException extends RuntimeException {

    public InvalidRefreshTokenException() {
        super("The supplied refresh token is invalid");
    }
}

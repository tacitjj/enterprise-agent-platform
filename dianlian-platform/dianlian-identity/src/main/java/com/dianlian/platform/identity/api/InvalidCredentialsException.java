package com.dianlian.platform.identity.api;

public final class InvalidCredentialsException extends RuntimeException {

    public InvalidCredentialsException() {
        super("The supplied credentials are invalid");
    }
}

package com.dianlian.platform.identity.api;

public final class ActiveTenantRequiredException extends RuntimeException {

    public ActiveTenantRequiredException() {
        super("An active tenant is required for this operation");
    }
}

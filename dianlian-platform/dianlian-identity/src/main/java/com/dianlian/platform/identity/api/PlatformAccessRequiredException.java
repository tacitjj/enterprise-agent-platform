package com.dianlian.platform.identity.api;

public final class PlatformAccessRequiredException extends RuntimeException {

    public PlatformAccessRequiredException() {
        super("A tenantless platform-scoped session is required");
    }
}

package com.dianlian.platform.context.api;

/**
 * The projection worker no longer owns the database lease or attempted to acknowledge it after expiry.
 */
public final class ContextIndexLeaseLostException extends RuntimeException {

    public ContextIndexLeaseLostException() {
        super("context index job lease is no longer owned by this worker attempt");
    }
}

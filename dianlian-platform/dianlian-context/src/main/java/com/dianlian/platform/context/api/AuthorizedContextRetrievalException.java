package com.dianlian.platform.context.api;

import java.util.Objects;
import java.util.regex.Pattern;

/**
 * Stable, redacted failure raised by an {@link AuthorizedContextRetrievalPort} adapter.
 */
public final class AuthorizedContextRetrievalException extends RuntimeException {

    private static final Pattern CODE = Pattern.compile("^[A-Z0-9_]{1,128}$");

    private final String code;
    private final boolean retryable;

    public AuthorizedContextRetrievalException(String code, boolean retryable) {
        super(safeMessage(code));
        this.code = code;
        this.retryable = retryable;
    }

    public String code() {
        return code;
    }

    public boolean retryable() {
        return retryable;
    }

    private static String safeMessage(String code) {
        Objects.requireNonNull(code, "code must not be null");
        if (!CODE.matcher(code).matches()) {
            throw new IllegalArgumentException("authorized context retrieval failure code is invalid");
        }
        return "Authorized context retrieval failed: " + code;
    }
}

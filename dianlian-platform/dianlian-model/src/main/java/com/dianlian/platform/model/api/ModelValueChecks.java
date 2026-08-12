package com.dianlian.platform.model.api;

import java.net.URI;
import java.util.Objects;
import java.util.regex.Pattern;

final class ModelValueChecks {
    private static final Pattern CODE = Pattern.compile("^[A-Z][A-Z0-9_.-]{1,127}$");
    private static final Pattern CREDENTIAL_REF = Pattern.compile("^env:DIANLIAN_MODEL_[A-Z0-9_]{1,113}$");

    private ModelValueChecks() {
    }

    static String code(String value, String fieldName, int maxLength) {
        var normalized = text(value, fieldName, maxLength).toUpperCase();
        if (!CODE.matcher(normalized).matches()) throw new IllegalArgumentException(fieldName + " is invalid");
        return normalized;
    }

    static String text(String value, String fieldName, int maxLength) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        var normalized = value.trim();
        if (normalized.isEmpty() || normalized.length() > maxLength) {
            throw new IllegalArgumentException(fieldName + " is invalid");
        }
        return normalized;
    }

    static String credentialRef(String value) {
        var normalized = text(value, "credentialRef", 132);
        if (!CREDENTIAL_REF.matcher(normalized).matches()) {
            throw new IllegalArgumentException(
                    "credentialRef must reference a DIANLIAN_MODEL_ environment secret");
        }
        return normalized;
    }

    static String url(String value, String fieldName) {
        var normalized = text(value, fieldName, 2_048);
        var uri = URI.create(normalized);
        if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null) {
            throw new IllegalArgumentException(fieldName + " must be an HTTPS URL");
        }
        return normalized.replaceAll("/+$", "");
    }
}

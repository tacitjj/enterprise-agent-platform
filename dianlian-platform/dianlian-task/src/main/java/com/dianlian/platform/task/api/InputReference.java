package com.dianlian.platform.task.api;

import java.util.Objects;
import java.util.UUID;

public record InputReference(InputReferenceType refType, UUID refId, String version) {

    public InputReference {
        Objects.requireNonNull(refType, "refType must not be null");
        Objects.requireNonNull(refId, "refId must not be null");
        version = requireText(version, "version", 128);
    }

    private static String requireText(String value, String name, int maxLength) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank() || value.length() > maxLength) {
            throw new IllegalArgumentException(name + " must contain 1 to " + maxLength + " characters");
        }
        return value;
    }
}

package com.dianlian.platform.task.application;

import java.util.Objects;

public record HashedTaskRequest(String requestHash, String canonicalJson) {

    public HashedTaskRequest {
        requestHash = requireText(requestHash, "requestHash");
        canonicalJson = requireText(canonicalJson, "canonicalJson");
    }

    private static String requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
        return value;
    }
}

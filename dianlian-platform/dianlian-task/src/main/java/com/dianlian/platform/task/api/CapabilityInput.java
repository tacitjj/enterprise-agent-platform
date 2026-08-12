package com.dianlian.platform.task.api;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Objects;
import java.util.regex.Pattern;

public record CapabilityInput(String schemaId, String schemaVersion, Map<String, Object> values) {

    private static final Pattern SCHEMA_ID = Pattern.compile("^[a-z][a-z0-9_.-]{1,127}$");

    public CapabilityInput {
        schemaId = requireText(schemaId, "schemaId", 128);
        if (!SCHEMA_ID.matcher(schemaId).matches()) {
            throw new IllegalArgumentException("schemaId is not a valid stable schema identifier");
        }
        schemaVersion = requireText(schemaVersion, "schemaVersion", 64);
        values = Collections.unmodifiableMap(new LinkedHashMap<>(Objects.requireNonNull(
                values,
                "values must not be null"
        )));
        if (values.size() > 200) {
            throw new IllegalArgumentException("values must contain at most 200 properties");
        }
    }

    private static String requireText(String value, String name, int maxLength) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank() || value.length() > maxLength) {
            throw new IllegalArgumentException(name + " must contain 1 to " + maxLength + " characters");
        }
        return value;
    }
}

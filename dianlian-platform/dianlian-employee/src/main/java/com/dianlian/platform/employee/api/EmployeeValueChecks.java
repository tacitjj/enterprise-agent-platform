package com.dianlian.platform.employee.api;

import java.util.regex.Pattern;

final class EmployeeValueChecks {

    private static final Pattern STABLE_CODE = Pattern.compile("[A-Za-z][A-Za-z0-9._-]*");
    private static final Pattern SCHEMA_ID = Pattern.compile("[a-z][a-z0-9_.-]{1,127}");
    private static final Pattern CAPABILITY_CODE = Pattern.compile("[A-Z][A-Z0-9_]{1,63}");

    private EmployeeValueChecks() {
    }

    static String nonBlank(String value, String field, int maxLength) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
        String normalized = value.trim();
        if (normalized.length() > maxLength) {
            throw new IllegalArgumentException(field + " exceeds " + maxLength + " characters");
        }
        return normalized;
    }

    static String optional(String value, String field, int maxLength) {
        if (value == null) {
            return null;
        }
        String normalized = value.trim();
        if (normalized.isEmpty()) {
            return null;
        }
        if (normalized.length() > maxLength) {
            throw new IllegalArgumentException(field + " exceeds " + maxLength + " characters");
        }
        return normalized;
    }

    static String stableCode(String value, String field, int maxLength) {
        String normalized = nonBlank(value, field, maxLength);
        if (!STABLE_CODE.matcher(normalized).matches()) {
            throw new IllegalArgumentException(field + " is not a stable code");
        }
        return normalized;
    }

    static String schemaId(String value) {
        String normalized = nonBlank(value, "schemaId", 128);
        if (!SCHEMA_ID.matcher(normalized).matches()) {
            throw new IllegalArgumentException("schemaId does not match the public contract");
        }
        return normalized;
    }

    static String capabilityCode(String value) {
        String normalized = nonBlank(value, "capabilityCode", 64);
        if (!CAPABILITY_CODE.matcher(normalized).matches()) {
            throw new IllegalArgumentException("capabilityCode does not match the public contract");
        }
        return normalized;
    }
}

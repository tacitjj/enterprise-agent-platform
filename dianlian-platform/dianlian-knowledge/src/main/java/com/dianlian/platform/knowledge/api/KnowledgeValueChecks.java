package com.dianlian.platform.knowledge.api;

import java.util.Locale;
import java.util.regex.Pattern;

final class KnowledgeValueChecks {

    private static final Pattern CONTENT_HASH = Pattern.compile("^[0-9a-f]{64,128}$");
    private static final Pattern SPACE_CODE = Pattern.compile("^[A-Za-z][A-Za-z0-9._-]{0,63}$");

    private KnowledgeValueChecks() {
    }

    static String nonBlank(String value, String field, int maxLength) {
        if (value == null) {
            throw new IllegalArgumentException(field + " must not be null");
        }
        String normalized = value.trim();
        if (normalized.isEmpty() || normalized.length() > maxLength) {
            throw new IllegalArgumentException(field + " is invalid");
        }
        return normalized;
    }

    static String contentHash(String value) {
        String normalized = nonBlank(value, "contentHash", 128).toLowerCase(Locale.ROOT);
        if (!CONTENT_HASH.matcher(normalized).matches()) {
            throw new IllegalArgumentException("contentHash must be a lowercase hexadecimal digest");
        }
        return normalized;
    }

    static String sha256(String value, String field) {
        String normalized = nonBlank(value, field, 64).toLowerCase(Locale.ROOT);
        if (normalized.length() != 64 || !CONTENT_HASH.matcher(normalized).matches()) {
            throw new IllegalArgumentException(field + " must be a lowercase SHA-256 digest");
        }
        return normalized;
    }

    static String nonBlankText(String value, String field) {
        if (value == null) {
            throw new IllegalArgumentException(field + " must not be null");
        }
        if (value.trim().isEmpty()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
        return value;
    }

    static String spaceCode(String value) {
        String normalized = nonBlank(value, "spaceCode", 64);
        if (!SPACE_CODE.matcher(normalized).matches()) {
            throw new IllegalArgumentException("spaceCode is invalid");
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
            throw new IllegalArgumentException(field + " is invalid");
        }
        return normalized;
    }
}

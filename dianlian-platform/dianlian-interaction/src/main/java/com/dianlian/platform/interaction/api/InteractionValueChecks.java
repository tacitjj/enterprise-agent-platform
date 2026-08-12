package com.dianlian.platform.interaction.api;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

final class InteractionValueChecks {
    private InteractionValueChecks() {
    }

    static String text(String value, String fieldName, int maxLength) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        var normalized = value.trim();
        if (normalized.isEmpty() || normalized.length() > maxLength) {
            throw new IllegalArgumentException(fieldName + " is invalid");
        }
        return normalized;
    }

    static List<UUID> distinctIds(List<UUID> values, String fieldName, int maxItems) {
        Objects.requireNonNull(values, fieldName + " must not be null");
        if (values.size() > maxItems) throw new IllegalArgumentException(fieldName + " exceeds limit");
        var distinct = new LinkedHashSet<UUID>();
        for (var value : values) distinct.add(Objects.requireNonNull(value, fieldName + " contains null"));
        if (distinct.size() != values.size()) throw new IllegalArgumentException(fieldName + " contains duplicates");
        return List.copyOf(distinct);
    }
}

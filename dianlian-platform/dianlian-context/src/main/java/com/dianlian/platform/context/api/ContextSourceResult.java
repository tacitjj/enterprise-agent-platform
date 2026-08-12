package com.dianlian.platform.context.api;

import java.util.List;
import java.util.Objects;

public record ContextSourceResult(
        ContextSourceState state,
        List<ContextEvidence> evidence,
        String reasonCode
) {
    public ContextSourceResult {
        Objects.requireNonNull(state, "state must not be null");
        evidence = List.copyOf(Objects.requireNonNull(evidence, "evidence must not be null"));
        if (state == ContextSourceState.READY && evidence.isEmpty()) {
            throw new IllegalArgumentException("READY context source must include evidence");
        }
        if (state != ContextSourceState.READY && !evidence.isEmpty()) {
            throw new IllegalArgumentException("non-ready context source cannot include evidence");
        }
    }

    public static ContextSourceResult empty(String reasonCode) {
        return new ContextSourceResult(ContextSourceState.EMPTY, List.of(), reasonCode);
    }

    public static ContextSourceResult unavailable(String reasonCode) {
        return new ContextSourceResult(ContextSourceState.UNAVAILABLE, List.of(), reasonCode);
    }
}

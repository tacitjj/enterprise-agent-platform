package com.dianlian.platform.knowledge.api;

import java.util.Objects;

public record KnowledgeCommandOutcome<T>(T resource, boolean replayed) {

    public KnowledgeCommandOutcome {
        Objects.requireNonNull(resource, "resource must not be null");
    }
}

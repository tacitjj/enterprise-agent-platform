package com.dianlian.platform.knowledge.application;

import java.util.Objects;

public record KnowledgeWriteResult<T>(KnowledgeWriteStatus status, T resource) {

    public KnowledgeWriteResult {
        Objects.requireNonNull(status, "status must not be null");
        if ((status == KnowledgeWriteStatus.CREATED || status == KnowledgeWriteStatus.REPLAYED)
                != (resource != null)) {
            throw new IllegalArgumentException("successful writes require a resource and failed writes cannot expose one");
        }
    }

    public static <T> KnowledgeWriteResult<T> created(T resource) {
        return new KnowledgeWriteResult<>(KnowledgeWriteStatus.CREATED, resource);
    }

    public static <T> KnowledgeWriteResult<T> replayed(T resource) {
        return new KnowledgeWriteResult<>(KnowledgeWriteStatus.REPLAYED, resource);
    }

    public static <T> KnowledgeWriteResult<T> failed(KnowledgeWriteStatus status) {
        return new KnowledgeWriteResult<>(status, null);
    }
}

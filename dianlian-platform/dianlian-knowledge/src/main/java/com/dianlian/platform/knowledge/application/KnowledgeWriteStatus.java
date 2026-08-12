package com.dianlian.platform.knowledge.application;

public enum KnowledgeWriteStatus {
    CREATED,
    REPLAYED,
    IDEMPOTENCY_CONFLICT,
    RESOURCE_CONFLICT,
    NOT_FOUND,
    NOT_ACTIVE
}

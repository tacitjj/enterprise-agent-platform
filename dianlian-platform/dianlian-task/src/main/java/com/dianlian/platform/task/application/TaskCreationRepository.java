package com.dianlian.platform.task.application;

import java.time.Instant;
import java.util.UUID;

public interface TaskCreationRepository {

    IdempotencyDecision claim(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey,
            String requestHash,
            Instant occurredAt
    );

    void insert(TaskCreation creation);
}

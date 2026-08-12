package com.dianlian.platform.employee.domain;

import com.dianlian.platform.employee.api.EnterpriseAgentStatus;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record EnterpriseAgentStateEvent(
        UUID eventId,
        UUID tenantId,
        UUID enterpriseAgentId,
        long stateVersion,
        String eventType,
        EnterpriseAgentStatus fromStatus,
        EnterpriseAgentStatus toStatus,
        UUID configurationVersionId,
        String requestHash,
        String idempotencyKey,
        UUID actorId,
        Instant occurredAt
) {

    public EnterpriseAgentStateEvent {
        Objects.requireNonNull(eventId, "eventId must not be null");
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        if (stateVersion < 0) {
            throw new IllegalArgumentException("stateVersion must not be negative");
        }
        Objects.requireNonNull(eventType, "eventType must not be null");
        Objects.requireNonNull(toStatus, "toStatus must not be null");
        Objects.requireNonNull(actorId, "actorId must not be null");
        Objects.requireNonNull(occurredAt, "occurredAt must not be null");
    }
}

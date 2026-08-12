package com.dianlian.platform.billing.application;

import com.dianlian.platform.billing.api.ReservePointsCommand;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record ReservePointsRequest(
        UUID tenantId,
        UUID actorId,
        ReservePointsCommand command,
        Instant occurredAt
) {

    public ReservePointsRequest {
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(actorId, "actorId must not be null");
        Objects.requireNonNull(command, "command must not be null");
        Objects.requireNonNull(occurredAt, "occurredAt must not be null");
    }
}

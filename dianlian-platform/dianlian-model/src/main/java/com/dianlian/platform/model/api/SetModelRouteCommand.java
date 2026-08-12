package com.dianlian.platform.model.api;

import java.util.Objects;
import java.util.UUID;

public record SetModelRouteCommand(
        UUID modelDefinitionId,
        ModelCapabilityType capabilityType,
        String idempotencyKey,
        String requestHash
) {
    public SetModelRouteCommand {
        Objects.requireNonNull(modelDefinitionId, "modelDefinitionId must not be null");
        Objects.requireNonNull(capabilityType, "capabilityType must not be null");
        idempotencyKey = ModelValueChecks.text(idempotencyKey, "idempotencyKey", 200);
        requestHash = ModelValueChecks.text(requestHash, "requestHash", 128);
    }
}

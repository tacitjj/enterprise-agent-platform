package com.dianlian.platform.task.api;

import java.util.Objects;
import java.util.UUID;

public record TaskOwnership(
        UUID ownerUserId,
        UUID projectId,
        BillingScopeType billingScopeType,
        UUID billingScopeId
) {

    public TaskOwnership {
        Objects.requireNonNull(ownerUserId, "ownerUserId must not be null");
        Objects.requireNonNull(billingScopeType, "billingScopeType must not be null");
        Objects.requireNonNull(billingScopeId, "billingScopeId must not be null");
    }
}

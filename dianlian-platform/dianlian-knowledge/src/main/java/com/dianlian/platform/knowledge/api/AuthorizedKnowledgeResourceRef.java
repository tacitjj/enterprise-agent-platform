package com.dianlian.platform.knowledge.api;

import java.util.Objects;
import java.util.UUID;

/** An invocation-scoped allowlist entry; it is not a permanent access token. */
public record AuthorizedKnowledgeResourceRef(
        UUID tenantId,
        UUID resourceId,
        UUID resourceVersionId
) {
    public AuthorizedKnowledgeResourceRef {
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(resourceId, "resourceId must not be null");
        Objects.requireNonNull(resourceVersionId, "resourceVersionId must not be null");
    }
}

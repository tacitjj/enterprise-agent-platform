package com.dianlian.platform.interaction.application;

import com.dianlian.platform.context.api.ContextAuthorityPort;
import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record InvocationContextAuthoritySnapshot(
        UUID contextSnapshotId,
        ContextAuthorityPort.InvocationBoundary invocationBoundary,
        String authorizationSnapshotHash,
        String contextHash,
        List<ContextAuthorityPort.EvidenceIdentity> evidence,
        Instant fencedAt
) {
    public InvocationContextAuthoritySnapshot {
        Objects.requireNonNull(contextSnapshotId, "contextSnapshotId must not be null");
        Objects.requireNonNull(invocationBoundary, "invocationBoundary must not be null");
        authorizationSnapshotHash = requireHash(authorizationSnapshotHash, "authorizationSnapshotHash");
        contextHash = requireHash(contextHash, "contextHash");
        evidence = List.copyOf(Objects.requireNonNull(evidence, "evidence must not be null"));
        Objects.requireNonNull(fencedAt, "fencedAt must not be null");
    }

    private static String requireHash(String value, String field) {
        Objects.requireNonNull(value, field + " must not be null");
        if (!value.matches("^[0-9a-f]{64}$")) {
            throw new IllegalArgumentException(field + " must be lowercase SHA-256");
        }
        return value;
    }
}

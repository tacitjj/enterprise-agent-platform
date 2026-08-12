package com.dianlian.platform.identity.application;

import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.ClientType;
import com.dianlian.platform.identity.api.TenantId;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

public interface DeviceSessionStore {

    void create(CreateSession session);

    Optional<RefreshSession> lockRefreshToken(String tokenDigest, Instant observedAt);

    boolean rotateRefreshToken(UUID tokenId, RotateRefreshToken replacement, Instant observedAt);

    void revoke(UUID sessionId, Instant observedAt);

    record CreateSession(
            UUID sessionId,
            ActorId actorId,
            TenantId activeTenantId,
            UUID activeMemberId,
            ClientType clientType,
            String deviceId,
            String deviceName,
            Instant issuedAt,
            Instant sessionExpiresAt,
            UUID refreshTokenId,
            String refreshTokenDigest,
            Instant refreshExpiresAt
    ) {
    }

    record RefreshSession(
            UUID tokenId,
            UUID sessionId,
            ActorId actorId,
            ClientType clientType,
            Instant sessionExpiresAt,
            Instant tokenExpiresAt,
            boolean consumed,
            boolean revoked
    ) {
        boolean isUsableAt(Instant observedAt) {
            return !consumed && !revoked
                    && sessionExpiresAt.isAfter(observedAt)
                    && tokenExpiresAt.isAfter(observedAt);
        }
    }

    record RotateRefreshToken(
            UUID tokenId,
            UUID sessionId,
            String tokenDigest,
            Instant issuedAt,
            Instant expiresAt
    ) {
    }
}

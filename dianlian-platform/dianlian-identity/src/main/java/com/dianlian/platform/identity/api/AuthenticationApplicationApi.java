package com.dianlian.platform.identity.api;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public interface AuthenticationApplicationApi {

    LoginSession login(PasswordLoginCommand command);

    LoginSession refresh(RefreshSessionCommand command);

    void logout(UUID sessionId, Instant observedAt);

    record PasswordLoginCommand(
            String username,
            String password,
            ClientType clientType,
            String deviceId,
            String deviceName,
            Instant observedAt
    ) {
        public PasswordLoginCommand {
            username = requireText(username, "username", 200);
            password = requireText(password, "password", 200);
            Objects.requireNonNull(clientType, "clientType must not be null");
            deviceId = optionalText(deviceId, "deviceId", 128);
            deviceName = optionalText(deviceName, "deviceName", 100);
            Objects.requireNonNull(observedAt, "observedAt must not be null");
        }
    }

    record RefreshSessionCommand(String refreshToken, Instant observedAt) {
        public RefreshSessionCommand {
            refreshToken = requireText(refreshToken, "refreshToken", 1024);
            Objects.requireNonNull(observedAt, "observedAt must not be null");
        }
    }

    record LoginSession(
            UUID sessionId,
            ActorId actorId,
            ClientType clientType,
            String refreshToken,
            Instant accessExpiresAt,
            Instant refreshExpiresAt
    ) {
        public LoginSession {
            Objects.requireNonNull(sessionId, "sessionId must not be null");
            Objects.requireNonNull(actorId, "actorId must not be null");
            Objects.requireNonNull(clientType, "clientType must not be null");
            refreshToken = requireText(refreshToken, "refreshToken", 1024);
            Objects.requireNonNull(accessExpiresAt, "accessExpiresAt must not be null");
            Objects.requireNonNull(refreshExpiresAt, "refreshExpiresAt must not be null");
            if (!refreshExpiresAt.isAfter(accessExpiresAt)) {
                throw new IllegalArgumentException("refreshExpiresAt must be after accessExpiresAt");
            }
        }
    }

    private static String requireText(String value, String field, int maxLength) {
        Objects.requireNonNull(value, field + " must not be null");
        var normalized = value.trim();
        if (normalized.isEmpty() || normalized.length() > maxLength) {
            throw new IllegalArgumentException(field + " is invalid");
        }
        return normalized;
    }

    private static String optionalText(String value, String field, int maxLength) {
        if (value == null) return null;
        var normalized = value.trim();
        if (normalized.isEmpty()) return null;
        if (normalized.length() > maxLength) throw new IllegalArgumentException(field + " is invalid");
        return normalized;
    }
}

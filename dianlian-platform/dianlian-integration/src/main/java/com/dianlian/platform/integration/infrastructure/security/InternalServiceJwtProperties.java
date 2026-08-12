package com.dianlian.platform.integration.infrastructure.security;

import java.util.regex.Pattern;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

@ConfigurationProperties(prefix = "dianlian.internal-service-jwt")
public record InternalServiceJwtProperties(
        boolean enabled,
        String keyId,
        String privateKeyPath,
        @DefaultValue("30") long ttlSeconds
) {

    static final long MAX_TTL_SECONDS = 60;
    private static final Pattern KEY_ID_PATTERN = Pattern.compile("[A-Za-z0-9._-]{1,64}");

    public InternalServiceJwtProperties {
        if (ttlSeconds < 1 || ttlSeconds > MAX_TTL_SECONDS) {
            throw new IllegalArgumentException("internal service JWT ttlSeconds must be between 1 and 60");
        }
        if (enabled) {
            if (keyId == null || !KEY_ID_PATTERN.matcher(keyId).matches()) {
                throw new IllegalArgumentException("internal service JWT keyId is required and invalid");
            }
            if (privateKeyPath == null || privateKeyPath.isBlank()) {
                throw new IllegalArgumentException("internal service JWT privateKeyPath is required");
            }
        }
    }

    @Override
    public String toString() {
        return "InternalServiceJwtProperties[enabled=" + enabled
                + ", keyId=" + keyId
                + ", privateKeyPath=<redacted>"
                + ", ttlSeconds=" + ttlSeconds + "]";
    }
}

package com.dianlian.platform.identity.infrastructure;

import com.dianlian.platform.identity.application.AuthenticationLifetimePolicy;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public final class ConfiguredAuthenticationLifetimePolicy implements AuthenticationLifetimePolicy {

    private final Duration accessTokenLifetime;
    private final Duration refreshTokenLifetime;

    public ConfiguredAuthenticationLifetimePolicy(
            @Value("${dianlian.authentication.access-token-seconds:900}") long accessTokenSeconds,
            @Value("${dianlian.authentication.refresh-token-seconds:2592000}") long refreshTokenSeconds
    ) {
        if (accessTokenSeconds <= 0 || accessTokenSeconds > 3600) {
            throw new IllegalArgumentException("Access token lifetime must be between 1 and 3600 seconds");
        }
        if (refreshTokenSeconds <= accessTokenSeconds) {
            throw new IllegalArgumentException("Refresh token lifetime must exceed access token lifetime");
        }
        this.accessTokenLifetime = Duration.ofSeconds(accessTokenSeconds);
        this.refreshTokenLifetime = Duration.ofSeconds(refreshTokenSeconds);
    }

    @Override
    public Duration accessTokenLifetime() {
        return accessTokenLifetime;
    }

    @Override
    public Duration refreshTokenLifetime() {
        return refreshTokenLifetime;
    }
}

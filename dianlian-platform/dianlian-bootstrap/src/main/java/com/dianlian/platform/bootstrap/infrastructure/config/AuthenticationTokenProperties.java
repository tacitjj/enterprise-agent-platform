package com.dianlian.platform.bootstrap.infrastructure.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "dianlian.authentication")
public record AuthenticationTokenProperties(
        String refreshCookieName,
        boolean refreshCookieSecure,
        String refreshCookieSameSite
) {
    public AuthenticationTokenProperties {
        if (refreshCookieName == null || refreshCookieName.isBlank()) {
            throw new IllegalArgumentException("refreshCookieName must not be blank");
        }
        if (!"Strict".equals(refreshCookieSameSite) && !"Lax".equals(refreshCookieSameSite)) {
            throw new IllegalArgumentException("refreshCookieSameSite must be Strict or Lax");
        }
    }
}

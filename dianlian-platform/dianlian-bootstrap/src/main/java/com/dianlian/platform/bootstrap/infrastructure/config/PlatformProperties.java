package com.dianlian.platform.bootstrap.infrastructure.config;

import jakarta.validation.constraints.NotNull;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties(prefix = "dianlian.platform")
public record PlatformProperties(@NotNull ProcessRole processRole) {

    public enum ProcessRole {
        API
    }
}

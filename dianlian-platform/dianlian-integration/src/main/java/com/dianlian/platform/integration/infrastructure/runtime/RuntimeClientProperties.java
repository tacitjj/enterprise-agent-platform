package com.dianlian.platform.integration.infrastructure.runtime;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "runtime")
public record RuntimeClientProperties(boolean enabled) {
}

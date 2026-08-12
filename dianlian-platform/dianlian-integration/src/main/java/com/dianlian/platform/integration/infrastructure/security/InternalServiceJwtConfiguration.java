package com.dianlian.platform.integration.infrastructure.security;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(InternalServiceJwtProperties.class)
public class InternalServiceJwtConfiguration {

    @Bean
    @ConditionalOnProperty(
            prefix = "dianlian.internal-service-jwt",
            name = "enabled",
            havingValue = "true"
    )
    InternalServiceJwtIssuer internalServiceJwtIssuer(InternalServiceJwtProperties properties) {
        return InternalServiceJwtIssuer.from(properties);
    }
}

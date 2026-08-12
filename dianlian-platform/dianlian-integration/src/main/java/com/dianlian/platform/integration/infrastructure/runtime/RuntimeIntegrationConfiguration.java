package com.dianlian.platform.integration.infrastructure.runtime;

import com.dianlian.platform.task.api.AgentRuntimePort;
import org.springframework.boot.actuate.health.Health;
import org.springframework.boot.actuate.health.HealthIndicator;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(RuntimeClientProperties.class)
public class RuntimeIntegrationConfiguration {

    @Bean
    @ConditionalOnMissingBean(AgentRuntimePort.class)
    AgentRuntimePort agentRuntimePort(RuntimeClientProperties properties) {
        if (properties.enabled()) {
            throw new IllegalStateException(
                    "runtime.enabled=true requires a production AgentRuntimePort adapter"
            );
        }
        return new DisabledAgentRuntimePort();
    }

    @Bean(name = "pythonRuntimeHealthIndicator")
    HealthIndicator pythonRuntimeHealthIndicator(RuntimeClientProperties properties) {
        return () -> properties.enabled()
                ? Health.outOfService()
                        .withDetail("enabled", true)
                        .withDetail("reason", "No production runtime health probe is configured")
                        .build()
                : Health.unknown()
                        .withDetail("enabled", false)
                        .withDetail("reason", "Python Agent Runtime is disabled")
                        .build();
    }
}

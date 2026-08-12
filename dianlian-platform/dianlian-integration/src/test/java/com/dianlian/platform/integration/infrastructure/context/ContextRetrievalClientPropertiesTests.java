package com.dianlian.platform.integration.infrastructure.context;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalPort;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.URI;
import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

class ContextRetrievalClientPropertiesTests {

    @Test
    void disabledConfigurationDoesNotRequireABaseUrl() {
        var properties = new ContextRetrievalClientProperties(
                false,
                null,
                Duration.ofSeconds(2),
                Duration.ofSeconds(15),
                false
        );

        assertThat(properties.enabled()).isFalse();
    }

    @Test
    void enabledConfigurationRequiresHttpsOutsideTheExplicitLocalLoopbackException() {
        assertThatThrownBy(() -> properties("http://runtime.internal:8091", false))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("HTTPS");
        assertThatThrownBy(() -> properties("http://127.0.0.1:8091", false))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("HTTPS");

        assertThat(properties("https://runtime.internal", false).enabled()).isTrue();
        assertThat(properties("http://127.0.0.1:8091", true).enabled()).isTrue();
    }

    @Test
    void baseUrlRejectsCredentialsPathsAndNonHttpSchemes() {
        assertThatThrownBy(() -> properties("https://user@runtime.internal", false))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("credentials");
        assertThatThrownBy(() -> properties("https://runtime.internal/internal", false))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("path");
        assertThatThrownBy(() -> properties("file://runtime.internal", false))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("HTTPS");
    }

    @Test
    void disabledClientCreatesNoRetrievalPort() {
        new ApplicationContextRunner()
                .withUserConfiguration(ContextRetrievalClientConfiguration.class, TestDependencies.class)
                .withPropertyValues("dianlian.context-retrieval-client.enabled=false")
                .run(context -> {
                    assertThat(context).hasNotFailed();
                    assertThat(context).doesNotHaveBean(AuthorizedContextRetrievalPort.class);
                });
    }

    @Test
    void enabledClientFailsStartupWhenTheServiceJwtIssuerIsAbsent() {
        new ApplicationContextRunner()
                .withUserConfiguration(ContextRetrievalClientConfiguration.class, TestDependencies.class)
                .withPropertyValues(
                        "dianlian.context-retrieval-client.enabled=true",
                        "dianlian.context-retrieval-client.base-url=https://runtime.internal",
                        "dianlian.context-retrieval-client.connect-timeout=2s",
                        "dianlian.context-retrieval-client.read-timeout=15s"
                )
                .run(context -> {
                    assertThat(context).hasFailed();
                    assertThat(context.getStartupFailure())
                            .rootCause()
                            .isInstanceOf(IllegalStateException.class)
                            .hasMessageContaining("requires an InternalServiceJwtIssuer");
                });
    }

    private static ContextRetrievalClientProperties properties(String baseUrl, boolean allowLoopbackHttp) {
        return new ContextRetrievalClientProperties(
                true,
                URI.create(baseUrl),
                Duration.ofSeconds(2),
                Duration.ofSeconds(15),
                allowLoopbackHttp
        );
    }

    @Configuration(proxyBeanMethods = false)
    static class TestDependencies {

        @Bean
        ObjectMapper objectMapper() {
            return new ObjectMapper();
        }
    }
}

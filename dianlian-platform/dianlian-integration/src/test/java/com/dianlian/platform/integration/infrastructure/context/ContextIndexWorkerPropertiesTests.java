package com.dianlian.platform.integration.infrastructure.context;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.context.api.ContextIndexDispatch;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.lang.reflect.Proxy;
import java.net.URI;
import java.time.Duration;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

class ContextIndexWorkerPropertiesTests {

    @Test
    void disabledConfigurationDoesNotRequireABaseUrl() {
        var properties = new ContextIndexWorkerProperties(
                false,
                null,
                Duration.ofSeconds(2),
                Duration.ofSeconds(20),
                Duration.ofSeconds(60),
                1000,
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
    void leaseMustOutliveTheBoundedHttpCallAndCompletionMargin() {
        assertThatThrownBy(() -> new ContextIndexWorkerProperties(
                true,
                URI.create("https://runtime.internal"),
                Duration.ofSeconds(2),
                Duration.ofSeconds(20),
                Duration.ofSeconds(25),
                1000,
                false
        )).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("leaseDuration");
    }

    @Test
    void disabledWorkerCreatesNoRuntimeClientOrPoller() {
        new ApplicationContextRunner()
                .withUserConfiguration(ContextIndexWorkerConfiguration.class, TestDependencies.class)
                .withPropertyValues("dianlian.context-index-worker.enabled=false")
                .run(context -> {
                    assertThat(context).hasNotFailed();
                    assertThat(context).doesNotHaveBean(ContextIndexingRuntimeClient.class);
                    assertThat(context).doesNotHaveBean(ContextIndexWorker.class);
                });
    }

    @Test
    void enabledWorkerFailsStartupWhenTheServiceJwtIssuerIsAbsent() {
        new ApplicationContextRunner()
                .withUserConfiguration(ContextIndexWorkerConfiguration.class, TestDependencies.class)
                .withPropertyValues(
                        "dianlian.context-index-worker.enabled=true",
                        "dianlian.context-index-worker.base-url=https://runtime.internal",
                        "dianlian.context-index-worker.connect-timeout=2s",
                        "dianlian.context-index-worker.read-timeout=20s",
                        "dianlian.context-index-worker.lease-duration=60s"
                )
                .run(context -> {
                    assertThat(context).hasFailed();
                    assertThat(context.getStartupFailure())
                            .rootCause()
                            .isInstanceOf(IllegalStateException.class)
                            .hasMessageContaining("requires an InternalServiceJwtIssuer");
                });
    }

    private static ContextIndexWorkerProperties properties(String baseUrl, boolean allowLoopbackHttp) {
        return new ContextIndexWorkerProperties(
                true,
                URI.create(baseUrl),
                Duration.ofSeconds(2),
                Duration.ofSeconds(20),
                Duration.ofSeconds(60),
                1000,
                allowLoopbackHttp
        );
    }

    @Configuration(proxyBeanMethods = false)
    static class TestDependencies {

        @Bean
        ContextIndexDispatch contextIndexDispatch() {
            return (ContextIndexDispatch) Proxy.newProxyInstance(
                    ContextIndexDispatch.class.getClassLoader(),
                    new Class<?>[]{ContextIndexDispatch.class},
                    (proxy, method, arguments) -> {
                        throw new UnsupportedOperationException("test dependency must not be invoked");
                    }
            );
        }

        @Bean
        ObjectMapper objectMapper() {
            return new ObjectMapper();
        }
    }
}

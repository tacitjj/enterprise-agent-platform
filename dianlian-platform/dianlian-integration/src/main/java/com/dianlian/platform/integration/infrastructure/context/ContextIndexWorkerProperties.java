package com.dianlian.platform.integration.infrastructure.context;

import java.net.URI;
import java.time.Duration;
import java.util.Locale;
import java.util.Set;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

@ConfigurationProperties(prefix = "dianlian.context-index-worker")
public record ContextIndexWorkerProperties(
        boolean enabled,
        URI baseUrl,
        @DefaultValue("2s") Duration connectTimeout,
        @DefaultValue("20s") Duration readTimeout,
        @DefaultValue("60s") Duration leaseDuration,
        @DefaultValue("1000") long pollDelayMs,
        @DefaultValue("false") boolean allowLoopbackHttp
) {

    private static final Set<String> LOOPBACK_HOSTS = Set.of("localhost", "127.0.0.1", "::1");
    private static final Duration MIN_TIMEOUT = Duration.ofMillis(100);
    private static final Duration MAX_CONNECT_TIMEOUT = Duration.ofSeconds(30);
    private static final Duration MAX_READ_TIMEOUT = Duration.ofMinutes(5);
    private static final Duration LEASE_COMPLETION_MARGIN = Duration.ofSeconds(5);

    public ContextIndexWorkerProperties {
        connectTimeout = requireDuration(
                connectTimeout, MIN_TIMEOUT, MAX_CONNECT_TIMEOUT, "connectTimeout");
        readTimeout = requireDuration(readTimeout, MIN_TIMEOUT, MAX_READ_TIMEOUT, "readTimeout");
        leaseDuration = requireDuration(
                leaseDuration, Duration.ofSeconds(5), Duration.ofMinutes(15), "leaseDuration");
        if (pollDelayMs < 100 || pollDelayMs > 60_000) {
            throw new IllegalArgumentException("context index worker pollDelayMs must be between 100 and 60000");
        }
        if (leaseDuration.compareTo(connectTimeout.plus(readTimeout).plus(LEASE_COMPLETION_MARGIN)) <= 0) {
            throw new IllegalArgumentException(
                    "context index worker leaseDuration must exceed HTTP timeouts and completion margin");
        }
        if (enabled) {
            validateBaseUrl(baseUrl, allowLoopbackHttp);
        }
    }

    private static Duration requireDuration(
            Duration value,
            Duration minimum,
            Duration maximum,
            String fieldName
    ) {
        if (value == null || value.compareTo(minimum) < 0 || value.compareTo(maximum) > 0) {
            throw new IllegalArgumentException("context index worker " + fieldName + " is invalid");
        }
        return value;
    }

    private static void validateBaseUrl(URI baseUrl, boolean allowLoopbackHttp) {
        if (baseUrl == null || !baseUrl.isAbsolute() || baseUrl.getHost() == null) {
            throw new IllegalArgumentException("context index worker baseUrl must be an absolute HTTP URL");
        }
        if (baseUrl.getUserInfo() != null || baseUrl.getQuery() != null || baseUrl.getFragment() != null) {
            throw new IllegalArgumentException("context index worker baseUrl must not contain credentials or metadata");
        }
        String path = baseUrl.getPath();
        if (path != null && !path.isEmpty() && !"/".equals(path)) {
            throw new IllegalArgumentException("context index worker baseUrl must not contain a path");
        }
        String scheme = baseUrl.getScheme().toLowerCase(Locale.ROOT);
        if ("https".equals(scheme)) {
            return;
        }
        String host = baseUrl.getHost().toLowerCase(Locale.ROOT);
        if (!"http".equals(scheme) || !allowLoopbackHttp || !LOOPBACK_HOSTS.contains(host)) {
            throw new IllegalArgumentException(
                    "context index worker baseUrl requires HTTPS; local profile may explicitly allow loopback HTTP");
        }
    }
}

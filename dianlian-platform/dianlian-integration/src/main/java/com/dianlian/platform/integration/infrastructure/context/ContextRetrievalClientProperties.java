package com.dianlian.platform.integration.infrastructure.context;

import java.net.URI;
import java.time.Duration;
import java.util.Locale;
import java.util.Set;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

@ConfigurationProperties(prefix = "dianlian.context-retrieval-client")
public record ContextRetrievalClientProperties(
        boolean enabled,
        URI baseUrl,
        @DefaultValue("2s") Duration connectTimeout,
        @DefaultValue("15s") Duration readTimeout,
        @DefaultValue("false") boolean allowLoopbackHttp
) {

    private static final Set<String> LOOPBACK_HOSTS = Set.of("localhost", "127.0.0.1", "::1");
    private static final Duration MIN_TIMEOUT = Duration.ofMillis(100);
    private static final Duration MAX_CONNECT_TIMEOUT = Duration.ofSeconds(30);
    private static final Duration MAX_READ_TIMEOUT = Duration.ofSeconds(60);

    public ContextRetrievalClientProperties {
        connectTimeout = requireDuration(
                connectTimeout,
                MIN_TIMEOUT,
                MAX_CONNECT_TIMEOUT,
                "connectTimeout"
        );
        readTimeout = requireDuration(readTimeout, MIN_TIMEOUT, MAX_READ_TIMEOUT, "readTimeout");
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
            throw new IllegalArgumentException("context retrieval client " + fieldName + " is invalid");
        }
        return value;
    }

    private static void validateBaseUrl(URI baseUrl, boolean allowLoopbackHttp) {
        if (baseUrl == null || !baseUrl.isAbsolute() || baseUrl.getHost() == null) {
            throw new IllegalArgumentException("context retrieval client baseUrl must be an absolute HTTP URL");
        }
        if (baseUrl.getUserInfo() != null || baseUrl.getQuery() != null || baseUrl.getFragment() != null) {
            throw new IllegalArgumentException(
                    "context retrieval client baseUrl must not contain credentials or metadata"
            );
        }
        String path = baseUrl.getPath();
        if (path != null && !path.isEmpty() && !"/".equals(path)) {
            throw new IllegalArgumentException("context retrieval client baseUrl must not contain a path");
        }
        String scheme = baseUrl.getScheme().toLowerCase(Locale.ROOT);
        if ("https".equals(scheme)) {
            return;
        }
        String host = baseUrl.getHost().toLowerCase(Locale.ROOT);
        if (!"http".equals(scheme) || !allowLoopbackHttp || !LOOPBACK_HOSTS.contains(host)) {
            throw new IllegalArgumentException(
                    "context retrieval client baseUrl requires HTTPS; local profile may explicitly allow loopback HTTP"
            );
        }
    }
}

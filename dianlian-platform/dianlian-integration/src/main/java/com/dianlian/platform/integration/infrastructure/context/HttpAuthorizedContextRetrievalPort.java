package com.dianlian.platform.integration.infrastructure.context;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextBundle;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextRetrievalRequest;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalException;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalPort;
import com.dianlian.platform.integration.infrastructure.context.ContextRetrievalHttpContract.HttpContextBundle;
import com.dianlian.platform.integration.infrastructure.security.InternalServiceJwtIssuer;
import com.dianlian.platform.integration.infrastructure.security.InternalServiceJwtScope;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.time.Clock;
import java.time.Duration;
import java.util.Objects;
import java.util.function.Supplier;

final class HttpAuthorizedContextRetrievalPort implements AuthorizedContextRetrievalPort {

    static final String SEARCH_PATH = "/internal/v1/retrieval/search";

    private final HttpClient httpClient;
    private final URI endpoint;
    private final ObjectMapper objectMapper;
    private final Supplier<String> tokenSupplier;
    private final Clock clock;
    private final Duration readTimeout;

    HttpAuthorizedContextRetrievalPort(
            HttpClient httpClient,
            URI baseUrl,
            ObjectMapper objectMapper,
            InternalServiceJwtIssuer jwtIssuer,
            Duration readTimeout
    ) {
        this(
                httpClient,
                baseUrl,
                objectMapper,
                () -> jwtIssuer.issue(InternalServiceJwtScope.CONTEXT_RETRIEVE).value(),
                Clock.systemUTC(),
                readTimeout
        );
    }

    HttpAuthorizedContextRetrievalPort(
            HttpClient httpClient,
            URI baseUrl,
            ObjectMapper objectMapper,
            Supplier<String> tokenSupplier,
            Clock clock,
            Duration readTimeout
    ) {
        this.httpClient = Objects.requireNonNull(httpClient, "httpClient must not be null");
        this.endpoint = Objects.requireNonNull(baseUrl, "baseUrl must not be null").resolve(SEARCH_PATH);
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
        this.tokenSupplier = Objects.requireNonNull(tokenSupplier, "tokenSupplier must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
        this.readTimeout = Objects.requireNonNull(readTimeout, "readTimeout must not be null");
    }

    @Override
    public ContextBundle retrieve(ContextRetrievalRequest request) {
        Objects.requireNonNull(request, "request must not be null");
        boundedTimeout(request);

        final byte[] requestBody;
        try {
            requestBody = objectMapper.writeValueAsBytes(ContextRetrievalHttpContract.request(request));
        } catch (JsonProcessingException | RuntimeException exception) {
            throw failure("CONTEXT_RETRIEVAL_REQUEST_INVALID", false);
        }

        final String token;
        try {
            token = tokenSupplier.get();
            if (token == null || token.isBlank()) {
                throw new IllegalStateException("service JWT is blank");
            }
        } catch (RuntimeException exception) {
            throw failure("CONTEXT_RETRIEVAL_SERVICE_JWT_UNAVAILABLE", true);
        }
        Duration requestTimeout = boundedTimeout(request);

        final HttpRequest httpRequest;
        try {
            httpRequest = HttpRequest.newBuilder(endpoint)
                    .timeout(requestTimeout)
                    .header("Authorization", "Bearer " + token)
                    .header("Content-Type", "application/json")
                    .header("Accept", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(requestBody))
                    .build();
        } catch (RuntimeException exception) {
            throw failure("CONTEXT_RETRIEVAL_REQUEST_INVALID", false);
        }

        final HttpResponse<byte[]> response;
        try {
            response = httpClient.send(httpRequest, HttpResponse.BodyHandlers.ofByteArray());
        } catch (HttpTimeoutException exception) {
            throw failure("CONTEXT_RETRIEVAL_RUNTIME_TIMEOUT", true);
        } catch (IOException exception) {
            throw failure("CONTEXT_RETRIEVAL_RUNTIME_IO", true);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw failure("CONTEXT_RETRIEVAL_RUNTIME_INTERRUPTED", true);
        } catch (RuntimeException exception) {
            throw failure("CONTEXT_RETRIEVAL_RUNTIME_IO", true);
        }

        int status = response.statusCode();
        if (status < 200 || status >= 300) {
            throw classifyStatus(status);
        }

        final ContextBundle bundle;
        try {
            bundle = ContextRetrievalHttpContract.response(
                    objectMapper.readValue(response.body(), HttpContextBundle.class)
            );
        } catch (IOException | RuntimeException exception) {
            throw failure("CONTEXT_RETRIEVAL_RESPONSE_INVALID", false);
        }
        if (!request.contractVersion().equals(bundle.contractVersion())
                || !request.requestId().equals(bundle.requestId())) {
            throw failure("CONTEXT_RETRIEVAL_RESPONSE_INVALID", false);
        }
        return bundle;
    }

    private Duration boundedTimeout(ContextRetrievalRequest request) {
        Duration remaining = Duration.between(clock.instant(), request.deadlineAt());
        if (remaining.isZero() || remaining.isNegative()) {
            throw failure("CONTEXT_RETRIEVAL_DEADLINE_EXCEEDED", true);
        }
        return remaining.compareTo(readTimeout) < 0 ? remaining : readTimeout;
    }

    private static AuthorizedContextRetrievalException classifyStatus(int status) {
        return switch (status) {
            case 401 -> failure("CONTEXT_RETRIEVAL_AUTHENTICATION_REJECTED", false);
            case 403 -> failure("CONTEXT_RETRIEVAL_AUTHORIZATION_REJECTED", false);
            case 408 -> failure("CONTEXT_RETRIEVAL_RUNTIME_TIMEOUT", true);
            case 422 -> failure("CONTEXT_RETRIEVAL_CONTRACT_REJECTED", false);
            case 429 -> failure("CONTEXT_RETRIEVAL_RATE_LIMITED", true);
            default -> {
                if (status >= 500 && status <= 599) {
                    yield failure("CONTEXT_RETRIEVAL_RUNTIME_UNAVAILABLE", true);
                }
                if (status >= 400 && status <= 499) {
                    yield failure("CONTEXT_RETRIEVAL_CLIENT_REJECTED", false);
                }
                yield failure("CONTEXT_RETRIEVAL_UNEXPECTED_STATUS", false);
            }
        };
    }

    private static AuthorizedContextRetrievalException failure(String code, boolean retryable) {
        return new AuthorizedContextRetrievalException(code, retryable);
    }
}

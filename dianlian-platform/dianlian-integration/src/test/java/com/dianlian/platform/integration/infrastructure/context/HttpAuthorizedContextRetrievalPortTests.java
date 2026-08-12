package com.dianlian.platform.integration.infrastructure.context;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextRetrievalRequest;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextSourceState;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.net.Authenticator;
import java.net.CookieHandler;
import java.net.ProxySelector;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpHeaders;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayDeque;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.concurrent.Flow;
import java.util.concurrent.atomic.AtomicInteger;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.SSLSession;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

class HttpAuthorizedContextRetrievalPortTests {

    private static final Instant NOW = Instant.parse("2098-01-01T00:00:00Z");
    private static final URI BASE_URL = URI.create("https://runtime.internal");

    private final ObjectMapper objectMapper = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
            .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);

    @Test
    void sendsTheExplicitCamelCaseContractAndMapsTheCompleteResponse() throws Exception {
        var fixture = fixture(responseFixture());

        var bundle = fixture.client.retrieve(requestFixture());

        assertThat(fixture.tokenIssueCount).hasValue(1);
        assertThat(fixture.httpClient.lastRequest().uri())
                .isEqualTo(URI.create("https://runtime.internal/internal/v1/retrieval/search"));
        assertThat(fixture.httpClient.lastRequest().headers().firstValue("Authorization"))
                .contains("Bearer signed-retrieve-token");
        var sent = objectMapper.readTree(publishedBody(fixture.httpClient.lastRequest()));
        assertThat(sent.path("requestId").asText()).isEqualTo(requestFixture().requestId().toString());
        assertThat(sent.path("authorizedKnowledgeResources").get(0).path("resourceVersionId").asText())
                .isEqualTo("00000000-0000-0000-0000-000000000402");
        assertThat(sent.path("allowedMemoryScopes").get(1).path("scopeType").asText())
                .isEqualTo("USER_AGENT");
        assertThat(sent.path("authorizationSnapshotHash").asText()).hasSize(64);

        assertThat(bundle.requestId()).isEqualTo(requestFixture().requestId());
        assertThat(bundle.retrievalSnapshotId()).isEqualTo("retrieval-snapshot-0001");
        assertThat(bundle.generatedAt()).isEqualTo(Instant.parse("2026-08-12T08:00:00Z"));
        assertThat(bundle.knowledge().state()).isEqualTo(ContextSourceState.READY);
        assertThat(bundle.knowledge().evidence()).singleElement().satisfies(evidence -> {
            assertThat(evidence.evidenceId()).isEqualTo("knowledge-evidence-0001");
            assertThat(evidence.sourceType()).isEqualTo(RequestedSource.KNOWLEDGE);
            assertThat(evidence.sourceVersion()).isEqualTo("00000000-0000-0000-0000-000000000402");
            assertThat(evidence.contentHash()).hasSize(64);
            assertThat(evidence.score()).isEqualTo(0.91);
            assertThat(evidence.citation()).isEqualTo("测试知识文档 / chunk-0001");
        });
        assertThat(bundle.memory().state()).isEqualTo(ContextSourceState.EMPTY);
        assertThat(bundle.memory().reasonCode()).isEqualTo("MEMORY_NO_CONFIRMED_EVIDENCE");
        assertThat(bundle.retrievalTrace().strategies()).containsExactly("LEXICAL", "VECTOR", "RERANK");
        assertThat(bundle.retrievalTrace().candidateCount()).isEqualTo(24);
        assertThat(bundle.retrievalTrace().rerankedCount()).isEqualTo(8);
        assertThat(bundle.retrievalTrace().indexVersion()).isEqualTo("index-v1");
        assertThat(bundle.retrievalTrace().elapsedMs()).isEqualTo(38);
    }

    @Test
    void clampsTheHttpTimeoutToTheRequestDeadline() throws Exception {
        var fixture = fixture(responseFixture());
        var request = withDeadline(requestFixture(), NOW.plusMillis(250));

        fixture.client.retrieve(request);

        assertThat(fixture.httpClient.lastRequest().timeout()).contains(Duration.ofMillis(250));
    }

    @Test
    void rejectsExpiredRequestsBeforeIssuingATokenOrCallingTheRuntime() throws Exception {
        var fixture = fixture(responseFixture());
        var request = withDeadline(requestFixture(), NOW);

        assertFailure(
                () -> fixture.client.retrieve(request),
                "CONTEXT_RETRIEVAL_DEADLINE_EXCEEDED",
                true
        );
        assertThat(fixture.tokenIssueCount).hasValue(0);
        assertThat(fixture.httpClient.callCount()).isZero();
    }

    @Test
    void rejectsUnknownResponseFieldsAndMismatchedEchoFields() throws Exception {
        var unknown = (ObjectNode) objectMapper.readTree(responseFixture());
        unknown.put("unexpected", "must be rejected");
        var unknownFixture = fixture(objectMapper.writeValueAsBytes(unknown));
        assertFailure(
                () -> unknownFixture.client.retrieve(requestFixture()),
                "CONTEXT_RETRIEVAL_RESPONSE_INVALID",
                false
        );

        var mismatched = (ObjectNode) objectMapper.readTree(responseFixture());
        mismatched.put("requestId", "00000000-0000-0000-0000-000000000999");
        var mismatchFixture = fixture(objectMapper.writeValueAsBytes(mismatched));
        assertFailure(
                () -> mismatchFixture.client.retrieve(requestFixture()),
                "CONTEXT_RETRIEVAL_RESPONSE_INVALID",
                false
        );

        var version = (ObjectNode) objectMapper.readTree(responseFixture());
        version.put("contractVersion", "1.1");
        var versionFixture = fixture(objectMapper.writeValueAsBytes(version));
        assertFailure(
                () -> versionFixture.client.retrieve(requestFixture()),
                "CONTEXT_RETRIEVAL_RESPONSE_INVALID",
                false
        );
    }

    @ParameterizedTest
    @CsvSource({
            "401, CONTEXT_RETRIEVAL_AUTHENTICATION_REJECTED, false",
            "403, CONTEXT_RETRIEVAL_AUTHORIZATION_REJECTED, false",
            "409, CONTEXT_RETRIEVAL_CLIENT_REJECTED, false",
            "422, CONTEXT_RETRIEVAL_CONTRACT_REJECTED, false",
            "408, CONTEXT_RETRIEVAL_RUNTIME_TIMEOUT, true",
            "429, CONTEXT_RETRIEVAL_RATE_LIMITED, true",
            "500, CONTEXT_RETRIEVAL_RUNTIME_UNAVAILABLE, true",
            "503, CONTEXT_RETRIEVAL_RUNTIME_UNAVAILABLE, true"
    })
    void classifiesHttpFailuresWithoutExposingRemoteData(
            int status,
            String expectedCode,
            boolean retryable
    ) throws Exception {
        var httpClient = new StubHttpClient();
        httpClient.respond(status, "secret remote response".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        var fixture = fixture(httpClient);

        assertThatThrownBy(() -> fixture.client.retrieve(requestFixture()))
                .isInstanceOfSatisfying(AuthorizedContextRetrievalException.class, failure -> {
                    assertThat(failure.code()).isEqualTo(expectedCode);
                    assertThat(failure.retryable()).isEqualTo(retryable);
                    assertThat(failure.getMessage())
                            .doesNotContain("secret remote response")
                            .doesNotContain("runtime.internal")
                            .doesNotContain("signed-retrieve-token");
                    assertThat(failure.getCause()).isNull();
                });
    }

    @Test
    void classifiesTimeoutIoAndTokenFailuresAsRetryableAndRedacted() throws Exception {
        var timeoutClient = new StubHttpClient();
        timeoutClient.fail(new HttpTimeoutException("secret timeout details"));
        var timeoutFixture = fixture(timeoutClient);
        assertFailure(
                () -> timeoutFixture.client.retrieve(requestFixture()),
                "CONTEXT_RETRIEVAL_RUNTIME_TIMEOUT",
                true
        );

        var ioClient = new StubHttpClient();
        ioClient.fail(new IOException("secret transport details"));
        var ioFixture = fixture(ioClient);
        assertThatThrownBy(() -> ioFixture.client.retrieve(requestFixture()))
                .isInstanceOfSatisfying(AuthorizedContextRetrievalException.class, failure -> {
                    assertThat(failure.code()).isEqualTo("CONTEXT_RETRIEVAL_RUNTIME_IO");
                    assertThat(failure.retryable()).isTrue();
                    assertThat(failure.getMessage()).doesNotContain("secret transport details");
                    assertThat(failure.getCause()).isNull();
                });

        var jwtClient = new StubHttpClient();
        var jwtFailure = new HttpAuthorizedContextRetrievalPort(
                jwtClient,
                BASE_URL,
                objectMapper,
                () -> {
                    throw new IllegalStateException("secret signing details");
                },
                Clock.fixed(NOW, ZoneOffset.UTC),
                Duration.ofSeconds(5)
        );
        assertThatThrownBy(() -> jwtFailure.retrieve(requestFixture()))
                .isInstanceOfSatisfying(AuthorizedContextRetrievalException.class, failure -> {
                    assertThat(failure.code()).isEqualTo("CONTEXT_RETRIEVAL_SERVICE_JWT_UNAVAILABLE");
                    assertThat(failure.retryable()).isTrue();
                    assertThat(failure.getMessage()).doesNotContain("secret signing details");
                });
        assertThat(jwtClient.callCount()).isZero();
    }

    private ClientFixture fixture(byte[] responseBody) {
        var httpClient = new StubHttpClient();
        httpClient.respond(200, responseBody);
        return fixture(httpClient);
    }

    private ClientFixture fixture(StubHttpClient httpClient) {
        var tokenIssueCount = new AtomicInteger();
        return new ClientFixture(
                new HttpAuthorizedContextRetrievalPort(
                        httpClient,
                        BASE_URL,
                        objectMapper,
                        () -> {
                            tokenIssueCount.incrementAndGet();
                            return "signed-retrieve-token";
                        },
                        Clock.fixed(NOW, ZoneOffset.UTC),
                        Duration.ofSeconds(5)
                ),
                httpClient,
                tokenIssueCount
        );
    }

    private ContextRetrievalRequest requestFixture() throws IOException {
        return objectMapper.readValue(requestFixturePath().toFile(), ContextRetrievalRequest.class);
    }

    private static ContextRetrievalRequest withDeadline(ContextRetrievalRequest request, Instant deadlineAt) {
        return new ContextRetrievalRequest(
                request.contractVersion(),
                request.requestId(),
                request.traceId(),
                deadlineAt,
                request.tenantId(),
                request.actorUserId(),
                request.enterpriseAgentId(),
                request.conversationId(),
                request.query(),
                request.audienceUserIds(),
                request.authorizedKnowledgeResources(),
                request.allowedMemoryScopes(),
                request.requestedSources(),
                request.policy(),
                request.authorizationSnapshotHash()
        );
    }

    private static byte[] responseFixture() throws IOException {
        return Files.readAllBytes(fixturePath("context-retrieval-v1-response.json"));
    }

    private static Path requestFixturePath() {
        return fixturePath("context-retrieval-v1-request.json");
    }

    private static Path fixturePath(String fileName) {
        Path cursor = Path.of("").toAbsolutePath();
        while (cursor != null) {
            Path candidate = cursor.resolve("contracts/fixtures/context").resolve(fileName);
            if (Files.isRegularFile(candidate)) {
                return candidate;
            }
            cursor = cursor.getParent();
        }
        throw new IllegalStateException("shared context fixture not found: " + fileName);
    }

    private static byte[] publishedBody(HttpRequest request) {
        var output = new ByteArrayOutputStream();
        var completed = new CompletableFuture<Void>();
        request.bodyPublisher().orElseThrow().subscribe(new Flow.Subscriber<>() {
            @Override
            public void onSubscribe(Flow.Subscription subscription) {
                subscription.request(Long.MAX_VALUE);
            }

            @Override
            public void onNext(ByteBuffer item) {
                byte[] bytes = new byte[item.remaining()];
                item.get(bytes);
                output.writeBytes(bytes);
            }

            @Override
            public void onError(Throwable throwable) {
                completed.completeExceptionally(throwable);
            }

            @Override
            public void onComplete() {
                completed.complete(null);
            }
        });
        completed.join();
        return output.toByteArray();
    }

    private static void assertFailure(
            ThrowingCall invocation,
            String expectedCode,
            boolean expectedRetryable
    ) {
        assertThatThrownBy(invocation::invoke)
                .isInstanceOfSatisfying(AuthorizedContextRetrievalException.class, failure -> {
                    assertThat(failure.code()).isEqualTo(expectedCode);
                    assertThat(failure.retryable()).isEqualTo(expectedRetryable);
                });
    }

    private record ClientFixture(
            HttpAuthorizedContextRetrievalPort client,
            StubHttpClient httpClient,
            AtomicInteger tokenIssueCount
    ) {
    }

    @FunctionalInterface
    private interface ThrowingCall {

        void invoke() throws Exception;
    }

    private static final class StubHttpClient extends HttpClient {

        private final ArrayDeque<Object> outcomes = new ArrayDeque<>();
        private HttpRequest lastRequest;
        private int callCount;

        void respond(int status, byte[] body) {
            outcomes.addLast(new StubOutcome(status, body));
        }

        void fail(IOException failure) {
            outcomes.addLast(failure);
        }

        HttpRequest lastRequest() {
            return lastRequest;
        }

        int callCount() {
            return callCount;
        }

        @Override
        public Optional<CookieHandler> cookieHandler() {
            return Optional.empty();
        }

        @Override
        public Optional<Duration> connectTimeout() {
            return Optional.of(Duration.ofSeconds(1));
        }

        @Override
        public Redirect followRedirects() {
            return Redirect.NEVER;
        }

        @Override
        public Optional<ProxySelector> proxy() {
            return Optional.empty();
        }

        @Override
        public SSLContext sslContext() {
            try {
                return SSLContext.getDefault();
            } catch (NoSuchAlgorithmException exception) {
                throw new IllegalStateException(exception);
            }
        }

        @Override
        public SSLParameters sslParameters() {
            return new SSLParameters();
        }

        @Override
        public Optional<Authenticator> authenticator() {
            return Optional.empty();
        }

        @Override
        public Version version() {
            return Version.HTTP_1_1;
        }

        @Override
        public Optional<Executor> executor() {
            return Optional.empty();
        }

        @Override
        @SuppressWarnings("unchecked")
        public <T> HttpResponse<T> send(
                HttpRequest request,
                HttpResponse.BodyHandler<T> responseBodyHandler
        ) throws IOException {
            lastRequest = request;
            callCount++;
            Object outcome = outcomes.removeFirst();
            if (outcome instanceof IOException failure) {
                throw failure;
            }
            var response = (StubOutcome) outcome;
            return new StubHttpResponse<>(response.status(), (T) response.body(), request);
        }

        @Override
        public <T> CompletableFuture<HttpResponse<T>> sendAsync(
                HttpRequest request,
                HttpResponse.BodyHandler<T> responseBodyHandler
        ) {
            throw new UnsupportedOperationException("synchronous client only");
        }

        @Override
        public <T> CompletableFuture<HttpResponse<T>> sendAsync(
                HttpRequest request,
                HttpResponse.BodyHandler<T> responseBodyHandler,
                HttpResponse.PushPromiseHandler<T> pushPromiseHandler
        ) {
            throw new UnsupportedOperationException("synchronous client only");
        }
    }

    private record StubOutcome(int status, byte[] body) {
    }

    private record StubHttpResponse<T>(
            int statusCode,
            T body,
            HttpRequest request
    ) implements HttpResponse<T> {

        @Override
        public Optional<HttpResponse<T>> previousResponse() {
            return Optional.empty();
        }

        @Override
        public HttpHeaders headers() {
            return HttpHeaders.of(Map.of("content-type", List.of("application/json")), (name, value) -> true);
        }

        @Override
        public Optional<SSLSession> sslSession() {
            return Optional.empty();
        }

        @Override
        public URI uri() {
            return request.uri();
        }

        @Override
        public HttpClient.Version version() {
            return HttpClient.Version.HTTP_1_1;
        }
    }
}

package com.dianlian.platform.integration.infrastructure.context;

import static com.dianlian.platform.integration.infrastructure.context.ContextIndexingTestFixtures.REQUEST_ID;
import static com.dianlian.platform.integration.infrastructure.context.ContextIndexingTestFixtures.TRACE_ID;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withForbiddenRequest;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withException;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withRequestConflict;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServiceUnavailable;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withTooManyRequests;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withUnauthorizedRequest;

import com.dianlian.platform.context.api.ContextIndexDispatch.ReceiptOutcome;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

class HttpContextIndexingRuntimeClientTests {

    @Test
    void sendsOnlyTheIndexWriteServiceTokenAndAcceptsAStrictMatchingReceipt() throws Exception {
        var fixture = fixture();
        fixture.server.expect(requestTo("https://runtime.internal/internal/v1/indexing/apply"))
                .andExpect(header(HttpHeaders.AUTHORIZATION, "Bearer signed-service-token"))
                .andExpect(jsonPath("$.resourceId").value(ContextIndexingTestFixtures.DOCUMENT_VERSION_ID.toString()))
                .andExpect(jsonPath("$.sourceId").value(ContextIndexingTestFixtures.DOCUMENT_ID.toString()))
                .andRespond(withSuccess(receiptJson("APPLIED", ContextIndexingTestFixtures.EVENT_SEQUENCE),
                        MediaType.APPLICATION_JSON));

        var receipt = fixture.client.apply(ContextIndexingTestFixtures.knowledgeProjection());

        assertThat(receipt.outcome()).isEqualTo(ReceiptOutcome.APPLIED);
        assertThat(fixture.tokenIssueCount).hasValue(1);
        fixture.server.verify();
    }

    @Test
    void rejectsAReceiptWhoseFenceFieldsDoNotMatch() throws Exception {
        var mismatches = List.<Map<String, Object>>of(
                Map.of("contractVersion", "1.1"),
                Map.of("requestId", ContextIndexingTestFixtures.SCOPE_ID),
                Map.of("jobId", ContextIndexingTestFixtures.MEMORY_ID),
                Map.of("leaseEpoch", ContextIndexingTestFixtures.LEASE_EPOCH + 1),
                Map.of("target", "VECTOR"),
                Map.of("operation", "DELETE"),
                Map.of("eventSequence", ContextIndexingTestFixtures.EVENT_SEQUENCE + 1),
                Map.of("indexProfile", "context-profile-v2")
        );
        for (var mismatch : mismatches) {
            var fixture = fixture();
            fixture.server.expect(requestTo("https://runtime.internal/internal/v1/indexing/apply"))
                    .andRespond(withSuccess(receiptJson("APPLIED", mismatch), MediaType.APPLICATION_JSON));

            assertThatThrownBy(() -> fixture.client.apply(ContextIndexingTestFixtures.knowledgeProjection()))
                    .isInstanceOfSatisfying(ContextIndexingRuntimeException.class, failure -> {
                        assertThat(failure.code()).isEqualTo("CONTEXT_INDEX_RECEIPT_INVALID");
                        assertThat(failure.retryable()).isFalse();
                    });
            fixture.server.verify();
        }
    }

    @Test
    void classifiesAuthorizationAsPermanentAndServiceUnavailableAsRetryable() throws Exception {
        var forbidden = fixture();
        forbidden.server.expect(requestTo("https://runtime.internal/internal/v1/indexing/apply"))
                .andRespond(withForbiddenRequest());
        assertThatThrownBy(() -> forbidden.client.apply(ContextIndexingTestFixtures.deleteProjection()))
                .isInstanceOfSatisfying(ContextIndexingRuntimeException.class, failure -> {
                    assertThat(failure.code()).isEqualTo("CONTEXT_INDEX_AUTHORIZATION_REJECTED");
                    assertThat(failure.retryable()).isFalse();
                });
        forbidden.server.verify();

        var unavailable = fixture();
        unavailable.server.expect(requestTo("https://runtime.internal/internal/v1/indexing/apply"))
                .andRespond(withServiceUnavailable());
        assertThatThrownBy(() -> unavailable.client.apply(ContextIndexingTestFixtures.deleteProjection()))
                .isInstanceOfSatisfying(ContextIndexingRuntimeException.class, failure -> {
                    assertThat(failure.code()).isEqualTo("CONTEXT_INDEX_RUNTIME_UNAVAILABLE");
                    assertThat(failure.retryable()).isTrue();
                });
        unavailable.server.verify();
    }

    @Test
    void classifiesAuthenticationAndConflictAsPermanent() throws Exception {
        var unauthorized = fixture();
        unauthorized.server.expect(requestTo("https://runtime.internal/internal/v1/indexing/apply"))
                .andRespond(withUnauthorizedRequest());
        assertFailure(
                unauthorized,
                "CONTEXT_INDEX_AUTHENTICATION_REJECTED",
                false
        );

        var conflict = fixture();
        conflict.server.expect(requestTo("https://runtime.internal/internal/v1/indexing/apply"))
                .andRespond(withRequestConflict());
        assertFailure(conflict, "CONTEXT_INDEX_CONFLICT", false);
    }

    @Test
    void classifiesRateLimitAndIoFailureAsRetryableWithoutExposingTheCause() throws Exception {
        var rateLimited = fixture();
        rateLimited.server.expect(requestTo("https://runtime.internal/internal/v1/indexing/apply"))
                .andRespond(withTooManyRequests());
        assertFailure(rateLimited, "CONTEXT_INDEX_RATE_LIMITED", true);

        var ioFailure = fixture();
        ioFailure.server.expect(requestTo("https://runtime.internal/internal/v1/indexing/apply"))
                .andRespond(withException(new IOException("secret transport details")));
        assertThatThrownBy(() -> ioFailure.client.apply(ContextIndexingTestFixtures.deleteProjection()))
                .isInstanceOfSatisfying(ContextIndexingRuntimeException.class, failure -> {
                    assertThat(failure.code()).isEqualTo("CONTEXT_INDEX_RUNTIME_IO");
                    assertThat(failure.retryable()).isTrue();
                    assertThat(failure.safeMessage()).doesNotContain("secret transport details");
                });
        ioFailure.server.verify();
    }

    private static void assertFailure(
            ClientFixture fixture,
            String expectedCode,
            boolean expectedRetryable
    ) {
        assertThatThrownBy(() -> fixture.client.apply(ContextIndexingTestFixtures.deleteProjection()))
                .isInstanceOfSatisfying(ContextIndexingRuntimeException.class, failure -> {
                    assertThat(failure.code()).isEqualTo(expectedCode);
                    assertThat(failure.retryable()).isEqualTo(expectedRetryable);
                });
        fixture.server.verify();
    }

    private static ClientFixture fixture() throws Exception {
        var builder = RestClient.builder().baseUrl("https://runtime.internal");
        var server = MockRestServiceServer.bindTo(builder).build();
        var ids = new ArrayDeque<>(java.util.List.of(REQUEST_ID, TRACE_ID));
        var tokenIssueCount = new AtomicInteger();
        return new ClientFixture(
                new HttpContextIndexingRuntimeClient(
                        builder.build(),
                        () -> {
                            tokenIssueCount.incrementAndGet();
                            return "signed-service-token";
                        },
                        ids::remove
                ),
                server,
                tokenIssueCount
        );
    }

    private static String receiptJson(String result, long eventSequence) throws Exception {
        return receiptJson(result, Map.of("eventSequence", eventSequence));
    }

    private static String receiptJson(String result, Map<String, Object> overrides) throws Exception {
        var receipt = new HashMap<String, Object>();
        receipt.put("contractVersion", "1.0");
        receipt.put("requestId", REQUEST_ID);
        receipt.put("jobId", ContextIndexingTestFixtures.JOB_ID);
        receipt.put("leaseEpoch", ContextIndexingTestFixtures.LEASE_EPOCH);
        receipt.put("target", "LEXICAL");
        receipt.put("operation", "UPSERT");
        receipt.put("result", result);
        receipt.put("eventSequence", ContextIndexingTestFixtures.EVENT_SEQUENCE);
        receipt.put("indexedChunkCount", 1);
        receipt.put("indexProfile", "context-default-v1");
        receipt.putAll(overrides);
        return new ObjectMapper().writeValueAsString(receipt);
    }

    private record ClientFixture(
            HttpContextIndexingRuntimeClient client,
            MockRestServiceServer server,
            AtomicInteger tokenIssueCount
    ) {
    }
}

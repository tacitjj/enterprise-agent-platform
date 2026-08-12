package com.dianlian.platform.integration.infrastructure.context;

import com.dianlian.platform.context.api.ContextIndexDispatch;
import com.dianlian.platform.context.api.ContextIndexDispatch.ClaimedProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.ReceiptOutcome;
import com.dianlian.platform.context.api.ContextIndexDispatch.RemoteReceipt;
import com.dianlian.platform.integration.infrastructure.context.ContextIndexingHttpContract.ContextIndexingReceipt;
import com.dianlian.platform.integration.infrastructure.security.InternalServiceJwtIssuer;
import com.dianlian.platform.integration.infrastructure.security.InternalServiceJwtScope;
import java.util.Objects;
import java.util.UUID;
import java.util.function.Supplier;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

final class HttpContextIndexingRuntimeClient implements ContextIndexingRuntimeClient {

    static final String APPLY_PATH = "/internal/v1/indexing/apply";

    private final RestClient restClient;
    private final Supplier<String> tokenSupplier;
    private final Supplier<UUID> idSupplier;

    HttpContextIndexingRuntimeClient(RestClient restClient, InternalServiceJwtIssuer jwtIssuer) {
        this(
                restClient,
                () -> jwtIssuer.issue(InternalServiceJwtScope.CONTEXT_INDEX_WRITE).value(),
                UUID::randomUUID
        );
    }

    HttpContextIndexingRuntimeClient(
            RestClient restClient,
            Supplier<String> tokenSupplier,
            Supplier<UUID> idSupplier
    ) {
        this.restClient = Objects.requireNonNull(restClient, "restClient must not be null");
        this.tokenSupplier = Objects.requireNonNull(tokenSupplier, "tokenSupplier must not be null");
        this.idSupplier = Objects.requireNonNull(idSupplier, "idSupplier must not be null");
    }

    @Override
    public RemoteReceipt apply(ClaimedProjection projection) {
        var requestId = idSupplier.get();
        var traceId = idSupplier.get();
        final ContextIndexingHttpContract.ContextIndexingRequest request;
        try {
            request = ContextIndexingHttpContract.request(projection, requestId, traceId);
        } catch (RuntimeException exception) {
            throw ContextIndexingRuntimeException.permanent("CONTEXT_INDEX_REQUEST_INVALID", exception);
        }

        final String token;
        try {
            token = tokenSupplier.get();
        } catch (RuntimeException exception) {
            throw ContextIndexingRuntimeException.retryable(
                    "CONTEXT_INDEX_SERVICE_JWT_UNAVAILABLE", exception);
        }

        final ContextIndexingReceipt receipt;
        try {
            receipt = restClient.post()
                    .uri(APPLY_PATH)
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + token)
                    .contentType(MediaType.APPLICATION_JSON)
                    .accept(MediaType.APPLICATION_JSON)
                    .body(request)
                    .retrieve()
                    .onStatus(
                            status -> !status.is2xxSuccessful(),
                            (httpRequest, httpResponse) -> {
                                throw new ContextIndexHttpStatusException(httpResponse.getStatusCode().value());
                            }
                    )
                    .body(ContextIndexingReceipt.class);
        } catch (ContextIndexHttpStatusException exception) {
            throw classifyStatus(exception.status());
        } catch (ResourceAccessException exception) {
            throw ContextIndexingRuntimeException.retryable("CONTEXT_INDEX_RUNTIME_IO", exception);
        } catch (RestClientException exception) {
            throw ContextIndexingRuntimeException.permanent("CONTEXT_INDEX_RECEIPT_INVALID", exception);
        }
        return validateReceipt(request, receipt);
    }

    private static RemoteReceipt validateReceipt(
            ContextIndexingHttpContract.ContextIndexingRequest request,
            ContextIndexingReceipt receipt
    ) {
        if (receipt == null
                || !ContextIndexDispatch.PROJECTION_CONTRACT_VERSION.equals(receipt.contractVersion())
                || !request.requestId().equals(receipt.requestId())
                || !request.jobId().equals(receipt.jobId())
                || request.leaseEpoch() != receipt.leaseEpoch()
                || request.eventSequence() != receipt.eventSequence()
                || !request.target().equals(receipt.target())
                || !request.operation().equals(receipt.operation())
                || !request.indexProfile().equals(receipt.indexProfile())
                || receipt.indexedChunkCount() < 0) {
            throw ContextIndexingRuntimeException.permanent("CONTEXT_INDEX_RECEIPT_INVALID", null);
        }
        ReceiptOutcome outcome = switch (Objects.toString(receipt.result(), "")) {
            case "APPLIED" -> ReceiptOutcome.APPLIED;
            case "NOOP_IDEMPOTENT" -> ReceiptOutcome.ALREADY_APPLIED;
            case "NOOP_STALE" -> ReceiptOutcome.IGNORED_STALE;
            default -> throw ContextIndexingRuntimeException.permanent(
                    "CONTEXT_INDEX_RECEIPT_INVALID", null);
        };
        return new RemoteReceipt(
                receipt.requestId().toString(),
                outcome,
                receipt.eventSequence(),
                null
        );
    }

    private static ContextIndexingRuntimeException classifyStatus(int status) {
        return switch (status) {
            case 401 -> ContextIndexingRuntimeException.permanent(
                    "CONTEXT_INDEX_AUTHENTICATION_REJECTED", null);
            case 403 -> ContextIndexingRuntimeException.permanent(
                    "CONTEXT_INDEX_AUTHORIZATION_REJECTED", null);
            case 409 -> ContextIndexingRuntimeException.permanent("CONTEXT_INDEX_CONFLICT", null);
            case 422 -> ContextIndexingRuntimeException.permanent(
                    "CONTEXT_INDEX_CONTRACT_REJECTED", null);
            case 408 -> ContextIndexingRuntimeException.retryable("CONTEXT_INDEX_RUNTIME_TIMEOUT", null);
            case 429 -> ContextIndexingRuntimeException.retryable("CONTEXT_INDEX_RATE_LIMITED", null);
            default -> status >= 500 && status <= 599
                    ? ContextIndexingRuntimeException.retryable("CONTEXT_INDEX_RUNTIME_UNAVAILABLE", null)
                    : ContextIndexingRuntimeException.permanent("CONTEXT_INDEX_HTTP_" + status, null);
        };
    }

    private static final class ContextIndexHttpStatusException extends RuntimeException {

        private final int status;

        private ContextIndexHttpStatusException(int status) {
            super("context indexing runtime returned HTTP " + status);
            this.status = status;
        }

        private int status() {
            return status;
        }
    }
}

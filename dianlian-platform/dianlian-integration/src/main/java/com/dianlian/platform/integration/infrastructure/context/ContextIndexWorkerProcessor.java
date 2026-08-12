package com.dianlian.platform.integration.infrastructure.context;

import com.dianlian.platform.context.api.ContextIndexDispatch;
import com.dianlian.platform.context.api.ContextIndexDispatch.ClaimRequest;
import com.dianlian.platform.context.api.ContextIndexDispatch.CompleteCommand;
import com.dianlian.platform.context.api.ContextIndexDispatch.FailCommand;
import com.dianlian.platform.context.api.ContextIndexDispatch.IndexTarget;
import com.dianlian.platform.context.api.ContextIndexLeaseLostException;
import java.time.Duration;
import java.util.Objects;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

final class ContextIndexWorkerProcessor {

    private static final Logger LOGGER = LoggerFactory.getLogger(ContextIndexWorkerProcessor.class);

    private final ContextIndexDispatch dispatch;
    private final ContextIndexingRuntimeClient runtimeClient;
    private final Duration leaseDuration;

    ContextIndexWorkerProcessor(
            ContextIndexDispatch dispatch,
            ContextIndexingRuntimeClient runtimeClient,
            Duration leaseDuration
    ) {
        this.dispatch = Objects.requireNonNull(dispatch, "dispatch must not be null");
        this.runtimeClient = Objects.requireNonNull(runtimeClient, "runtimeClient must not be null");
        this.leaseDuration = Objects.requireNonNull(leaseDuration, "leaseDuration must not be null");
    }

    /**
     * Claims in the Context module's short transaction, then invokes the runtime only after that
     * call has returned and its transaction has completed.
     */
    boolean processNext(String workerId) {
        var claimed = dispatch.claimNext(new ClaimRequest(
                workerId,
                IndexTarget.LEXICAL,
                ContextIndexDispatch.DEFAULT_INDEX_PROFILE_VERSION,
                leaseDuration
        ));
        if (claimed.isEmpty()) {
            return false;
        }
        var projection = claimed.orElseThrow();
        try {
            var receipt = runtimeClient.apply(projection);
            dispatch.complete(new CompleteCommand(projection.lease(), receipt));
            LOGGER.info(
                    "Context index projection completed: jobId={}, attempt={}, leaseEpoch={}",
                    projection.lease().jobId(),
                    projection.lease().attempt(),
                    projection.lease().leaseEpoch()
            );
        } catch (ContextIndexLeaseLostException exception) {
            logLeaseLost(projection);
        } catch (ContextIndexingRuntimeException exception) {
            failProjection(projection, exception);
        }
        return true;
    }

    private void failProjection(
            ContextIndexDispatch.ClaimedProjection projection,
            ContextIndexingRuntimeException failure
    ) {
        try {
            var disposition = dispatch.fail(new FailCommand(
                    projection.lease(),
                    failure.code(),
                    failure.safeMessage(),
                    failure.retryable()
            ));
            LOGGER.warn(
                    "Context index projection failed: jobId={}, attempt={}, leaseEpoch={}, code={}, retryable={}, disposition={}",
                    projection.lease().jobId(),
                    projection.lease().attempt(),
                    projection.lease().leaseEpoch(),
                    failure.code(),
                    failure.retryable(),
                    disposition
            );
        } catch (ContextIndexLeaseLostException exception) {
            logLeaseLost(projection);
        }
    }

    private static void logLeaseLost(ContextIndexDispatch.ClaimedProjection projection) {
        LOGGER.info(
                "Context index projection lease was lost; no acknowledgement was written: jobId={}, attempt={}, leaseEpoch={}",
                projection.lease().jobId(),
                projection.lease().attempt(),
                projection.lease().leaseEpoch()
        );
    }
}

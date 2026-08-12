package com.dianlian.platform.integration.infrastructure.context;

import static org.assertj.core.api.Assertions.assertThat;

import com.dianlian.platform.context.api.ContextIndexDispatch;
import com.dianlian.platform.context.api.ContextIndexDispatch.ClaimRequest;
import com.dianlian.platform.context.api.ContextIndexDispatch.ClaimedProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.CompleteCommand;
import com.dianlian.platform.context.api.ContextIndexDispatch.ContextIndexLease;
import com.dianlian.platform.context.api.ContextIndexDispatch.FailCommand;
import com.dianlian.platform.context.api.ContextIndexDispatch.FailureDisposition;
import com.dianlian.platform.context.api.ContextIndexDispatch.HeartbeatCommand;
import com.dianlian.platform.context.api.ContextIndexDispatch.IndexTarget;
import com.dianlian.platform.context.api.ContextIndexDispatch.ReceiptOutcome;
import com.dianlian.platform.context.api.ContextIndexDispatch.RemoteReceipt;
import com.dianlian.platform.context.api.ContextIndexLeaseLostException;
import java.time.Duration;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class ContextIndexWorkerProcessorTests {

    @Test
    void claimsTheFixedLexicalCapabilityBeforeCallingHttpAndThenCompletes() {
        var dispatch = new StubDispatch();
        dispatch.claimed = ContextIndexingTestFixtures.knowledgeProjection();
        ContextIndexingRuntimeClient client = projection -> {
            assertThat(dispatch.claimReturned).isTrue();
            return receipt(projection);
        };
        var processor = new ContextIndexWorkerProcessor(dispatch, client, Duration.ofMinutes(1));

        assertThat(processor.processNext("lexical-worker-1")).isTrue();

        assertThat(dispatch.claimRequest.indexTarget()).isEqualTo(IndexTarget.LEXICAL);
        assertThat(dispatch.claimRequest.indexProfileVersion())
                .isEqualTo(ContextIndexDispatch.DEFAULT_INDEX_PROFILE_VERSION);
        assertThat(dispatch.completeCommand).isNotNull();
        assertThat(dispatch.failCommand).isNull();
    }

    @Test
    void preservesRetryClassificationWhenTheRuntimeIsUnavailable() {
        var dispatch = new StubDispatch();
        dispatch.claimed = ContextIndexingTestFixtures.memoryProjection();
        ContextIndexingRuntimeClient client = projection -> {
            throw ContextIndexingRuntimeException.retryable("CONTEXT_INDEX_RUNTIME_IO", null);
        };
        var processor = new ContextIndexWorkerProcessor(dispatch, client, Duration.ofMinutes(1));

        assertThat(processor.processNext("lexical-worker-2")).isTrue();

        assertThat(dispatch.completeCommand).isNull();
        assertThat(dispatch.failCommand.errorCode()).isEqualTo("CONTEXT_INDEX_RUNTIME_IO");
        assertThat(dispatch.failCommand.retryable()).isTrue();
    }

    @Test
    void doesNotWriteAFailureAcknowledgementAfterCompletionFindsTheLeaseLost() {
        var dispatch = new StubDispatch();
        dispatch.claimed = ContextIndexingTestFixtures.deleteProjection();
        dispatch.loseLeaseOnComplete = true;
        ContextIndexingRuntimeClient client = ContextIndexWorkerProcessorTests::receipt;
        var processor = new ContextIndexWorkerProcessor(dispatch, client, Duration.ofMinutes(1));

        assertThat(processor.processNext("lexical-worker-3")).isTrue();

        assertThat(dispatch.completeCommand).isNotNull();
        assertThat(dispatch.failCommand).isNull();
    }

    private static RemoteReceipt receipt(ClaimedProjection projection) {
        return new RemoteReceipt(
                "receipt-1",
                ReceiptOutcome.APPLIED,
                projection.payload().eventSequence(),
                null
        );
    }

    private static final class StubDispatch implements ContextIndexDispatch {

        private ClaimedProjection claimed;
        private ClaimRequest claimRequest;
        private CompleteCommand completeCommand;
        private FailCommand failCommand;
        private boolean claimReturned;
        private boolean loseLeaseOnComplete;

        @Override
        public Optional<ClaimedProjection> claimNext(ClaimRequest request) {
            claimRequest = request;
            claimReturned = true;
            return Optional.ofNullable(claimed);
        }

        @Override
        public ContextIndexLease heartbeat(HeartbeatCommand command) {
            return command.lease();
        }

        @Override
        public void complete(CompleteCommand command) {
            completeCommand = command;
            if (loseLeaseOnComplete) {
                throw new ContextIndexLeaseLostException();
            }
        }

        @Override
        public FailureDisposition fail(FailCommand command) {
            failCommand = command;
            return command.retryable()
                    ? FailureDisposition.RETRY_SCHEDULED
                    : FailureDisposition.DEAD_LETTERED;
        }
    }
}

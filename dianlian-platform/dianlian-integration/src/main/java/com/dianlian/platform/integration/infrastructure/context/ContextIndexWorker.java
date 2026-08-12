package com.dianlian.platform.integration.infrastructure.context;

import java.lang.management.ManagementFactory;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;

final class ContextIndexWorker {

    private static final Logger LOGGER = LoggerFactory.getLogger(ContextIndexWorker.class);

    private final ContextIndexWorkerProcessor processor;
    private final String workerId;
    private final AtomicBoolean polling = new AtomicBoolean();

    ContextIndexWorker(ContextIndexWorkerProcessor processor) {
        this(
                processor,
                ManagementFactory.getRuntimeMXBean().getName() + ":context-index:" + UUID.randomUUID()
        );
    }

    ContextIndexWorker(ContextIndexWorkerProcessor processor, String workerId) {
        this.processor = Objects.requireNonNull(processor, "processor must not be null");
        this.workerId = Objects.requireNonNull(workerId, "workerId must not be null");
    }

    @Scheduled(fixedDelayString = "${dianlian.context-index-worker.poll-delay-ms:1000}")
    void poll() {
        if (!polling.compareAndSet(false, true)) {
            return;
        }
        try {
            processor.processNext(workerId);
        } catch (RuntimeException exception) {
            LOGGER.error(
                    "Context index worker poll failed: errorType={}",
                    exception.getClass().getSimpleName()
            );
        } finally {
            polling.set(false);
        }
    }
}

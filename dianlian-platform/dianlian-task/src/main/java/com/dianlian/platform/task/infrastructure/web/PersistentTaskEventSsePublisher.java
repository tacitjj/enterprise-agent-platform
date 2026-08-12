package com.dianlian.platform.task.infrastructure.web;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.AuthenticationRequiredException;
import com.dianlian.platform.identity.api.SessionAuthenticationPort;
import com.dianlian.platform.task.api.TaskEventBatch;
import com.dianlian.platform.task.api.TaskEventEnvelope;
import com.dianlian.platform.task.api.TaskEventStreamQuery;
import com.dianlian.platform.task.api.TaskEventStreamUnavailableException;
import com.dianlian.platform.task.api.TaskAccessDeniedException;
import com.dianlian.platform.task.api.TaskNotFoundException;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.time.Clock;
import java.time.Duration;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Component
public class PersistentTaskEventSsePublisher implements TaskEventSsePublisher {

    private static final Logger LOGGER = LoggerFactory.getLogger(PersistentTaskEventSsePublisher.class);
    private static final int REPLAY_BATCH_SIZE = 100;
    private static final int MAX_ACTIVE_STREAMS = 256;
    private static final Duration CONNECTION_TIMEOUT = Duration.ofSeconds(25);
    private static final Duration POLL_INTERVAL = Duration.ofSeconds(1);
    private static final Duration HEARTBEAT_INTERVAL = Duration.ofSeconds(10);

    private final TaskEventStreamQuery eventStreamQuery;
    private final SessionAuthenticationPort sessionAuthenticationPort;
    private final Clock clock;
    private final Duration connectionTimeout;
    private final Duration pollInterval;
    private final Duration heartbeatInterval;
    private final ExecutorService streamExecutor;
    private final Semaphore capacity = new Semaphore(MAX_ACTIVE_STREAMS);

    @Autowired
    public PersistentTaskEventSsePublisher(
            TaskEventStreamQuery eventStreamQuery,
            SessionAuthenticationPort sessionAuthenticationPort
    ) {
        this(eventStreamQuery, sessionAuthenticationPort, Clock.systemUTC());
    }

    PersistentTaskEventSsePublisher(
            TaskEventStreamQuery eventStreamQuery,
            SessionAuthenticationPort sessionAuthenticationPort,
            Clock clock
    ) {
        this(
                eventStreamQuery,
                sessionAuthenticationPort,
                clock,
                CONNECTION_TIMEOUT,
                POLL_INTERVAL,
                HEARTBEAT_INTERVAL
        );
    }

    PersistentTaskEventSsePublisher(
            TaskEventStreamQuery eventStreamQuery,
            SessionAuthenticationPort sessionAuthenticationPort,
            Clock clock,
            Duration connectionTimeout,
            Duration pollInterval,
            Duration heartbeatInterval
    ) {
        this.eventStreamQuery = Objects.requireNonNull(eventStreamQuery, "eventStreamQuery must not be null");
        this.sessionAuthenticationPort = Objects.requireNonNull(
                sessionAuthenticationPort,
                "sessionAuthenticationPort must not be null"
        );
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
        this.connectionTimeout = requirePositive(connectionTimeout, "connectionTimeout");
        this.pollInterval = requirePositive(pollInterval, "pollInterval");
        this.heartbeatInterval = requirePositive(heartbeatInterval, "heartbeatInterval");
        this.streamExecutor = Executors.newVirtualThreadPerTaskExecutor();
    }

    @Override
    public SseEmitter open(
            UUID taskId,
            String afterEventId,
            UUID sessionId,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(taskId, "taskId must not be null");
        Objects.requireNonNull(sessionId, "sessionId must not be null");
        Objects.requireNonNull(accessContext, "accessContext must not be null");

        // Perform the first permission/participant check before committing a 200 SSE response.
        var currentAccess = requireCurrentAccess(sessionId, accessContext);
        var initialBatch = eventStreamQuery.read(taskId, afterEventId, REPLAY_BATCH_SIZE, currentAccess);
        if (!capacity.tryAcquire()) {
            throw new TaskEventStreamUnavailableException();
        }

        var emitter = new SseEmitter(connectionTimeout.toMillis());
        var subscription = new Subscription(emitter);
        emitter.onCompletion(subscription::close);
        emitter.onTimeout(subscription::close);
        emitter.onError(error -> subscription.close());

        try {
            sendBatch(emitter, initialBatch);
            if (initialBatch.resetRequired()) {
                emitter.complete();
                subscription.releaseCapacity();
                return emitter;
            }
            var initialCursor = initialBatch.lastEventId(afterEventId);
            subscription.worker.set(streamExecutor.submit(() -> runStream(
                    taskId,
                    initialCursor,
                    sessionId,
                    accessContext,
                    subscription
            )));
            return emitter;
        } catch (IOException | RuntimeException exception) {
            subscription.close();
            subscription.releaseCapacity();
            throw new TaskEventStreamUnavailableException();
        }
    }

    private void runStream(
            UUID taskId,
            String initialCursor,
            UUID sessionId,
            AccessContext accessContext,
            Subscription subscription
    ) {
        var cursor = initialCursor;
        var lastHeartbeatNanos = System.nanoTime();
        try {
            while (!subscription.closed.get()) {
                Thread.sleep(pollInterval);
                if (subscription.closed.get()) {
                    return;
                }

                // Rebuild the principal before each batch. Session/account/tenant/member/role changes
                // therefore close the stream before any later task payload is selected.
                var currentAccess = requireCurrentAccess(sessionId, accessContext);
                var batch = eventStreamQuery.read(taskId, cursor, REPLAY_BATCH_SIZE, currentAccess);
                sendBatch(subscription.emitter, batch);
                cursor = batch.lastEventId(cursor);
                if (batch.resetRequired()) {
                    subscription.emitter.complete();
                    return;
                }

                var now = System.nanoTime();
                if (now - lastHeartbeatNanos >= heartbeatInterval.toNanos()) {
                    subscription.emitter.send(SseEmitter.event().comment("heartbeat"));
                    lastHeartbeatNanos = now;
                }
            }
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
        } catch (AuthenticationRequiredException | TaskNotFoundException | TaskAccessDeniedException exception) {
            subscription.emitter.complete();
        } catch (IOException exception) {
            LOGGER.debug("Task SSE client disconnected taskId={}", taskId);
            subscription.emitter.complete();
        } catch (RuntimeException exception) {
            LOGGER.warn("Task SSE polling stopped taskId={} cause={}", taskId, exception.getClass().getSimpleName());
            // Never append an error body to an already committed event stream. The client reconnects
            // with its last persisted cursor and falls back to the authoritative snapshot if needed.
            subscription.emitter.complete();
        } finally {
            subscription.closed.set(true);
            subscription.releaseCapacity();
        }
    }

    private AccessContext requireCurrentAccess(UUID sessionId, AccessContext expectedAccess) {
        var principal = sessionAuthenticationPort.authenticate(sessionId, clock.instant())
                .orElseThrow(AuthenticationRequiredException::new);
        var currentAccess = AccessContext.fromAuthenticatedPrincipal(principal);
        if (!currentAccess.actorId().equals(expectedAccess.actorId())
                || !currentAccess.tenantId().equals(expectedAccess.tenantId())) {
            throw new AuthenticationRequiredException();
        }
        return currentAccess;
    }

    private static Duration requirePositive(Duration value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isZero() || value.isNegative()) {
            throw new IllegalArgumentException(name + " must be positive");
        }
        return value;
    }

    private static void sendBatch(SseEmitter emitter, TaskEventBatch batch) throws IOException {
        for (TaskEventEnvelope event : batch.events()) {
            emitter.send(SseEmitter.event()
                    .id(event.eventId())
                    .name(event.eventType())
                    .data(event, MediaType.APPLICATION_JSON));
        }
    }

    @PreDestroy
    void stop() {
        streamExecutor.shutdownNow();
    }

    private final class Subscription {
        private final SseEmitter emitter;
        private final AtomicBoolean closed = new AtomicBoolean();
        private final AtomicBoolean capacityReleased = new AtomicBoolean();
        private final AtomicReference<java.util.concurrent.Future<?>> worker = new AtomicReference<>();

        private Subscription(SseEmitter emitter) {
            this.emitter = emitter;
        }

        private void close() {
            if (closed.compareAndSet(false, true)) {
                var currentWorker = worker.get();
                if (currentWorker != null) {
                    currentWorker.cancel(true);
                } else {
                    releaseCapacity();
                }
            }
        }

        private void releaseCapacity() {
            if (capacityReleased.compareAndSet(false, true)) {
                capacity.release();
            }
        }
    }
}

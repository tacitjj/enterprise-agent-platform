package com.dianlian.platform.context.application;

import com.dianlian.platform.context.api.ContextIndexDispatch;
import com.dianlian.platform.context.api.ContextIndexDispatch.ClaimRequest;
import com.dianlian.platform.context.api.ContextIndexDispatch.ClaimedProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.CompleteCommand;
import com.dianlian.platform.context.api.ContextIndexDispatch.ContextIndexLease;
import com.dianlian.platform.context.api.ContextIndexDispatch.FailCommand;
import com.dianlian.platform.context.api.ContextIndexDispatch.FailureDisposition;
import com.dianlian.platform.context.api.ContextIndexDispatch.HeartbeatCommand;
import com.dianlian.platform.context.api.ContextIndexDispatch.IndexOperation;
import com.dianlian.platform.context.api.ContextIndexDispatch.KnowledgeDocumentProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.MemoryItemProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.ProjectionPayload;
import com.dianlian.platform.context.api.ContextIndexDispatch.ResourceType;
import com.dianlian.platform.context.api.ContextIndexDispatch.TombstoneProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.TombstoneReason;
import com.dianlian.platform.context.api.ContextIndexLeaseLostException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Objects;
import java.util.Optional;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Claims and materializes one authority-checked projection in a short transaction.
 * External indexing must happen only after this method returns.
 */
@Service
public final class ContextIndexDispatchApplicationService implements ContextIndexDispatch {

    static final int MAX_ATTEMPTS = 8;
    private static final Duration INITIAL_RETRY_DELAY = Duration.ofSeconds(15);
    private static final Duration MAX_RETRY_DELAY = Duration.ofMinutes(15);

    private final ContextIndexDispatchRepository repository;
    private final Clock clock;

    @Autowired
    public ContextIndexDispatchApplicationService(ContextIndexDispatchRepository repository) {
        this(repository, Clock.systemUTC());
    }

    ContextIndexDispatchApplicationService(ContextIndexDispatchRepository repository, Clock clock) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
    }

    @Override
    @Transactional
    public Optional<ClaimedProjection> claimNext(ClaimRequest request) {
        Objects.requireNonNull(request, "request must not be null");
        Instant now = clock.instant();
        repository.deadLetterExhausted(MAX_ATTEMPTS, now);
        return repository.claimNext(
                        request.workerId(),
                        request.indexTarget(),
                        request.indexProfileVersion(),
                        MAX_ATTEMPTS,
                        now,
                        now.plus(request.leaseDuration())
                )
                .map(this::materialize);
    }

    @Override
    @Transactional
    public ContextIndexLease heartbeat(HeartbeatCommand command) {
        Objects.requireNonNull(command, "command must not be null");
        var lease = command.lease();
        Instant now = clock.instant();
        Instant extendedUntil = now.plus(command.leaseDuration());
        Instant storedUntil = repository.heartbeat(
                lease.jobId(),
                lease.workerId(),
                lease.attempt(),
                lease.leaseEpoch(),
                now,
                extendedUntil
        ).orElseThrow(ContextIndexLeaseLostException::new);
        return new ContextIndexLease(
                lease.jobId(),
                lease.workerId(),
                lease.attempt(),
                lease.leaseEpoch(),
                lease.projectionEventSequence(),
                storedUntil
        );
    }

    @Override
    @Transactional
    public void complete(CompleteCommand command) {
        Objects.requireNonNull(command, "command must not be null");
        var lease = command.lease();
        if (!repository.complete(
                lease.jobId(),
                lease.workerId(),
                lease.attempt(),
                lease.leaseEpoch(),
                clock.instant(),
                command.receipt()
        )) {
            throw new ContextIndexLeaseLostException();
        }
    }

    @Override
    @Transactional
    public FailureDisposition fail(FailCommand command) {
        Objects.requireNonNull(command, "command must not be null");
        var lease = command.lease();
        Instant now = clock.instant();
        Instant nextAttemptAt = now.plus(retryDelay(lease.attempt()));
        return repository.fail(
                lease.jobId(),
                lease.workerId(),
                lease.attempt(),
                lease.leaseEpoch(),
                now,
                nextAttemptAt,
                MAX_ATTEMPTS,
                command.retryable(),
                command.errorCode(),
                command.errorMessage()
        ).orElseThrow(ContextIndexLeaseLostException::new);
    }

    private ClaimedProjection materialize(ContextIndexDispatchRepository.ClaimedIndexJob job) {
        ProjectionPayload payload = switch (job.resourceType()) {
            case KNOWLEDGE_DOCUMENT_VERSION -> knowledgeProjection(job);
            case MEMORY_ITEM_VERSION -> memoryProjection(job);
        };
        var lease = new ContextIndexLease(
                job.jobId(),
                job.workerId(),
                job.attempt(),
                job.leaseEpoch(),
                payload.eventSequence(),
                job.leaseExpiresAt()
        );
        return new ClaimedProjection(lease, payload);
    }

    private ProjectionPayload knowledgeProjection(ContextIndexDispatchRepository.ClaimedIndexJob job) {
        var authority = repository.findKnowledgeAuthority(
                job.tenantId(),
                job.authorityScope(),
                job.resourceId()
        );
        if (job.operation() == IndexOperation.DELETE) {
            return tombstone(job, job.eventSequence(), TombstoneReason.REQUESTED_DELETE);
        }
        if (authority.isEmpty()) {
            return tombstone(job, job.eventSequence(), TombstoneReason.AUTHORITY_NOT_FOUND);
        }
        var snapshot = authority.orElseThrow();
        long eventSequence = Math.max(job.eventSequence(), snapshot.authorityEventSequence());
        if (!sameAuthority(job, snapshot.tenantId(), snapshot.authorityScope())) {
            return tombstone(job, eventSequence, TombstoneReason.AUTHORITY_SCOPE_MISMATCH);
        }
        if (!"ACTIVE".equals(snapshot.spaceStatus())
                || !("PROCESSING".equals(snapshot.documentStatus()) || "READY".equals(snapshot.documentStatus()))
                || !"PUBLISHED".equals(snapshot.versionStatus())
                || !"ACTIVE".equals(snapshot.accessState())) {
            return tombstone(job, eventSequence, TombstoneReason.AUTHORITY_NOT_ACTIVE);
        }
        if (!job.resourceId().equals(snapshot.currentVersionId())) {
            return tombstone(job, eventSequence, TombstoneReason.RESOURCE_VERSION_NOT_CURRENT);
        }
        if (job.resourceVersion() != snapshot.versionResourceVersion()) {
            return tombstone(job, eventSequence, TombstoneReason.RESOURCE_VERSION_NOT_CURRENT);
        }
        if (snapshot.normalizedText() == null
                || snapshot.normalizedTextHash() == null
                || snapshot.normalizationProfileVersion() == null
                || snapshot.normalizedAt() == null) {
            return tombstone(job, eventSequence, TombstoneReason.AUTHORITY_NOT_READY);
        }
        return payload(
                job,
                eventSequence,
                job.operation(),
                new KnowledgeDocumentProjection(
                        snapshot.documentVersionId(),
                        snapshot.documentId(),
                        snapshot.spaceId(),
                        snapshot.title(),
                        snapshot.objectKey(),
                        snapshot.contentHash(),
                        snapshot.normalizedText(),
                        snapshot.normalizedTextHash(),
                        snapshot.normalizationProfileVersion(),
                        snapshot.normalizedAt(),
                        snapshot.mimeType(),
                        snapshot.byteSize(),
                        snapshot.metadataJson()
                )
        );
    }

    private ProjectionPayload memoryProjection(ContextIndexDispatchRepository.ClaimedIndexJob job) {
        if (job.authorityScope() != ContextIndexDispatch.AuthorityScope.TENANT || job.tenantId() == null) {
            return tombstone(job, job.eventSequence(), TombstoneReason.AUTHORITY_SCOPE_MISMATCH);
        }
        var authority = repository.findMemoryAuthority(
                job.tenantId(),
                job.resourceId(),
                job.resourceVersion()
        );
        if (authority.isEmpty()) {
            return tombstone(job, job.eventSequence(), job.operation() == IndexOperation.DELETE
                    ? TombstoneReason.REQUESTED_DELETE : TombstoneReason.AUTHORITY_NOT_FOUND);
        }
        var snapshot = authority.orElseThrow();
        long eventSequence = Math.max(job.eventSequence(), snapshot.authorityEventSequence());
        if (!Objects.equals(job.tenantId(), snapshot.tenantId())) {
            return tombstone(job, eventSequence, TombstoneReason.AUTHORITY_SCOPE_MISMATCH);
        }
        if (job.operation() == IndexOperation.DELETE) {
            return tombstone(job, eventSequence, TombstoneReason.REQUESTED_DELETE);
        }
        if (!"ACTIVE".equals(snapshot.itemStatus())) {
            return tombstone(job, eventSequence, TombstoneReason.AUTHORITY_NOT_ACTIVE);
        }
        if (snapshot.currentVersion() != job.resourceVersion()
                || snapshot.requestedVersion() == null
                || snapshot.requestedVersion() != job.resourceVersion()) {
            return tombstone(job, eventSequence, TombstoneReason.RESOURCE_VERSION_NOT_CURRENT);
        }
        return payload(
                job,
                eventSequence,
                job.operation(),
                new MemoryItemProjection(
                        snapshot.memoryId(),
                        snapshot.requestedVersion(),
                        snapshot.enterpriseAgentId(),
                        snapshot.scopeType(),
                        snapshot.scopeId(),
                        snapshot.content(),
                        snapshot.semanticKey(),
                        snapshot.sourceMessageSequenceNo()
                )
        );
    }

    private static boolean sameAuthority(
            ContextIndexDispatchRepository.ClaimedIndexJob job,
            java.util.UUID tenantId,
            ContextIndexDispatch.AuthorityScope authorityScope
    ) {
        return job.authorityScope() == authorityScope && Objects.equals(job.tenantId(), tenantId);
    }

    private static ProjectionPayload tombstone(
            ContextIndexDispatchRepository.ClaimedIndexJob job,
            long authorityEventSequence,
            TombstoneReason reason
    ) {
        return payload(
                job,
                Math.max(job.eventSequence(), authorityEventSequence),
                IndexOperation.DELETE,
                new TombstoneProjection(reason)
        );
    }

    private static ProjectionPayload payload(
            ContextIndexDispatchRepository.ClaimedIndexJob job,
            long eventSequence,
            IndexOperation effectiveOperation,
            ContextIndexDispatch.ProjectionBody body
    ) {
        return new ProjectionPayload(
                ContextIndexDispatch.PROJECTION_CONTRACT_VERSION,
                job.jobId(),
                job.tenantId(),
                job.authorityScope(),
                job.resourceType(),
                job.resourceId(),
                job.resourceVersion(),
                eventSequence,
                job.indexTarget(),
                job.indexProfileVersion(),
                job.operation(),
                effectiveOperation,
                body
        );
    }

    private static Duration retryDelay(int attempt) {
        int exponent = Math.max(0, Math.min(attempt - 1, 10));
        long seconds = Math.multiplyExact(INITIAL_RETRY_DELAY.toSeconds(), 1L << exponent);
        return Duration.ofSeconds(Math.min(seconds, MAX_RETRY_DELAY.toSeconds()));
    }
}

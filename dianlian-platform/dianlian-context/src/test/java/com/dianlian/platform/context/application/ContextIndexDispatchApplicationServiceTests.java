package com.dianlian.platform.context.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.context.api.ContextIndexDispatch;
import com.dianlian.platform.context.api.ContextIndexDispatch.AuthorityScope;
import com.dianlian.platform.context.api.ContextIndexDispatch.ClaimRequest;
import com.dianlian.platform.context.api.ContextIndexDispatch.CompleteCommand;
import com.dianlian.platform.context.api.ContextIndexDispatch.FailCommand;
import com.dianlian.platform.context.api.ContextIndexDispatch.FailureDisposition;
import com.dianlian.platform.context.api.ContextIndexDispatch.HeartbeatCommand;
import com.dianlian.platform.context.api.ContextIndexDispatch.IndexOperation;
import com.dianlian.platform.context.api.ContextIndexDispatch.IndexTarget;
import com.dianlian.platform.context.api.ContextIndexDispatch.KnowledgeDocumentProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.MemoryScopeType;
import com.dianlian.platform.context.api.ContextIndexDispatch.ReceiptOutcome;
import com.dianlian.platform.context.api.ContextIndexDispatch.RemoteReceipt;
import com.dianlian.platform.context.api.ContextIndexDispatch.ResourceType;
import com.dianlian.platform.context.api.ContextIndexDispatch.TombstoneProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.TombstoneReason;
import com.dianlian.platform.context.api.ContextIndexLeaseLostException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class ContextIndexDispatchApplicationServiceTests {

    private static final Instant NOW = Instant.parse("2026-08-12T03:00:00Z");
    private static final UUID TENANT_ID = UUID.fromString("10000000-0000-4000-8000-000000000001");
    private static final UUID JOB_ID = UUID.fromString("10000000-0000-4000-8000-000000000002");
    private static final UUID RESOURCE_ID = UUID.fromString("10000000-0000-4000-8000-000000000003");
    private static final UUID DOCUMENT_ID = UUID.fromString("10000000-0000-4000-8000-000000000004");
    private static final UUID SPACE_ID = UUID.fromString("10000000-0000-4000-8000-000000000005");
    private static final UUID AGENT_ID = UUID.fromString("10000000-0000-4000-8000-000000000006");
    private static final UUID SCOPE_ID = UUID.fromString("10000000-0000-4000-8000-000000000007");

    @Test
    void claimsThenMaterializesOnlyTheCurrentActivePublishedKnowledgeAuthority() {
        var repository = new StubRepository();
        repository.claimed = knowledgeJob(IndexOperation.UPSERT, 11, 2);
        repository.knowledge = new ContextIndexDispatchRepository.KnowledgeAuthoritySnapshot(
                TENANT_ID,
                AuthorityScope.TENANT,
                RESOURCE_ID,
                DOCUMENT_ID,
                RESOURCE_ID,
                SPACE_ID,
                "ACTIVE",
                "PROCESSING",
                "PUBLISHED",
                "ACTIVE",
                2,
                17,
                "制度文档",
                "tenant/object.pdf",
                "a".repeat(64),
                "已经解析的正文",
                "c".repeat(64),
                "normalize-v1",
                NOW,
                "application/pdf",
                128,
                "{}"
        );

        var claimed = service(repository).claimNext(claimRequest(IndexTarget.VECTOR))
                .orElseThrow();

        assertThat(repository.deadLetterCalled).isTrue();
        assertThat(claimed.lease().attempt()).isEqualTo(2);
        assertThat(claimed.lease().leaseEpoch()).isEqualTo(7);
        assertThat(claimed.payload().eventSequence()).isEqualTo(17);
        assertThat(claimed.payload().indexProfileVersion())
                .isEqualTo(ContextIndexDispatch.DEFAULT_INDEX_PROFILE_VERSION);
        assertThat(claimed.payload().operation()).isEqualTo(IndexOperation.UPSERT);
        assertThat(claimed.payload().body()).isInstanceOfSatisfying(
                KnowledgeDocumentProjection.class,
                body -> {
                    assertThat(body.documentVersionId()).isEqualTo(RESOURCE_ID);
                    assertThat(body.normalizedText()).isEqualTo("已经解析的正文");
                    assertThat(body.normalizedTextHash()).isEqualTo("c".repeat(64));
                }
        );
    }

    @Test
    void convertsAStaleMemoryUpsertIntoALaterTombstone() {
        var repository = new StubRepository();
        repository.claimed = memoryJob(IndexOperation.UPSERT, 12, 1);
        repository.memory = new ContextIndexDispatchRepository.MemoryAuthoritySnapshot(
                TENANT_ID,
                RESOURCE_ID,
                2,
                "ACTIVE",
                25,
                1L,
                AGENT_ID,
                MemoryScopeType.USER_AGENT,
                SCOPE_ID,
                "过期版本",
                "preference",
                null
        );

        var payload = service(repository).claimNext(claimRequest(IndexTarget.VECTOR))
                .orElseThrow()
                .payload();

        assertThat(payload.queuedOperation()).isEqualTo(IndexOperation.UPSERT);
        assertThat(payload.operation()).isEqualTo(IndexOperation.DELETE);
        assertThat(payload.eventSequence()).isEqualTo(25);
        assertThat(payload.body()).isEqualTo(new TombstoneProjection(
                TombstoneReason.RESOURCE_VERSION_NOT_CURRENT
        ));
    }

    @Test
    void convertsALegacyUnnormalizedKnowledgeJobIntoAFailClosedTombstone() {
        var repository = new StubRepository();
        repository.claimed = knowledgeJob(IndexOperation.UPSERT, 11);
        repository.knowledge = new ContextIndexDispatchRepository.KnowledgeAuthoritySnapshot(
                TENANT_ID,
                AuthorityScope.TENANT,
                RESOURCE_ID,
                DOCUMENT_ID,
                RESOURCE_ID,
                SPACE_ID,
                "ACTIVE",
                "PROCESSING",
                "PUBLISHED",
                "ACTIVE",
                1,
                11,
                "旧版未解析文档",
                "tenant/legacy.pdf",
                "a".repeat(64),
                null,
                null,
                null,
                null,
                "application/pdf",
                128,
                "{}"
        );

        var payload = service(repository).claimNext(claimRequest(IndexTarget.VECTOR))
                .orElseThrow()
                .payload();

        assertThat(payload.operation()).isEqualTo(IndexOperation.DELETE);
        assertThat(payload.body()).isEqualTo(new TombstoneProjection(TombstoneReason.AUTHORITY_NOT_READY));
    }

    @Test
    void keepsTheOriginalCursorForAnExplicitDeleteSoItCannotOverwriteANewerEvent() {
        var repository = new StubRepository();
        repository.claimed = knowledgeJob(IndexOperation.DELETE, 11);
        repository.knowledge = new ContextIndexDispatchRepository.KnowledgeAuthoritySnapshot(
                TENANT_ID, AuthorityScope.TENANT, RESOURCE_ID, DOCUMENT_ID, RESOURCE_ID, SPACE_ID,
                "ACTIVE", "READY", "PUBLISHED", "ACTIVE", 3, 99,
                "新版本", "new.pdf", "b".repeat(64), "new", "c".repeat(64), "normalize-v1", NOW,
                "application/pdf", 10, "{}"
        );

        var payload = service(repository).claimNext(claimRequest(IndexTarget.VECTOR))
                .orElseThrow()
                .payload();

        assertThat(payload.operation()).isEqualTo(IndexOperation.DELETE);
        assertThat(payload.eventSequence()).isEqualTo(11);
        assertThat(payload.body()).isEqualTo(new TombstoneProjection(TombstoneReason.REQUESTED_DELETE));
    }

    @Test
    void heartbeatAndAcknowledgementsFailClosedWhenTheFenceIsLost() {
        var repository = new StubRepository();
        repository.claimed = memoryJob(IndexOperation.DELETE, 30, 2);
        var dispatch = service(repository);
        var claimed = dispatch.claimNext(claimRequest(IndexTarget.VECTOR)).orElseThrow();

        repository.leaseOwned = false;

        assertThatThrownBy(() -> dispatch.heartbeat(new HeartbeatCommand(
                claimed.lease(),
                Duration.ofMinutes(2)
        ))).isInstanceOf(ContextIndexLeaseLostException.class);
        assertThatThrownBy(() -> dispatch.complete(new CompleteCommand(
                claimed.lease(),
                new RemoteReceipt("receipt-1", ReceiptOutcome.APPLIED, 30, null)
        ))).isInstanceOf(ContextIndexLeaseLostException.class);
        assertThatThrownBy(() -> dispatch.fail(new FailCommand(
                claimed.lease(),
                "PROVIDER_UNAVAILABLE",
                "provider unavailable",
                true
        ))).isInstanceOf(ContextIndexLeaseLostException.class);
    }

    @Test
    void aLexicalWorkerDoesNotClaimAVectorJob() {
        var repository = new StubRepository();
        repository.claimed = memoryJob(IndexOperation.UPSERT, 31, 1);

        var claimed = service(repository).claimNext(new ClaimRequest(
                "lexical-worker-1",
                IndexTarget.LEXICAL,
                ContextIndexDispatch.DEFAULT_INDEX_PROFILE_VERSION,
                Duration.ofMinutes(2)
        ));

        assertThat(claimed).isEmpty();
        assertThat(repository.requestedIndexTarget).isEqualTo(IndexTarget.LEXICAL);
        assertThat(repository.requestedIndexProfileVersion)
                .isEqualTo(ContextIndexDispatch.DEFAULT_INDEX_PROFILE_VERSION);
    }

    @Test
    void aWorkerDoesNotClaimAJobFromAnotherIndexProfile() {
        var repository = new StubRepository();
        repository.claimed = memoryJob(IndexOperation.UPSERT, 32, 1);

        var claimed = service(repository).claimNext(new ClaimRequest(
                "vector-worker-2",
                IndexTarget.VECTOR,
                "vector-profile-v2",
                Duration.ofMinutes(2)
        ));

        assertThat(claimed).isEmpty();
        assertThat(repository.requestedIndexTarget).isEqualTo(IndexTarget.VECTOR);
        assertThat(repository.requestedIndexProfileVersion).isEqualTo("vector-profile-v2");
    }

    private static ContextIndexDispatchApplicationService service(StubRepository repository) {
        return new ContextIndexDispatchApplicationService(
                repository,
                Clock.fixed(NOW, ZoneOffset.UTC)
        );
    }

    private static ClaimRequest claimRequest(IndexTarget indexTarget) {
        return new ClaimRequest(
                "index-worker-1",
                indexTarget,
                ContextIndexDispatch.DEFAULT_INDEX_PROFILE_VERSION,
                Duration.ofMinutes(2)
        );
    }

    private static ContextIndexDispatchRepository.ClaimedIndexJob knowledgeJob(
            IndexOperation operation,
            long eventSequence
    ) {
        return knowledgeJob(operation, eventSequence, 1);
    }

    private static ContextIndexDispatchRepository.ClaimedIndexJob knowledgeJob(
            IndexOperation operation,
            long eventSequence,
            long resourceVersion
    ) {
        return job(ResourceType.KNOWLEDGE_DOCUMENT_VERSION, operation, eventSequence, resourceVersion);
    }

    private static ContextIndexDispatchRepository.ClaimedIndexJob memoryJob(
            IndexOperation operation,
            long eventSequence,
            long resourceVersion
    ) {
        return job(ResourceType.MEMORY_ITEM_VERSION, operation, eventSequence, resourceVersion);
    }

    private static ContextIndexDispatchRepository.ClaimedIndexJob job(
            ResourceType resourceType,
            IndexOperation operation,
            long eventSequence,
            long resourceVersion
    ) {
        return new ContextIndexDispatchRepository.ClaimedIndexJob(
                JOB_ID,
                TENANT_ID,
                AuthorityScope.TENANT,
                resourceType,
                RESOURCE_ID,
                resourceVersion,
                eventSequence,
                IndexTarget.VECTOR,
                ContextIndexDispatch.DEFAULT_INDEX_PROFILE_VERSION,
                operation,
                "index-worker-1",
                2,
                7,
                NOW.plusSeconds(120)
        );
    }

    private static final class StubRepository implements ContextIndexDispatchRepository {

        private ClaimedIndexJob claimed;
        private KnowledgeAuthoritySnapshot knowledge;
        private MemoryAuthoritySnapshot memory;
        private boolean deadLetterCalled;
        private boolean leaseOwned = true;
        private IndexTarget requestedIndexTarget;
        private String requestedIndexProfileVersion;

        @Override
        public void deadLetterExhausted(int maxAttempts, Instant now) {
            deadLetterCalled = true;
        }

        @Override
        public Optional<ClaimedIndexJob> claimNext(
                String workerId,
                IndexTarget indexTarget,
                String indexProfileVersion,
                int maxAttempts,
                Instant now,
                Instant leaseExpiresAt
        ) {
            requestedIndexTarget = indexTarget;
            requestedIndexProfileVersion = indexProfileVersion;
            return Optional.ofNullable(claimed)
                    .filter(job -> job.indexTarget() == indexTarget)
                    .filter(job -> job.indexProfileVersion().equals(indexProfileVersion));
        }

        @Override
        public Optional<KnowledgeAuthoritySnapshot> findKnowledgeAuthority(
                UUID tenantId,
                AuthorityScope authorityScope,
                UUID documentVersionId
        ) {
            return Optional.ofNullable(knowledge);
        }

        @Override
        public Optional<MemoryAuthoritySnapshot> findMemoryAuthority(
                UUID tenantId,
                UUID memoryId,
                long requestedVersion
        ) {
            return Optional.ofNullable(memory);
        }

        @Override
        public Optional<Instant> heartbeat(
                UUID jobId,
                String workerId,
                int attempt,
                long leaseEpoch,
                Instant now,
                Instant newLeaseExpiresAt
        ) {
            return leaseOwned ? Optional.of(newLeaseExpiresAt) : Optional.empty();
        }

        @Override
        public boolean complete(
                UUID jobId,
                String workerId,
                int attempt,
                long leaseEpoch,
                Instant now,
                RemoteReceipt receipt
        ) {
            return leaseOwned;
        }

        @Override
        public Optional<FailureDisposition> fail(
                UUID jobId,
                String workerId,
                int attempt,
                long leaseEpoch,
                Instant now,
                Instant nextAttemptAt,
                int maxAttempts,
                boolean retryable,
                String errorCode,
                String errorMessage
        ) {
            return leaseOwned
                    ? Optional.of(retryable
                            ? FailureDisposition.RETRY_SCHEDULED
                            : FailureDisposition.DEAD_LETTERED)
                    : Optional.empty();
        }
    }
}

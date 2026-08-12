package com.dianlian.platform.memory.application;

import static com.dianlian.platform.identity.api.AccessContextFixtures.authenticated;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.memory.api.ConfirmMemoryCandidateCommand;
import com.dianlian.platform.memory.api.CorrectMemoryCommand;
import com.dianlian.platform.memory.api.ForgetMemoryCommand;
import com.dianlian.platform.memory.api.GroupMembershipUnavailableException;
import com.dianlian.platform.memory.api.InvocationMemoryAuthoritySource;
import com.dianlian.platform.memory.api.InvocationMemoryBoundaryVerifier;
import com.dianlian.platform.memory.api.MemoryAccessDeniedException;
import com.dianlian.platform.memory.api.MemoryCandidateStatus;
import com.dianlian.platform.memory.api.MemoryCommandConflictException;
import com.dianlian.platform.memory.api.MemoryItemStatus;
import com.dianlian.platform.memory.api.MemoryPermissions;
import com.dianlian.platform.memory.api.MemoryScopeRef;
import com.dianlian.platform.memory.api.MemoryScopeType;
import com.dianlian.platform.memory.api.ProposeMemoryCandidateCommand;
import com.dianlian.platform.memory.api.RecallConfirmedMemoryQuery;
import com.dianlian.platform.memory.api.RejectMemoryCandidateCommand;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;

class MemoryApplicationServiceTests {

    private static final UUID TENANT_ID = uuid(1);
    private static final UUID ACTOR_ID = uuid(2);
    private static final UUID OTHER_USER_ID = uuid(3);
    private static final UUID AGENT_ID = uuid(4);
    private static final UUID GROUP_ID = uuid(5);
    private static final Instant NOW = Instant.parse("2026-08-12T01:02:03Z");

    @Test
    void confirmedMemoryIsVersionedAndImmediatelyExcludedAfterForget() {
        var repository = new TestMemoryRepository();
        var service = service(repository, List.of());
        var access = authenticated(
                TENANT_ID, ACTOR_ID,
                MemoryPermissions.CANDIDATE_PROPOSE,
                MemoryPermissions.SELF_MANAGE,
                MemoryPermissions.RECALL
        );
        var scope = new MemoryScopeRef(MemoryScopeType.USER_AGENT, ACTOR_ID);

        var proposed = service.propose(propose(scope, "用户偏好蓝色", "propose-1", "hash-1"), access).value();
        assertThat(repository.indexJobs).isEmpty();
        var confirmed = service.confirm(new ConfirmMemoryCandidateCommand(
                proposed.candidateId(), "用户确认", "confirm-1", "hash-2"
        ), access);
        var replay = service.confirm(new ConfirmMemoryCandidateCommand(
                proposed.candidateId(), "用户确认", "confirm-1", "hash-2"
        ), access);

        assertThat(confirmed.value().status()).isEqualTo(MemoryCandidateStatus.CONFIRMED);
        assertThat(replay.replayed()).isTrue();
        assertThat(repository.indexJobs).hasSize(2)
                .allMatch(job -> job.operation() == MemoryIndexJobWrite.Operation.UPSERT)
                .allMatch(job -> job.resourceVersion() == 1);
        assertThat(service.recallConfirmed(recall(scope, "蓝色"), access)).hasSize(1);

        UUID memoryId = confirmed.value().confirmedMemoryId();
        var correction = new CorrectMemoryCommand(
                memoryId, "用户偏好绿色", "color-preference", "用户纠正",
                "correct-1", "hash-3"
        );
        service.correct(correction, access);
        assertThat(service.correct(correction, access).replayed()).isTrue();
        assertThat(repository.indexJobs).hasSize(4);
        assertThat(service.recallConfirmed(recall(scope, "绿色"), access))
                .singleElement()
                .satisfies(memory -> assertThat(memory.version()).isEqualTo(2));

        var forget = new ForgetMemoryCommand(
                memoryId, "用户要求遗忘", "forget-1", "hash-4"
        );
        service.forget(forget, access);
        assertThat(service.forget(forget, access).replayed()).isTrue();

        assertThat(service.recallConfirmed(recall(scope, "绿色"), access)).isEmpty();
        assertThat(repository.memories.get(memoryId).status()).isEqualTo(MemoryItemStatus.FORGOTTEN);
        assertThat(repository.versions).hasSize(2);
        assertThat(repository.events).hasSize(4);
        assertThat(repository.indexJobs)
                .extracting(job -> job.operation() + ":" + job.resourceVersion() + ":" + job.indexTarget())
                .containsExactlyInAnyOrder(
                        "UPSERT:1:LEXICAL",
                        "UPSERT:1:VECTOR",
                        "UPSERT:2:LEXICAL",
                        "UPSERT:2:VECTOR",
                        "DELETE:2:LEXICAL",
                        "DELETE:2:VECTOR"
                );
        long newestUpsertSequence = repository.indexJobs.stream()
                .filter(job -> job.operation() == MemoryIndexJobWrite.Operation.UPSERT)
                .mapToLong(MemoryIndexJobWrite::eventSequence)
                .max()
                .orElseThrow();
        assertThat(repository.indexJobs.stream()
                .filter(job -> job.operation() == MemoryIndexJobWrite.Operation.DELETE)
                .mapToLong(MemoryIndexJobWrite::eventSequence))
                .allMatch(sequence -> sequence > newestUpsertSequence);
    }

    @Test
    void userAgentScopeCannotBeDecidedOrReadForAnotherUser() {
        var repository = new TestMemoryRepository();
        var service = service(repository, List.of());
        var access = authenticated(
                TENANT_ID, ACTOR_ID,
                MemoryPermissions.CANDIDATE_PROPOSE,
                MemoryPermissions.SELF_MANAGE,
                MemoryPermissions.RECALL
        );
        var otherUsersScope = new MemoryScopeRef(MemoryScopeType.USER_AGENT, OTHER_USER_ID);

        assertThatThrownBy(() -> service.propose(
                propose(otherUsersScope, "越权内容", "propose-other", "hash-other"), access
        )).isInstanceOf(MemoryAccessDeniedException.class);
        assertThatThrownBy(() -> service.recallConfirmed(recall(otherUsersScope, "越权"), access))
                .isInstanceOf(MemoryAccessDeniedException.class);
    }

    @Test
    void groupMemoryFailsClosedWithoutExactlyOneMembershipVerifier() {
        var service = service(new TestMemoryRepository(), List.of());
        var access = authenticated(TENANT_ID, ACTOR_ID, MemoryPermissions.CANDIDATE_PROPOSE);
        var groupScope = new MemoryScopeRef(MemoryScopeType.GROUP_AGENT, GROUP_ID);

        assertThatThrownBy(() -> service.propose(
                propose(groupScope, "群记忆", "group-propose", "group-hash"), access
        )).isInstanceOf(GroupMembershipUnavailableException.class);
    }

    @Test
    void agentCandidateRequiresGovernancePermissionBeforeConfirmation() {
        var repository = new TestMemoryRepository();
        var service = service(repository, List.of());
        var scope = new MemoryScopeRef(MemoryScopeType.AGENT, AGENT_ID);
        var proposer = authenticated(TENANT_ID, ACTOR_ID, MemoryPermissions.CANDIDATE_PROPOSE);
        var candidate = service.propose(
                propose(scope, "员工通用工作习惯", "agent-propose", "agent-hash"), proposer
        ).value();
        var confirm = new ConfirmMemoryCandidateCommand(
                candidate.candidateId(), null, "agent-confirm", "agent-confirm-hash"
        );

        assertThatThrownBy(() -> service.confirm(confirm, proposer))
                .isInstanceOf(MemoryAccessDeniedException.class);

        var governor = authenticated(TENANT_ID, ACTOR_ID, MemoryPermissions.AGENT_GOVERN);
        assertThat(service.confirm(confirm, governor).value().status())
                .isEqualTo(MemoryCandidateStatus.CONFIRMED);
    }

    @Test
    void reusedDecisionIdempotencyKeyWithDifferentHashIsRejected() {
        var repository = new TestMemoryRepository();
        var service = service(repository, List.of());
        var access = authenticated(
                TENANT_ID, ACTOR_ID,
                MemoryPermissions.CANDIDATE_PROPOSE,
                MemoryPermissions.SELF_MANAGE
        );
        var scope = new MemoryScopeRef(MemoryScopeType.USER_AGENT, ACTOR_ID);
        var candidate = service.propose(propose(scope, "偏好简洁", "p-idem", "p-hash"), access).value();
        service.confirm(new ConfirmMemoryCandidateCommand(
                candidate.candidateId(), null, "decision-idem", "decision-hash"
        ), access);

        assertThatThrownBy(() -> service.confirm(new ConfirmMemoryCandidateCommand(
                candidate.candidateId(), null, "decision-idem", "different-hash"
        ), access))
                .isInstanceOfSatisfying(MemoryCommandConflictException.class,
                        error -> assertThat(error.code()).isEqualTo("IDEMPOTENCY_REQUEST_CONFLICT"));
    }

    @Test
    void rejectedCandidateAndItsReplayNeverEnqueueAnIndexJob() {
        var repository = new TestMemoryRepository();
        var service = service(repository, List.of());
        var access = authenticated(
                TENANT_ID, ACTOR_ID,
                MemoryPermissions.CANDIDATE_PROPOSE,
                MemoryPermissions.SELF_MANAGE
        );
        var scope = new MemoryScopeRef(MemoryScopeType.USER_AGENT, ACTOR_ID);
        var candidate = service.propose(propose(scope, "错误偏好", "reject-propose", "reject-propose-hash"), access)
                .value();
        var reject = new RejectMemoryCandidateCommand(
                candidate.candidateId(), "内容不准确", "reject-decision", "reject-decision-hash"
        );

        service.reject(reject, access);
        assertThat(service.reject(reject, access).replayed()).isTrue();
        assertThat(repository.indexJobs).isEmpty();
    }

    @Test
    void directInvocationAuthorizesOnlyAgentAndActorsPrivateScope() {
        var service = service(new TestMemoryRepository(), List.of(), List.of(query -> true));

        var result = service.authorizeScopes(invocation(false, 0));

        assertThat(result.authorized()).isTrue();
        assertThat(result.scopes())
                .extracting(InvocationMemoryAuthoritySource.AuthorizedMemoryScope::scopeType)
                .containsExactly(MemoryScopeType.AGENT, MemoryScopeType.USER_AGENT);
        assertThat(result.scopes().get(0).scopeId()).isEqualTo(AGENT_ID);
        assertThat(result.scopes().get(1).scopeId()).isEqualTo(ACTOR_ID);
        assertThat(result.scopes()).allMatch(scope -> scope.historyFloorSequenceNo() == 0);
    }

    @Test
    void groupInvocationAuthorizesOnlyAgentAndThisGroupsScope() {
        var service = service(new TestMemoryRepository(), List.of(), List.of(query -> true));

        var result = service.authorizeScopes(invocation(true, 7));

        assertThat(result.authorized()).isTrue();
        assertThat(result.scopes())
                .extracting(InvocationMemoryAuthoritySource.AuthorizedMemoryScope::scopeType)
                .containsExactly(MemoryScopeType.AGENT, MemoryScopeType.GROUP_AGENT)
                .doesNotContain(MemoryScopeType.USER_AGENT);
        assertThat(result.scopes().get(1).scopeId()).isEqualTo(GROUP_ID);
        assertThat(result.scopes().get(0).historyFloorSequenceNo()).isZero();
        assertThat(result.scopes().get(1).historyFloorSequenceNo()).isEqualTo(7);
    }

    @Test
    void invocationAuthorityFailsClosedWithoutOneBoundaryVerifier() {
        var none = service(new TestMemoryRepository(), List.of(), List.of());
        var multiple = service(
                new TestMemoryRepository(),
                List.of(),
                List.of(query -> true, query -> true)
        );

        assertThat(none.authorizeScopes(invocation(false, 0)).rejectionCode())
                .isEqualTo(InvocationMemoryAuthoritySource.RejectionCode.AUTHORITY_BOUNDARY_UNAVAILABLE);
        assertThat(multiple.authorizeScopes(invocation(true, 7)).rejectionCode())
                .isEqualTo(InvocationMemoryAuthoritySource.RejectionCode.AUTHORITY_BOUNDARY_UNAVAILABLE);
    }

    @Test
    void invocationAuthorityFailsClosedWhenBoundaryDeniesOrThrows() {
        var denied = service(new TestMemoryRepository(), List.of(), List.of(query -> false));
        var failed = service(new TestMemoryRepository(), List.of(), List.of(query -> {
            throw new IllegalStateException("boundary unavailable");
        }));

        assertThat(denied.authorizeScopes(invocation(false, 0)).rejectionCode())
                .isEqualTo(InvocationMemoryAuthoritySource.RejectionCode.INVOCATION_BOUNDARY_DENIED);
        assertThat(failed.authorizeScopes(invocation(true, 7)).rejectionCode())
                .isEqualTo(InvocationMemoryAuthoritySource.RejectionCode.AUTHORITY_BOUNDARY_UNAVAILABLE);
    }

    @Test
    void groupReauthorizationRejectsPrivateMemoryAsWholeContractViolation() {
        var repository = new TestMemoryRepository();
        UUID memoryId = uuid(50);
        repository.memories.put(memoryId, memory(
                memoryId,
                AGENT_ID,
                new MemoryScopeRef(MemoryScopeType.USER_AGENT, ACTOR_ID),
                MemoryItemStatus.ACTIVE,
                1
        ));
        var service = service(repository, List.of(), List.of(query -> true));

        var result = service.reauthorize(new InvocationMemoryAuthoritySource.ReauthorizeQuery(
                invocation(true, 7),
                List.of(new InvocationMemoryAuthoritySource.MemoryEvidenceKey(memoryId, 1))
        ));

        assertThat(result.contractAccepted()).isFalse();
        assertThat(result.contractRejectionCode()).isEqualTo(
                InvocationMemoryAuthoritySource.RejectionCode.GROUP_PRIVATE_SCOPE_CONTRACT_VIOLATION
        );
        assertThat(result.allowed()).isEmpty();
    }

    @Test
    void exactReauthorizationReturnsOnlyCurrentActiveAllowedEvidenceWithoutContent() {
        var repository = new TestMemoryRepository();
        UUID allowedId = uuid(51);
        UUID oldVersionId = uuid(52);
        UUID forgottenId = uuid(53);
        UUID preHistoryId = uuid(54);
        UUID missingSequenceId = uuid(55);
        UUID otherAgentId = uuid(56);
        UUID otherGroupId = uuid(57);
        var groupScope = new MemoryScopeRef(MemoryScopeType.GROUP_AGENT, GROUP_ID);
        repository.memories.put(allowedId, memory(allowedId, AGENT_ID, groupScope, MemoryItemStatus.ACTIVE, 2));
        repository.memories.put(oldVersionId, memory(oldVersionId, AGENT_ID, groupScope, MemoryItemStatus.ACTIVE, 2));
        repository.memories.put(forgottenId, memory(forgottenId, AGENT_ID, groupScope, MemoryItemStatus.FORGOTTEN, 1));
        repository.memories.put(preHistoryId, memory(preHistoryId, AGENT_ID, groupScope, MemoryItemStatus.ACTIVE, 1));
        repository.memories.put(
                missingSequenceId,
                memory(missingSequenceId, AGENT_ID, groupScope, MemoryItemStatus.ACTIVE, 1)
        );
        repository.memories.put(
                otherAgentId,
                memory(otherAgentId, uuid(404), groupScope, MemoryItemStatus.ACTIVE, 1)
        );
        repository.memories.put(
                otherGroupId,
                memory(
                        otherGroupId,
                        AGENT_ID,
                        new MemoryScopeRef(MemoryScopeType.GROUP_AGENT, uuid(405)),
                        MemoryItemStatus.ACTIVE,
                        1
                )
        );
        repository.authoritySourceSequences.put(allowedId, 8L);
        repository.authoritySourceSequences.put(oldVersionId, 8L);
        repository.authoritySourceSequences.put(forgottenId, 8L);
        repository.authoritySourceSequences.put(preHistoryId, 6L);
        repository.authoritySourceSequences.put(otherAgentId, 8L);
        repository.authoritySourceSequences.put(otherGroupId, 8L);
        var keys = List.of(
                new InvocationMemoryAuthoritySource.MemoryEvidenceKey(allowedId, 2),
                new InvocationMemoryAuthoritySource.MemoryEvidenceKey(oldVersionId, 1),
                new InvocationMemoryAuthoritySource.MemoryEvidenceKey(forgottenId, 1),
                new InvocationMemoryAuthoritySource.MemoryEvidenceKey(preHistoryId, 1),
                new InvocationMemoryAuthoritySource.MemoryEvidenceKey(missingSequenceId, 1),
                new InvocationMemoryAuthoritySource.MemoryEvidenceKey(otherAgentId, 1),
                new InvocationMemoryAuthoritySource.MemoryEvidenceKey(otherGroupId, 1),
                new InvocationMemoryAuthoritySource.MemoryEvidenceKey(uuid(999), 1)
        );
        var service = service(repository, List.of(), List.of(query -> true));

        var result = service.reauthorize(new InvocationMemoryAuthoritySource.ReauthorizeQuery(
                invocation(true, 7), keys
        ));

        assertThat(result.contractAccepted()).isTrue();
        assertThat(result.allowed()).singleElement()
                .satisfies(evidence -> {
                    assertThat(evidence.key()).isEqualTo(keys.getFirst());
                    assertThat(evidence.scope()).isEqualTo(groupScope);
                });
        assertThat(result.rejected())
                .extracting(InvocationMemoryAuthoritySource.RejectedMemoryEvidence::rejectionCode)
                .containsExactly(
                        InvocationMemoryAuthoritySource.RejectionCode.MEMORY_VERSION_NOT_CURRENT,
                        InvocationMemoryAuthoritySource.RejectionCode.MEMORY_NOT_ACTIVE,
                        InvocationMemoryAuthoritySource.RejectionCode.GROUP_MEMORY_BEFORE_HISTORY_FLOOR,
                        InvocationMemoryAuthoritySource.RejectionCode.GROUP_MEMORY_SOURCE_SEQUENCE_MISSING,
                        InvocationMemoryAuthoritySource.RejectionCode.MEMORY_AGENT_MISMATCH,
                        InvocationMemoryAuthoritySource.RejectionCode.MEMORY_SCOPE_NOT_ALLOWED,
                        InvocationMemoryAuthoritySource.RejectionCode.MEMORY_NOT_FOUND
                );
    }

    private static MemoryApplicationService service(
            TestMemoryRepository repository,
            List<com.dianlian.platform.memory.api.GroupMembershipVerifier> membershipVerifiers
    ) {
        var sequence = new AtomicLong(100);
        return new MemoryApplicationService(
                repository,
                membershipVerifiers,
                List.of(query -> true),
                Clock.fixed(NOW, ZoneOffset.UTC),
                () -> uuid(sequence.getAndIncrement())
        );
    }

    private static MemoryApplicationService service(
            TestMemoryRepository repository,
            List<com.dianlian.platform.memory.api.GroupMembershipVerifier> membershipVerifiers,
            List<InvocationMemoryBoundaryVerifier> invocationBoundaryVerifiers
    ) {
        var sequence = new AtomicLong(100);
        return new MemoryApplicationService(
                repository,
                membershipVerifiers,
                invocationBoundaryVerifiers,
                Clock.fixed(NOW, ZoneOffset.UTC),
                () -> uuid(sequence.getAndIncrement())
        );
    }

    private static InvocationMemoryAuthoritySource.AuthorizeScopesQuery invocation(
            boolean group,
            long historyFloor
    ) {
        return new InvocationMemoryAuthoritySource.AuthorizeScopesQuery(
                TENANT_ID,
                ACTOR_ID,
                AGENT_ID,
                GROUP_ID,
                group,
                List.of(ACTOR_ID),
                historyFloor,
                NOW
        );
    }

    private static com.dianlian.platform.memory.domain.MemoryItem memory(
            UUID memoryId,
            UUID agentId,
            MemoryScopeRef scope,
            MemoryItemStatus status,
            long version
    ) {
        UUID forgottenBy = status == MemoryItemStatus.FORGOTTEN ? ACTOR_ID : null;
        Instant forgottenAt = status == MemoryItemStatus.FORGOTTEN ? NOW : null;
        return new com.dianlian.platform.memory.domain.MemoryItem(
                memoryId, TENANT_ID, agentId, scope, status, version, "不应返回的正文", null,
                ACTOR_ID, NOW.minusSeconds(10), NOW, forgottenBy, forgottenAt,
                status == MemoryItemStatus.FORGOTTEN ? "遗忘" : null,
                status == MemoryItemStatus.FORGOTTEN ? "forget-hash" : null,
                status == MemoryItemStatus.FORGOTTEN ? "forget-key" : null
        );
    }

    private static ProposeMemoryCandidateCommand propose(
            MemoryScopeRef scope,
            String content,
            String idempotencyKey,
            String requestHash
    ) {
        return new ProposeMemoryCandidateCommand(
                AGENT_ID, scope, content, "preference", null, null, idempotencyKey, requestHash
        );
    }

    private static RecallConfirmedMemoryQuery recall(MemoryScopeRef scope, String query) {
        return new RecallConfirmedMemoryQuery(AGENT_ID, List.of(scope), query, 10);
    }

    private static UUID uuid(long value) {
        return new UUID(0, value);
    }
}

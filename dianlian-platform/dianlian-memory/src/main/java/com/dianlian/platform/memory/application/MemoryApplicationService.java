package com.dianlian.platform.memory.application;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.memory.api.ConfirmMemoryCandidateCommand;
import com.dianlian.platform.memory.api.ConfirmedMemory;
import com.dianlian.platform.memory.api.CorrectMemoryCommand;
import com.dianlian.platform.memory.api.ForgetMemoryCommand;
import com.dianlian.platform.memory.api.GroupMembershipUnavailableException;
import com.dianlian.platform.memory.api.GroupMembershipVerifier;
import com.dianlian.platform.memory.api.InvocationMemoryAuthoritySource;
import com.dianlian.platform.memory.api.InvocationMemoryBoundaryVerifier;
import com.dianlian.platform.memory.api.MemoryAccessDeniedException;
import com.dianlian.platform.memory.api.MemoryCandidateSnapshot;
import com.dianlian.platform.memory.api.MemoryCandidateStatus;
import com.dianlian.platform.memory.api.MemoryCommandConflictException;
import com.dianlian.platform.memory.api.MemoryCommandOutcome;
import com.dianlian.platform.memory.api.MemoryCommands;
import com.dianlian.platform.memory.api.MemoryItemStatus;
import com.dianlian.platform.memory.api.MemoryPermissions;
import com.dianlian.platform.memory.api.MemoryQuery;
import com.dianlian.platform.memory.api.MemoryResourceNotDiscoverableException;
import com.dianlian.platform.memory.api.MemoryScopeRef;
import com.dianlian.platform.memory.api.MemoryScopeType;
import com.dianlian.platform.memory.api.ProposeMemoryCandidateCommand;
import com.dianlian.platform.memory.api.RecallConfirmedMemoryQuery;
import com.dianlian.platform.memory.api.RejectMemoryCandidateCommand;
import com.dianlian.platform.memory.domain.MemoryCandidate;
import com.dianlian.platform.memory.domain.MemoryEvent;
import com.dianlian.platform.memory.domain.MemoryEventType;
import com.dianlian.platform.memory.domain.MemoryItem;
import com.dianlian.platform.memory.domain.MemoryVersion;
import com.dianlian.platform.memory.domain.MemoryVersionChangeType;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import java.util.Objects;
import java.util.UUID;
import java.util.function.Supplier;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class MemoryApplicationService implements MemoryCommands, MemoryQuery, InvocationMemoryAuthoritySource {

    private final MemoryRepository repository;
    private final List<GroupMembershipVerifier> groupMembershipVerifiers;
    private final List<InvocationMemoryBoundaryVerifier> invocationBoundaryVerifiers;
    private final Clock clock;
    private final Supplier<UUID> idGenerator;

    @Autowired
    public MemoryApplicationService(
            MemoryRepository repository,
            ObjectProvider<GroupMembershipVerifier> groupMembershipVerifiers,
            ObjectProvider<InvocationMemoryBoundaryVerifier> invocationBoundaryVerifiers
    ) {
        this(
                repository,
                groupMembershipVerifiers.orderedStream().toList(),
                invocationBoundaryVerifiers.orderedStream().toList(),
                Clock.systemUTC(),
                UUID::randomUUID
        );
    }

    MemoryApplicationService(
            MemoryRepository repository,
            List<GroupMembershipVerifier> groupMembershipVerifiers,
            List<InvocationMemoryBoundaryVerifier> invocationBoundaryVerifiers,
            Clock clock,
            Supplier<UUID> idGenerator
    ) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
        this.groupMembershipVerifiers = List.copyOf(Objects.requireNonNull(
                groupMembershipVerifiers,
                "groupMembershipVerifiers must not be null"
        ));
        this.invocationBoundaryVerifiers = List.copyOf(Objects.requireNonNull(
                invocationBoundaryVerifiers,
                "invocationBoundaryVerifiers must not be null"
        ));
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
        this.idGenerator = Objects.requireNonNull(idGenerator, "idGenerator must not be null");
    }

    @Override
    @Transactional
    public MemoryCommandOutcome<MemoryCandidateSnapshot> propose(
            ProposeMemoryCandidateCommand command,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePermission(accessContext, MemoryPermissions.CANDIDATE_PROPOSE);
        requireScopeIdentity(command.scope(), accessContext);
        UUID tenantId = accessContext.tenantId().value();
        UUID actorId = accessContext.actorId().value();

        var replay = repository.findCandidateByProposeIdempotency(tenantId, actorId, command.idempotencyKey());
        if (replay.isPresent()) {
            requireSameCandidateIntent(replay.get(), command.enterpriseAgentId(), command.scope(), command.requestHash());
            return new MemoryCommandOutcome<>(replay.get().toSnapshot(), true);
        }

        Instant now = clock.instant();
        var candidate = new MemoryCandidate(
                idGenerator.get(), tenantId, command.enterpriseAgentId(), command.scope(), command.content(),
                command.semanticKey(), command.sourceConversationId(), command.sourceMessageId(),
                MemoryCandidateStatus.PENDING, command.requestHash(), command.idempotencyKey(), actorId, now,
                null, null, null, null, null, null
        );
        if (!repository.insertCandidateIfAbsent(candidate)) {
            var concurrentReplay = repository.findCandidateByProposeIdempotency(
                    tenantId,
                    actorId,
                    command.idempotencyKey()
            ).orElseThrow(() -> concurrentConflict("MEMORY_CANDIDATE_CONCURRENT_CONFLICT"));
            requireSameCandidateIntent(
                    concurrentReplay,
                    command.enterpriseAgentId(),
                    command.scope(),
                    command.requestHash()
            );
            return new MemoryCommandOutcome<>(concurrentReplay.toSnapshot(), true);
        }
        repository.insertEvent(event(
                candidate, MemoryEventType.CANDIDATE_PROPOSED, null, null,
                null, MemoryCandidateStatus.PENDING.name(), null,
                command.requestHash(), command.idempotencyKey(), actorId, now
        ));
        return new MemoryCommandOutcome<>(candidate.toSnapshot(), false);
    }

    @Override
    @Transactional
    public MemoryCommandOutcome<MemoryCandidateSnapshot> confirm(
            ConfirmMemoryCandidateCommand command,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        UUID tenantId = accessContext.tenantId().value();
        UUID actorId = accessContext.actorId().value();
        var replay = repository.findCandidateByDecisionIdempotency(tenantId, actorId, command.idempotencyKey());
        if (replay.isPresent()) {
            requireDecisionReplay(replay.get(), command.candidateId(), MemoryCandidateStatus.CONFIRMED, command.requestHash());
            requireManageScope(replay.get().scope(), accessContext);
            return new MemoryCommandOutcome<>(replay.get().toSnapshot(), true);
        }

        var candidate = repository.lockCandidate(tenantId, command.candidateId())
                .orElseThrow(MemoryResourceNotDiscoverableException::new);
        requireManageScope(candidate.scope(), accessContext);
        requirePending(candidate);
        Instant now = clock.instant();
        UUID memoryId = idGenerator.get();
        var memory = activeMemory(candidate, memoryId, actorId, now);
        repository.insertMemory(memory);
        repository.insertVersion(new MemoryVersion(
                memoryId, tenantId, 1, candidate.content(), candidate.semanticKey(), candidate.candidateId(),
                MemoryVersionChangeType.CONFIRMED, command.reason(), command.requestHash(),
                command.idempotencyKey(), actorId, now
        ));
        if (!repository.markCandidateConfirmed(
                tenantId, candidate.candidateId(), memoryId, actorId, now, command.reason(),
                command.requestHash(), command.idempotencyKey()
        )) {
            throw concurrentConflict("MEMORY_CANDIDATE_DECISION_CONFLICT");
        }
        long eventSequence = repository.insertEvent(event(
                candidate, MemoryEventType.CANDIDATE_CONFIRMED, memoryId, 1L,
                MemoryCandidateStatus.PENDING.name(), MemoryCandidateStatus.CONFIRMED.name(), command.reason(),
                command.requestHash(), command.idempotencyKey(), actorId, now
        ));
        insertIndexJobs(
                tenantId,
                memoryId,
                1,
                eventSequence,
                MemoryIndexJobWrite.Operation.UPSERT,
                now
        );
        return new MemoryCommandOutcome<>(decided(candidate, MemoryCandidateStatus.CONFIRMED, actorId, now,
                command.reason(), command.requestHash(), command.idempotencyKey(), memoryId).toSnapshot(), false);
    }

    @Override
    @Transactional
    public MemoryCommandOutcome<MemoryCandidateSnapshot> reject(
            RejectMemoryCandidateCommand command,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        UUID tenantId = accessContext.tenantId().value();
        UUID actorId = accessContext.actorId().value();
        var replay = repository.findCandidateByDecisionIdempotency(tenantId, actorId, command.idempotencyKey());
        if (replay.isPresent()) {
            requireDecisionReplay(replay.get(), command.candidateId(), MemoryCandidateStatus.REJECTED, command.requestHash());
            requireManageScope(replay.get().scope(), accessContext);
            return new MemoryCommandOutcome<>(replay.get().toSnapshot(), true);
        }
        var candidate = repository.lockCandidate(tenantId, command.candidateId())
                .orElseThrow(MemoryResourceNotDiscoverableException::new);
        requireManageScope(candidate.scope(), accessContext);
        requirePending(candidate);
        Instant now = clock.instant();
        if (!repository.markCandidateRejected(
                tenantId, candidate.candidateId(), actorId, now, command.reason(),
                command.requestHash(), command.idempotencyKey()
        )) {
            throw concurrentConflict("MEMORY_CANDIDATE_DECISION_CONFLICT");
        }
        repository.insertEvent(event(
                candidate, MemoryEventType.CANDIDATE_REJECTED, null, null,
                MemoryCandidateStatus.PENDING.name(), MemoryCandidateStatus.REJECTED.name(), command.reason(),
                command.requestHash(), command.idempotencyKey(), actorId, now
        ));
        return new MemoryCommandOutcome<>(decided(candidate, MemoryCandidateStatus.REJECTED, actorId, now,
                command.reason(), command.requestHash(), command.idempotencyKey(), null).toSnapshot(), false);
    }

    @Override
    @Transactional
    public MemoryCommandOutcome<ConfirmedMemory> correct(CorrectMemoryCommand command, AccessContext accessContext) {
        Objects.requireNonNull(command, "command must not be null");
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        UUID tenantId = accessContext.tenantId().value();
        UUID actorId = accessContext.actorId().value();
        var replay = repository.findCorrectionByIdempotency(tenantId, actorId, command.idempotencyKey());
        if (replay.isPresent()) {
            requireSameMemoryIntent(replay.get().memoryId(), command.memoryId(), replay.get().requestHash(), command.requestHash());
            var memory = repository.findMemory(tenantId, command.memoryId())
                    .orElseThrow(MemoryResourceNotDiscoverableException::new);
            requireManageScope(memory.scope(), accessContext);
            return new MemoryCommandOutcome<>(memory.toView(), true);
        }
        var current = repository.lockMemory(tenantId, command.memoryId())
                .orElseThrow(MemoryResourceNotDiscoverableException::new);
        requireManageScope(current.scope(), accessContext);
        requireActive(current);
        Instant now = clock.instant();
        long nextVersion = Math.addExact(current.currentVersion(), 1);
        repository.insertVersion(new MemoryVersion(
                current.memoryId(), tenantId, nextVersion, command.correctedContent(), command.semanticKey(), null,
                MemoryVersionChangeType.CORRECTED, command.reason(), command.requestHash(),
                command.idempotencyKey(), actorId, now
        ));
        if (!repository.advanceMemoryVersion(
                tenantId, current.memoryId(), current.currentVersion(), command.correctedContent(),
                command.semanticKey(), now
        )) {
            throw concurrentConflict("MEMORY_VERSION_CONFLICT");
        }
        long eventSequence = repository.insertEvent(event(
                current, MemoryEventType.MEMORY_CORRECTED, nextVersion,
                MemoryItemStatus.ACTIVE.name(), MemoryItemStatus.ACTIVE.name(), command.reason(),
                command.requestHash(), command.idempotencyKey(), actorId, now
        ));
        insertIndexJobs(
                tenantId,
                current.memoryId(),
                nextVersion,
                eventSequence,
                MemoryIndexJobWrite.Operation.UPSERT,
                now
        );
        return new MemoryCommandOutcome<>(updatedMemory(current, nextVersion, command.correctedContent(),
                command.semanticKey(), now).toView(), false);
    }

    @Override
    @Transactional
    public MemoryCommandOutcome<ConfirmedMemory> forget(ForgetMemoryCommand command, AccessContext accessContext) {
        Objects.requireNonNull(command, "command must not be null");
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        UUID tenantId = accessContext.tenantId().value();
        UUID actorId = accessContext.actorId().value();
        var replay = repository.findForgetByIdempotency(tenantId, actorId, command.idempotencyKey());
        if (replay.isPresent()) {
            requireSameMemoryIntent(replay.get().memoryId(), command.memoryId(),
                    replay.get().forgetRequestHash(), command.requestHash());
            requireManageScope(replay.get().scope(), accessContext);
            return new MemoryCommandOutcome<>(replay.get().toView(), true);
        }
        var current = repository.lockMemory(tenantId, command.memoryId())
                .orElseThrow(MemoryResourceNotDiscoverableException::new);
        requireManageScope(current.scope(), accessContext);
        requireActive(current);
        Instant now = clock.instant();
        if (!repository.forgetMemory(
                tenantId, current.memoryId(), current.currentVersion(), actorId, now, command.reason(),
                command.requestHash(), command.idempotencyKey()
        )) {
            throw concurrentConflict("MEMORY_FORGET_CONFLICT");
        }
        long eventSequence = repository.insertEvent(event(
                current, MemoryEventType.MEMORY_FORGOTTEN, current.currentVersion(),
                MemoryItemStatus.ACTIVE.name(), MemoryItemStatus.FORGOTTEN.name(), command.reason(),
                command.requestHash(), command.idempotencyKey(), actorId, now
        ));
        insertIndexJobs(
                tenantId,
                current.memoryId(),
                current.currentVersion(),
                eventSequence,
                MemoryIndexJobWrite.Operation.DELETE,
                now
        );
        return new MemoryCommandOutcome<>(forgottenMemory(current, actorId, now, command).toView(), false);
    }

    @Override
    @Transactional(readOnly = true)
    public List<ConfirmedMemory> recallConfirmed(RecallConfirmedMemoryQuery query, AccessContext accessContext) {
        Objects.requireNonNull(query, "query must not be null");
        requirePermission(accessContext, MemoryPermissions.RECALL);
        query.scopes().forEach(scope -> requireScopeIdentity(scope, accessContext));
        return repository.recallConfirmed(
                accessContext.tenantId().value(), query.enterpriseAgentId(), query.scopes(), query.query(), query.limit()
        ).stream().map(MemoryItem::toView).toList();
    }

    @Override
    @Transactional(readOnly = true)
    public AuthorizeScopesResult authorizeScopes(AuthorizeScopesQuery query) {
        Objects.requireNonNull(query, "query must not be null");
        RejectionCode boundaryRejection = invocationBoundaryRejection(query);
        if (boundaryRejection != null) {
            return AuthorizeScopesResult.denied(boundaryRejection);
        }
        var scopes = List.of(
                new AuthorizedMemoryScope(
                        query.tenantId(), MemoryScopeType.AGENT, query.enterpriseAgentId(),
                        query.enterpriseAgentId(), 0
                ),
                new AuthorizedMemoryScope(
                        query.tenantId(),
                        query.groupConversation() ? MemoryScopeType.GROUP_AGENT : MemoryScopeType.USER_AGENT,
                        query.groupConversation() ? query.conversationId() : query.actorUserId(),
                        query.enterpriseAgentId(),
                        query.groupConversation() ? query.historyFloorSequenceNo() : 0
                )
        );
        return AuthorizeScopesResult.allowed(scopes);
    }

    @Override
    @Transactional(readOnly = true)
    public ReauthorizationResult reauthorize(ReauthorizeQuery query) {
        Objects.requireNonNull(query, "query must not be null");
        var scopeResult = authorizeScopes(query.invocation());
        if (!scopeResult.authorized()) {
            return new ReauthorizationResult(false, scopeResult.rejectionCode(), List.of(), List.of());
        }
        Map<MemoryEvidenceKey, MemoryRepository.MemoryAuthoritySnapshot> snapshots = new HashMap<>();
        for (var snapshot : repository.findAuthoritySnapshots(
                query.invocation().tenantId(), query.evidenceKeys())) {
            snapshots.put(snapshot.key(), snapshot);
        }
        Set<MemoryScopeRef> allowedScopes = scopeResult.scopes().stream()
                .map(scope -> new MemoryScopeRef(scope.scopeType(), scope.scopeId()))
                .collect(java.util.stream.Collectors.toUnmodifiableSet());
        var allowed = new ArrayList<AuthorizedMemoryEvidence>();
        var rejected = new ArrayList<RejectedMemoryEvidence>();
        for (MemoryEvidenceKey key : query.evidenceKeys()) {
            var snapshot = snapshots.get(key);
            RejectionCode rejection = rejectionFor(query.invocation(), key, snapshot, allowedScopes);
            if (rejection == RejectionCode.GROUP_PRIVATE_SCOPE_CONTRACT_VIOLATION) {
                return new ReauthorizationResult(false, rejection, List.of(), List.of());
            }
            if (rejection == null) {
                allowed.add(new AuthorizedMemoryEvidence(key, snapshot.scope()));
            } else {
                rejected.add(new RejectedMemoryEvidence(key, rejection));
            }
        }
        return new ReauthorizationResult(true, null, allowed, rejected);
    }

    private RejectionCode invocationBoundaryRejection(AuthorizeScopesQuery query) {
        if (invocationBoundaryVerifiers.size() != 1) {
            return RejectionCode.AUTHORITY_BOUNDARY_UNAVAILABLE;
        }
        try {
            return invocationBoundaryVerifiers.getFirst().isAuthorized(query)
                    ? null
                    : RejectionCode.INVOCATION_BOUNDARY_DENIED;
        } catch (RuntimeException exception) {
            return RejectionCode.AUTHORITY_BOUNDARY_UNAVAILABLE;
        }
    }

    private static RejectionCode rejectionFor(
            AuthorizeScopesQuery invocation,
            MemoryEvidenceKey key,
            MemoryRepository.MemoryAuthoritySnapshot snapshot,
            Set<MemoryScopeRef> allowedScopes
    ) {
        if (snapshot == null) return RejectionCode.MEMORY_NOT_FOUND;
        if (invocation.groupConversation() && snapshot.scope().scopeType() == MemoryScopeType.USER_AGENT) {
            return RejectionCode.GROUP_PRIVATE_SCOPE_CONTRACT_VIOLATION;
        }
        if (snapshot.status() != MemoryItemStatus.ACTIVE) return RejectionCode.MEMORY_NOT_ACTIVE;
        if (snapshot.currentVersion() != key.versionNo()) return RejectionCode.MEMORY_VERSION_NOT_CURRENT;
        if (!snapshot.enterpriseAgentId().equals(invocation.enterpriseAgentId())) {
            return RejectionCode.MEMORY_AGENT_MISMATCH;
        }
        if (!allowedScopes.contains(snapshot.scope())) return RejectionCode.MEMORY_SCOPE_NOT_ALLOWED;
        if (snapshot.scope().scopeType() == MemoryScopeType.GROUP_AGENT) {
            if (snapshot.sourceMessageSequenceNo() == null) {
                return RejectionCode.GROUP_MEMORY_SOURCE_SEQUENCE_MISSING;
            }
            if (snapshot.sourceMessageSequenceNo() < invocation.historyFloorSequenceNo()) {
                return RejectionCode.GROUP_MEMORY_BEFORE_HISTORY_FLOOR;
            }
        }
        return null;
    }

    private void requireManageScope(MemoryScopeRef scope, AccessContext accessContext) {
        requireScopeIdentity(scope, accessContext);
        switch (scope.scopeType()) {
            case AGENT -> requirePermission(accessContext, MemoryPermissions.AGENT_GOVERN);
            case USER_AGENT -> requirePermission(accessContext, MemoryPermissions.SELF_MANAGE);
            case GROUP_AGENT -> requirePermission(accessContext, MemoryPermissions.GROUP_MANAGE);
        }
    }

    private void requireScopeIdentity(MemoryScopeRef scope, AccessContext accessContext) {
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        UUID actorId = accessContext.actorId().value();
        switch (scope.scopeType()) {
            case AGENT -> { }
            case USER_AGENT -> {
                if (!scope.scopeId().equals(actorId)) {
                    throw new MemoryAccessDeniedException(MemoryPermissions.SELF_MANAGE);
                }
            }
            case GROUP_AGENT -> requireActiveGroupMember(
                    accessContext.tenantId().value(), scope.scopeId(), actorId
            );
        }
    }

    private void requireActiveGroupMember(UUID tenantId, UUID groupId, UUID actorId) {
        if (groupMembershipVerifiers.size() != 1) {
            throw new GroupMembershipUnavailableException();
        }
        if (!groupMembershipVerifiers.getFirst().isActiveMember(tenantId, groupId, actorId)) {
            throw new MemoryAccessDeniedException("active-group-membership");
        }
    }

    private static void requirePermission(AccessContext accessContext, String permission) {
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        if (!accessContext.authorities().contains(permission)) {
            throw new MemoryAccessDeniedException(permission);
        }
    }

    private static void requirePending(MemoryCandidate candidate) {
        if (candidate.status() != MemoryCandidateStatus.PENDING) {
            throw new MemoryCommandConflictException(
                    "MEMORY_CANDIDATE_ALREADY_DECIDED",
                    "memory candidate is already decided"
            );
        }
    }

    private static void requireActive(MemoryItem memory) {
        if (memory.status() != MemoryItemStatus.ACTIVE) {
            throw new MemoryCommandConflictException("MEMORY_ALREADY_FORGOTTEN", "forgotten memory cannot be changed");
        }
    }

    private static void requireSameCandidateIntent(
            MemoryCandidate stored,
            UUID enterpriseAgentId,
            MemoryScopeRef scope,
            String requestHash
    ) {
        if (!stored.enterpriseAgentId().equals(enterpriseAgentId)
                || !stored.scope().equals(scope)
                || !stored.requestHash().equals(requestHash)) {
            throw idempotencyConflict();
        }
    }

    private static void requireDecisionReplay(
            MemoryCandidate stored,
            UUID candidateId,
            MemoryCandidateStatus status,
            String requestHash
    ) {
        if (!stored.candidateId().equals(candidateId)
                || stored.status() != status
                || !Objects.equals(stored.decisionRequestHash(), requestHash)) {
            throw idempotencyConflict();
        }
    }

    private static void requireSameMemoryIntent(
            UUID storedMemoryId,
            UUID incomingMemoryId,
            String storedRequestHash,
            String incomingRequestHash
    ) {
        if (!storedMemoryId.equals(incomingMemoryId) || !Objects.equals(storedRequestHash, incomingRequestHash)) {
            throw idempotencyConflict();
        }
    }

    private static MemoryCommandConflictException idempotencyConflict() {
        return new MemoryCommandConflictException(
                "IDEMPOTENCY_REQUEST_CONFLICT",
                "the idempotency key was already used with a different memory command"
        );
    }

    private static MemoryCommandConflictException concurrentConflict(String code) {
        return new MemoryCommandConflictException(code, "another memory write won the concurrent request");
    }

    private void insertIndexJobs(
            UUID tenantId,
            UUID memoryId,
            long memoryVersion,
            long eventSequence,
            MemoryIndexJobWrite.Operation operation,
            Instant occurredAt
    ) {
        for (MemoryIndexJobWrite.IndexTarget indexTarget : MemoryIndexJobWrite.IndexTarget.values()) {
            repository.insertIndexJob(new MemoryIndexJobWrite(
                    idGenerator.get(),
                    tenantId,
                    memoryId,
                    memoryVersion,
                    eventSequence,
                    indexTarget,
                    operation,
                    occurredAt
            ));
        }
    }

    private static MemoryItem activeMemory(MemoryCandidate candidate, UUID memoryId, UUID actorId, Instant now) {
        return new MemoryItem(
                memoryId, candidate.tenantId(), candidate.enterpriseAgentId(), candidate.scope(),
                MemoryItemStatus.ACTIVE, 1, candidate.content(), candidate.semanticKey(), actorId, now, now,
                null, null, null, null, null
        );
    }

    private static MemoryCandidate decided(
            MemoryCandidate candidate,
            MemoryCandidateStatus status,
            UUID actorId,
            Instant now,
            String reason,
            String requestHash,
            String idempotencyKey,
            UUID memoryId
    ) {
        return new MemoryCandidate(
                candidate.candidateId(), candidate.tenantId(), candidate.enterpriseAgentId(), candidate.scope(),
                candidate.content(), candidate.semanticKey(), candidate.sourceConversationId(), candidate.sourceMessageId(),
                status, candidate.requestHash(), candidate.idempotencyKey(), candidate.proposedBy(), candidate.proposedAt(),
                actorId, now, reason, requestHash, idempotencyKey, memoryId
        );
    }

    private static MemoryItem updatedMemory(
            MemoryItem current,
            long version,
            String content,
            String semanticKey,
            Instant now
    ) {
        return new MemoryItem(
                current.memoryId(), current.tenantId(), current.enterpriseAgentId(), current.scope(),
                MemoryItemStatus.ACTIVE, version, content, semanticKey, current.createdBy(), current.createdAt(), now,
                null, null, null, null, null
        );
    }

    private static MemoryItem forgottenMemory(
            MemoryItem current,
            UUID actorId,
            Instant now,
            ForgetMemoryCommand command
    ) {
        return new MemoryItem(
                current.memoryId(), current.tenantId(), current.enterpriseAgentId(), current.scope(),
                MemoryItemStatus.FORGOTTEN, current.currentVersion(), current.content(), current.semanticKey(),
                current.createdBy(), current.createdAt(), now, actorId, now, command.reason(), command.requestHash(),
                command.idempotencyKey()
        );
    }

    private MemoryEvent event(
            MemoryCandidate candidate,
            MemoryEventType eventType,
            UUID memoryId,
            Long resultingVersion,
            String fromStatus,
            String toStatus,
            String reason,
            String requestHash,
            String idempotencyKey,
            UUID actorId,
            Instant now
    ) {
        return new MemoryEvent(
                idGenerator.get(), candidate.tenantId(), candidate.enterpriseAgentId(), candidate.scope(), eventType,
                candidate.candidateId(), memoryId, resultingVersion, fromStatus, toStatus, reason, requestHash,
                idempotencyKey, actorId, now
        );
    }

    private MemoryEvent event(
            MemoryItem memory,
            MemoryEventType eventType,
            long resultingVersion,
            String fromStatus,
            String toStatus,
            String reason,
            String requestHash,
            String idempotencyKey,
            UUID actorId,
            Instant now
    ) {
        return new MemoryEvent(
                idGenerator.get(), memory.tenantId(), memory.enterpriseAgentId(), memory.scope(), eventType,
                null, memory.memoryId(), resultingVersion, fromStatus, toStatus, reason, requestHash,
                idempotencyKey, actorId, now
        );
    }
}

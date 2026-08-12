package com.dianlian.platform.integration.infrastructure.context;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScope;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScopeType;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AuthorizedKnowledgeResource;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource;
import com.dianlian.platform.context.api.ContextAuthorityPort;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeAuthorizationQuery;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeAuthoritySource;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeEvidenceRef;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeReauthorizationQuery;
import com.dianlian.platform.memory.api.InvocationMemoryAuthoritySource;
import com.dianlian.platform.memory.api.InvocationMemoryAuthoritySource.AuthorizeScopesQuery;
import com.dianlian.platform.memory.api.InvocationMemoryAuthoritySource.MemoryEvidenceKey;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import org.springframework.stereotype.Component;

@Component
final class AuthoritativeContextAuthorityAdapter implements ContextAuthorityPort {

    private final InvocationKnowledgeAuthoritySource knowledgeAuthority;
    private final InvocationMemoryAuthoritySource memoryAuthority;

    AuthoritativeContextAuthorityAdapter(
            InvocationKnowledgeAuthoritySource knowledgeAuthority,
            InvocationMemoryAuthoritySource memoryAuthority
    ) {
        this.knowledgeAuthority = Objects.requireNonNull(knowledgeAuthority);
        this.memoryAuthority = Objects.requireNonNull(memoryAuthority);
    }

    @Override
    public Authorization authorize(AuthorizationRequest request) {
        Objects.requireNonNull(request, "request must not be null");
        var invocation = request.invocation();
        var knowledge = request.knowledgeEnabled()
                ? knowledgeAuthority.authorize(new InvocationKnowledgeAuthorizationQuery(
                        invocation.tenantId(), invocation.actorUserId(), invocation.agentVersionId(),
                        invocation.enterpriseAgentId(), invocation.configurationVersionId(),
                        invocation.audienceUserIds(), invocation.observedAt(), request.knowledgeLimit()
                )).stream().map(resource -> new AuthorizedKnowledgeResource(
                        resource.tenantId(), resource.resourceId(), resource.resourceVersionId()
                )).toList()
                : List.<AuthorizedKnowledgeResource>of();
        var memory = request.memoryEnabled()
                ? memoryAuthority.authorizeScopes(memoryQuery(invocation))
                : null;
        if (memory != null && !memory.authorized()) {
            return new Authorization(false, memory.rejectionCode().name(), List.of(), List.of());
        }
        var scopes = memory == null ? List.<AllowedMemoryScope>of() : memory.scopes().stream()
                .map(scope -> new AllowedMemoryScope(
                        scope.tenantId(), AllowedMemoryScopeType.valueOf(scope.scopeType().name()),
                        scope.scopeId(), scope.enterpriseAgentId(), scope.historyFloorSequenceNo()
                )).toList();
        validateScopeContract(invocation, scopes);
        return new Authorization(true, null, knowledge, scopes);
    }

    @Override
    public Reauthorization reauthorize(ReauthorizationRequest request) {
        Objects.requireNonNull(request, "request must not be null");
        var invocation = request.invocation();
        var knowledgeEvidence = request.actualEvidence().stream()
                .filter(evidence -> evidence.sourceType() == RequestedSource.KNOWLEDGE)
                .toList();
        var memoryEvidence = request.actualEvidence().stream()
                .filter(evidence -> evidence.sourceType() == RequestedSource.MEMORY)
                .toList();
        var allowedIds = new java.util.HashSet<String>();
        var rejections = new ArrayList<EvidenceRejection>();

        if (!knowledgeEvidence.isEmpty()) {
            var evidenceByKey = mapKnowledgeEvidence(knowledgeEvidence);
            var result = knowledgeAuthority.reauthorize(new InvocationKnowledgeReauthorizationQuery(
                    invocation.tenantId(), invocation.actorUserId(), invocation.agentVersionId(),
                    invocation.enterpriseAgentId(), invocation.configurationVersionId(),
                    invocation.audienceUserIds(), invocation.observedAt(), 2_000,
                    List.copyOf(evidenceByKey.keySet())
            ));
            result.allowed().forEach(ref -> {
                var evidence = evidenceByKey.get(new InvocationKnowledgeEvidenceRef(
                        ref.resourceId(), ref.resourceVersionId()));
                if (evidence != null) allowedIds.add(evidence.evidenceId());
            });
            result.rejected().forEach(rejected -> {
                var evidence = evidenceByKey.get(rejected.evidence());
                if (evidence != null) rejections.add(new EvidenceRejection(
                        evidence.evidenceId(), rejected.reason().name()));
            });
        }

        if (!memoryEvidence.isEmpty()) {
            var evidenceByKey = mapMemoryEvidence(memoryEvidence);
            var result = memoryAuthority.reauthorize(new InvocationMemoryAuthoritySource.ReauthorizeQuery(
                    memoryQuery(invocation), List.copyOf(evidenceByKey.keySet())
            ));
            if (!result.contractAccepted()) {
                return new Reauthorization(false, result.contractRejectionCode().name(), List.of(), List.of());
            }
            result.allowed().forEach(allowed -> {
                var evidence = evidenceByKey.get(allowed.key());
                if (evidence != null) allowedIds.add(evidence.evidenceId());
            });
            result.rejected().forEach(rejected -> {
                var evidence = evidenceByKey.get(rejected.key());
                if (evidence != null) rejections.add(new EvidenceRejection(
                        evidence.evidenceId(), rejected.rejectionCode().name()));
            });
        }

        var allowed = request.actualEvidence().stream()
                .filter(evidence -> allowedIds.contains(evidence.evidenceId()))
                .toList();
        rejections.sort(java.util.Comparator.comparing(EvidenceRejection::evidenceId));
        return new Reauthorization(true, null, allowed, rejections);
    }

    private static AuthorizeScopesQuery memoryQuery(InvocationBoundary invocation) {
        return new AuthorizeScopesQuery(
                invocation.tenantId(), invocation.actorUserId(), invocation.enterpriseAgentId(),
                invocation.conversationId(), invocation.groupConversation(), invocation.audienceUserIds(),
                invocation.historyFloorSequenceNo(), invocation.observedAt()
        );
    }

    private static Map<InvocationKnowledgeEvidenceRef, EvidenceIdentity> mapKnowledgeEvidence(
            List<EvidenceIdentity> evidence
    ) {
        var result = new HashMap<InvocationKnowledgeEvidenceRef, EvidenceIdentity>();
        for (var item : evidence) {
            UUID version;
            try {
                version = UUID.fromString(item.sourceVersion());
            } catch (IllegalArgumentException exception) {
                throw new IllegalArgumentException("knowledge sourceVersion must be a UUID", exception);
            }
            result.putIfAbsent(new InvocationKnowledgeEvidenceRef(item.sourceId(), version), item);
        }
        return Map.copyOf(result);
    }

    private static Map<MemoryEvidenceKey, EvidenceIdentity> mapMemoryEvidence(List<EvidenceIdentity> evidence) {
        var result = new HashMap<MemoryEvidenceKey, EvidenceIdentity>();
        for (var item : evidence) {
            long version;
            try {
                version = Long.parseLong(item.sourceVersion());
            } catch (NumberFormatException exception) {
                throw new IllegalArgumentException("memory sourceVersion must be a positive integer", exception);
            }
            result.putIfAbsent(new MemoryEvidenceKey(item.sourceId(), version), item);
        }
        return Map.copyOf(result);
    }

    private static void validateScopeContract(InvocationBoundary invocation, List<AllowedMemoryScope> scopes) {
        if (invocation.groupConversation()
                && scopes.stream().anyMatch(scope -> scope.scopeType() == AllowedMemoryScopeType.USER_AGENT)) {
            throw new IllegalStateException("group invocation cannot authorize private user memory");
        }
        if (!invocation.groupConversation()
                && scopes.stream().anyMatch(scope -> scope.scopeType() == AllowedMemoryScopeType.GROUP_AGENT)) {
            throw new IllegalStateException("direct invocation cannot authorize group memory");
        }
    }
}

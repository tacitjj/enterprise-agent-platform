package com.dianlian.platform.knowledge.application;

import com.dianlian.platform.knowledge.api.AuthorizedKnowledgeResourceRef;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeAuthorizationQuery;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeAuthoritySource;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeEvidenceRef;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeReauthorizationQuery;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeReauthorizationResult;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeRejectionReason;
import com.dianlian.platform.knowledge.api.RejectedInvocationKnowledgeEvidence;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Fresh knowledge authority checks for asynchronous invocations.
 *
 * <p>This service deliberately bypasses interactive menu permissions: its caller supplies the
 * already admitted invocation identity, while the database query independently rechecks current
 * execution identity, resource binding and every audience member's ACL. It does not construct an
 * {@code AccessContext}, write state or cache authority decisions.</p>
 */
@Service
public class InvocationKnowledgeAuthorityService implements InvocationKnowledgeAuthoritySource {

    private final KnowledgeRepository repository;

    public InvocationKnowledgeAuthorityService(KnowledgeRepository repository) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
    }

    @Override
    @Transactional(readOnly = true)
    public List<AuthorizedKnowledgeResourceRef> authorize(
            InvocationKnowledgeAuthorizationQuery query
    ) {
        Objects.requireNonNull(query, "query must not be null");
        List<AuthorizedKnowledgeResourceRef> resolved = List.copyOf(repository.resolveAuthorizedResources(
                new KnowledgeAuthorizationRequest(
                        query.tenantId(),
                        query.agentVersionId(),
                        query.enterpriseAgentId(),
                        query.configurationVersionId(),
                        query.audienceUserIds(),
                        query.limit(),
                        query.observedAt()
                )));
        if (resolved.size() > query.limit()
                || resolved.stream().anyMatch(resource -> !query.tenantId().equals(resource.tenantId()))
                || new HashSet<>(resolved).size() != resolved.size()) {
            throw new IllegalStateException("knowledge authority repository returned an invalid resource set");
        }
        return resolved.stream()
                .sorted(java.util.Comparator.comparing(AuthorizedKnowledgeResourceRef::resourceId)
                        .thenComparing(AuthorizedKnowledgeResourceRef::resourceVersionId))
                .toList();
    }

    @Override
    @Transactional(readOnly = true)
    public InvocationKnowledgeReauthorizationResult reauthorize(
            InvocationKnowledgeReauthorizationQuery query
    ) {
        Objects.requireNonNull(query, "query must not be null");
        List<InvocationKnowledgeEvidenceRef> allowedEvidence = List.copyOf(
                repository.reauthorizeExactEvidence(query)
        );
        Set<InvocationKnowledgeEvidenceRef> requested = Set.copyOf(query.actualEvidence());
        if (allowedEvidence.stream().anyMatch(evidence -> !requested.contains(evidence))
                || new HashSet<>(allowedEvidence).size() != allowedEvidence.size()) {
            throw new IllegalStateException("knowledge authority repository returned an invalid evidence set");
        }
        Set<InvocationKnowledgeEvidenceRef> allowedSet = Set.copyOf(allowedEvidence);
        List<AuthorizedKnowledgeResourceRef> allowed = query.actualEvidence().stream()
                .filter(allowedSet::contains)
                .map(evidence -> new AuthorizedKnowledgeResourceRef(
                        query.tenantId(),
                        evidence.documentId(),
                        evidence.documentVersionId()
                ))
                .toList();
        List<RejectedInvocationKnowledgeEvidence> rejected = query.actualEvidence().stream()
                .filter(evidence -> !allowedSet.contains(evidence))
                .map(evidence -> new RejectedInvocationKnowledgeEvidence(
                        evidence,
                        InvocationKnowledgeRejectionReason.CURRENT_AUTHORITY_DENIED
                ))
                .toList();
        return new InvocationKnowledgeReauthorizationResult(allowed, rejected);
    }
}

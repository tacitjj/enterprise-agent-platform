package com.dianlian.platform.knowledge.application;

import com.dianlian.platform.knowledge.api.AuthorizedKnowledgeResourceRef;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeEvidenceRef;
import com.dianlian.platform.knowledge.api.InvocationKnowledgeReauthorizationQuery;
import com.dianlian.platform.knowledge.domain.KnowledgeBinding;
import com.dianlian.platform.knowledge.domain.KnowledgeDocumentVersion;
import com.dianlian.platform.knowledge.domain.KnowledgeGrant;
import com.dianlian.platform.knowledge.domain.KnowledgeSpace;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface KnowledgeRepository {

    Optional<KnowledgeSpace> findSpace(UUID spaceId);

    Optional<KnowledgeGrant> findGrant(UUID grantId);

    KnowledgeWriteResult<KnowledgeSpace> createSpace(KnowledgeWrites.CreateSpace write);

    KnowledgeWriteResult<KnowledgeDocumentVersion> appendDocumentVersion(
            KnowledgeWrites.AppendDocumentVersion write
    );

    KnowledgeWriteResult<KnowledgeDocumentVersion> completeDocumentNormalization(
            KnowledgeWrites.CompleteDocumentNormalization write
    );

    KnowledgeWriteResult<KnowledgeGrant> grantAudience(KnowledgeWrites.GrantAudience write);

    KnowledgeWriteResult<KnowledgeGrant> revokeAudience(KnowledgeWrites.RevokeAudience write);

    KnowledgeWriteResult<KnowledgeBinding> bindSpace(KnowledgeWrites.BindSpace write);

    List<AuthorizedKnowledgeResourceRef> resolveAuthorizedResources(KnowledgeAuthorizationRequest request);

    List<InvocationKnowledgeEvidenceRef> reauthorizeExactEvidence(
            InvocationKnowledgeReauthorizationQuery query
    );
}

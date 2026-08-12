package com.dianlian.platform.knowledge.api;

import com.dianlian.platform.identity.api.AccessContext;

public interface EnterpriseKnowledgeCommands {

    KnowledgeCommandOutcome<KnowledgeSpaceView> createEnterpriseSpace(
            CreateKnowledgeSpaceCommand command,
            AccessContext accessContext
    );

    KnowledgeCommandOutcome<KnowledgeDocumentVersionView> appendEnterpriseDocumentVersion(
            AppendKnowledgeDocumentVersionCommand command,
            AccessContext accessContext
    );

    KnowledgeCommandOutcome<KnowledgeDocumentVersionView> completeEnterpriseDocumentNormalization(
            CompleteKnowledgeDocumentNormalizationCommand command,
            AccessContext accessContext
    );

    KnowledgeCommandOutcome<KnowledgeGrantView> grantEnterpriseAudience(
            GrantKnowledgeAudienceCommand command,
            AccessContext accessContext
    );

    KnowledgeCommandOutcome<KnowledgeGrantView> revokeEnterpriseAudience(
            RevokeKnowledgeAudienceCommand command,
            AccessContext accessContext
    );

    KnowledgeCommandOutcome<KnowledgeBindingView> bindEnterpriseConfiguration(
            BindEnterpriseKnowledgeSpaceCommand command,
            AccessContext accessContext
    );
}

package com.dianlian.platform.knowledge.api;

import com.dianlian.platform.identity.api.PlatformAccessContext;

public interface PlatformKnowledgeCommands {

    KnowledgeCommandOutcome<KnowledgeSpaceView> createPlatformSpace(
            CreateKnowledgeSpaceCommand command,
            PlatformAccessContext accessContext
    );

    KnowledgeCommandOutcome<KnowledgeDocumentVersionView> appendPlatformDocumentVersion(
            AppendKnowledgeDocumentVersionCommand command,
            PlatformAccessContext accessContext
    );

    KnowledgeCommandOutcome<KnowledgeDocumentVersionView> completePlatformDocumentNormalization(
            CompleteKnowledgeDocumentNormalizationCommand command,
            PlatformAccessContext accessContext
    );

    KnowledgeCommandOutcome<KnowledgeGrantView> grantPlatformAudience(
            GrantKnowledgeAudienceCommand command,
            PlatformAccessContext accessContext
    );

    KnowledgeCommandOutcome<KnowledgeGrantView> revokePlatformAudience(
            RevokeKnowledgeAudienceCommand command,
            PlatformAccessContext accessContext
    );

    KnowledgeCommandOutcome<KnowledgeBindingView> bindPlatformAgentVersion(
            BindPlatformKnowledgeSpaceCommand command,
            PlatformAccessContext accessContext
    );
}

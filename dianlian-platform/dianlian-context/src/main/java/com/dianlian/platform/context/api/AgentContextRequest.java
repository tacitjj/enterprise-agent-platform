package com.dianlian.platform.context.api;

import java.util.List;
import java.util.Objects;
import java.util.UUID;

public record AgentContextRequest(
        UUID tenantId,
        UUID actorUserId,
        UUID enterpriseAgentId,
        UUID conversationId,
        boolean groupConversation,
        UUID agentVersionId,
        UUID configurationVersionId,
        String roleName,
        String platformProfile,
        String enterpriseInstructions,
        String userQuery,
        UUID sourceMessageId,
        long sourceSequenceNo,
        long membershipVersion,
        String policyVersion,
        long historyFloorSequenceNo,
        List<UUID> audienceUserIds,
        List<ContextMessage> recentMessages,
        boolean enterpriseKnowledgeEnabled,
        boolean enterpriseKnowledgeRequired,
        boolean longTermMemoryRequired
) {
    public AgentContextRequest {
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(actorUserId, "actorUserId must not be null");
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        Objects.requireNonNull(conversationId, "conversationId must not be null");
        Objects.requireNonNull(agentVersionId, "agentVersionId must not be null");
        Objects.requireNonNull(configurationVersionId, "configurationVersionId must not be null");
        roleName = requireText(roleName, "roleName", 100);
        platformProfile = requireText(platformProfile, "platformProfile", 2_000);
        enterpriseInstructions = requireText(enterpriseInstructions, "enterpriseInstructions", 20_000);
        userQuery = requireText(userQuery, "userQuery", 20_000);
        Objects.requireNonNull(sourceMessageId, "sourceMessageId must not be null");
        if (sourceSequenceNo <= 0) {
            throw new IllegalArgumentException("sourceSequenceNo must be positive");
        }
        if (membershipVersion <= 0) {
            throw new IllegalArgumentException("membershipVersion must be positive");
        }
        policyVersion = requireText(policyVersion, "policyVersion", 64);
        if (historyFloorSequenceNo < 0) {
            throw new IllegalArgumentException("historyFloorSequenceNo cannot be negative");
        }
        audienceUserIds = List.copyOf(Objects.requireNonNull(audienceUserIds, "audienceUserIds must not be null"));
        recentMessages = List.copyOf(Objects.requireNonNull(recentMessages, "recentMessages must not be null"));
        if (enterpriseKnowledgeRequired && !enterpriseKnowledgeEnabled) {
            throw new IllegalArgumentException("required enterprise knowledge must be enabled");
        }
    }

    /** Compatibility constructor for callers that have not yet persisted the authority watermarks. */
    public AgentContextRequest(
            UUID tenantId,
            UUID actorUserId,
            UUID enterpriseAgentId,
            UUID conversationId,
            boolean groupConversation,
            UUID agentVersionId,
            UUID configurationVersionId,
            String roleName,
            String platformProfile,
            String enterpriseInstructions,
            String userQuery,
            long historyFloorSequenceNo,
            List<UUID> audienceUserIds,
            List<ContextMessage> recentMessages,
            boolean enterpriseKnowledgeEnabled,
            boolean enterpriseKnowledgeRequired,
            boolean longTermMemoryRequired
    ) {
        this(
                tenantId, actorUserId, enterpriseAgentId, conversationId, groupConversation,
                agentVersionId, configurationVersionId, roleName, platformProfile,
                enterpriseInstructions, userQuery, conversationId, 1, 1, "legacy-v1",
                historyFloorSequenceNo, audienceUserIds, recentMessages, enterpriseKnowledgeEnabled,
                enterpriseKnowledgeRequired, longTermMemoryRequired
        );
    }

    private static String requireText(String value, String fieldName, int maxLength) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        var normalized = value.trim();
        if (normalized.isEmpty() || normalized.length() > maxLength) {
            throw new IllegalArgumentException(fieldName + " is invalid");
        }
        return normalized;
    }
}

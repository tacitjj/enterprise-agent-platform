package com.dianlian.platform.interaction.application;

import com.dianlian.platform.interaction.api.ConversationCollaborationMode;
import com.dianlian.platform.interaction.api.ConversationMessagePage;
import com.dianlian.platform.interaction.api.ConversationMessageView;
import com.dianlian.platform.interaction.api.ConversationSummary;
import com.dianlian.platform.interaction.api.ConversationType;
import com.dianlian.platform.interaction.api.MessageTriggerType;
import com.dianlian.platform.model.api.ResolvedModelRoute;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface ConversationRepository {

    Optional<StoredConversationIntent> findConversationIntent(UUID tenantId, UUID actorId, String idempotencyKey);

    void requireActiveTenantMembers(UUID tenantId, List<UUID> userIds);

    ConversationSummary createConversation(CreateConversationWrite write);

    ConversationState lockVisibleConversation(UUID tenantId, UUID actorId, UUID conversationId);

    Optional<StoredMessageIntent> findMessageIntent(
            UUID tenantId,
            UUID actorId,
            UUID conversationId,
            String idempotencyKey
    );

    void requireReplyMessage(UUID tenantId, UUID conversationId, UUID replyToMessageId);

    void requireReplyMessageFromAgent(
            UUID tenantId,
            UUID conversationId,
            UUID replyToMessageId,
            UUID enterpriseAgentId
    );

    ConversationMessageView appendHumanMessage(AppendHumanMessageWrite write);

    UUID appendTarget(AppendTargetWrite write);

    void appendAccessSnapshot(AppendAccessSnapshotWrite write);

    void appendInvocation(AppendInvocationWrite write);

    List<UUID> listInvocationIds(UUID tenantId, UUID sourceMessageId);

    List<ConversationSummary> listVisible(UUID tenantId, UUID actorId, int limit);

    ConversationMessagePage listMessages(
            UUID tenantId,
            UUID actorId,
            UUID conversationId,
            long afterSequenceNo,
            int limit
    );

    record StoredConversationIntent(ConversationSummary summary, String requestHash) {
    }

    record StoredMessageIntent(ConversationMessageView message, String requestHash) {
    }

    record ConversationState(
            UUID conversationId,
            UUID tenantId,
            ConversationType type,
            long membershipVersion,
            long historyFloorSequenceNo,
            List<UUID> humanMemberIds,
            List<UUID> agentIds
    ) {
    }

    record CreateConversationWrite(
            UUID conversationId,
            UUID tenantId,
            UUID actorId,
            ConversationType type,
            String title,
            List<UUID> participantUserIds,
            List<UUID> enterpriseAgentIds,
            String idempotencyKey,
            String requestHash,
            Instant createdAt
    ) {
    }

    record AppendHumanMessageWrite(
            UUID messageId,
            UUID tenantId,
            UUID actorId,
            UUID conversationId,
            String clientMessageId,
            String idempotencyKey,
            String requestHash,
            String text,
            UUID replyToMessageId,
            ConversationCollaborationMode collaborationMode,
            UUID primaryAgentId,
            Instant createdAt
    ) {
    }

    record AppendTargetWrite(
            UUID targetId,
            UUID tenantId,
            UUID conversationId,
            UUID messageId,
            UUID enterpriseAgentId,
            MessageTriggerType triggerType,
            UUID replyToMessageId,
            Instant createdAt
    ) {
    }

    record AppendAccessSnapshotWrite(
            UUID messageId,
            UUID tenantId,
            UUID conversationId,
            long membershipVersion,
            long historyFloorSequenceNo,
            List<UUID> audienceUserIds,
            List<UUID> allowedAgentIds,
            String knowledgeScopeVersion,
            String policyVersion,
            Instant createdAt
    ) {
    }

    record AppendInvocationWrite(
            UUID invocationId,
            UUID tenantId,
            UUID conversationId,
            UUID sourceMessageId,
            UUID messageTargetId,
            UUID requestedBy,
            UUID enterpriseAgentId,
            UUID agentVersionId,
            UUID configurationVersionId,
            String roleName,
            String platformProfile,
            String enterpriseInstructions,
            String knowledgeScopeMode,
            ResolvedModelRoute route,
            UUID pointReservationId,
            Instant createdAt
    ) {
    }
}

package com.dianlian.platform.interaction.application;

import com.dianlian.platform.context.api.ContextMessage;
import com.dianlian.platform.model.api.ModelChatResponse;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface AiInvocationRepository {

    Optional<ClaimedInvocation> claimNext(String workerId, Instant now, Instant leaseUntil);

    List<ContextMessage> recentMessages(ClaimedInvocation invocation, int limit);

    UUID saveContext(ClaimedInvocation invocation, InvocationContextSnapshot snapshot);

    Optional<InvocationContextAuthoritySnapshot> loadContextAuthority(ClaimedInvocation invocation);

    void scheduleContextRetry(ClaimedInvocation invocation, String errorCode, Instant retryAt, Instant now);

    boolean lockPreModelAccessCurrent(ClaimedInvocation invocation, Instant now);

    ClaimedInvocation recordProviderResponse(
            ClaimedInvocation invocation,
            ModelChatResponse response,
            Instant startedAt,
            Instant completedAt
    );

    void recordProviderFailure(
            ClaimedInvocation invocation,
            String errorCode,
            Instant startedAt,
            Instant completedAt
    );

    void markContextBlocked(ClaimedInvocation invocation, String errorCode, Instant now);

    boolean lockPublishAccessCurrent(ClaimedInvocation invocation, Instant now);

    void markAccessBlocked(ClaimedInvocation invocation, String errorCode, Instant now);

    void publishResponse(ClaimedInvocation invocation, long capturedMicroCredit, Instant now);

    record ClaimedInvocation(
            UUID invocationId,
            UUID tenantId,
            UUID conversationId,
            boolean groupConversation,
            UUID sourceMessageId,
            long sourceSequenceNo,
            long membershipVersion,
            String policyVersion,
            long historyFloorSequenceNo,
            String userQuery,
            UUID requestedBy,
            UUID enterpriseAgentId,
            UUID agentVersionId,
            UUID configurationVersionId,
            String roleName,
            String platformProfile,
            String enterpriseInstructions,
            String knowledgeScopeMode,
            UUID modelRouteBindingId,
            UUID modelDefinitionId,
            UUID pointReservationId,
            List<UUID> audienceUserIds,
            boolean accessStillCurrent,
            String status,
            int attemptNo,
            long leaseEpoch,
            String leaseOwner,
            String providerResponseText,
            int inputTokens,
            int outputTokens,
            boolean usageConfirmed,
            String providerRequestId
    ) {
        public boolean responseReady() {
            return "RESPONSE_RECEIVED".equals(status);
        }
    }
}

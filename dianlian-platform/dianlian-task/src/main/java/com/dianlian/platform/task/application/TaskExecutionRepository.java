package com.dianlian.platform.task.application;

import com.dianlian.platform.model.api.ModelChatResponse;
import com.dianlian.platform.model.api.ResolvedModelRoute;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

public interface TaskExecutionRepository {

    Optional<ClaimedExecution> claimNext(String workerId, Instant now, Instant leaseUntil);

    ClaimedExecution freezeRoute(ClaimedExecution execution, ResolvedModelRoute route, Instant now);

    ClaimedExecution recordProviderResponse(
            ClaimedExecution execution,
            ModelChatResponse response,
            long desiredCapturedAmount,
            boolean usageEstimated,
            Instant startedAt,
            Instant completedAt
    );

    ClaimedExecution recordProviderFailure(
            ClaimedExecution execution,
            String failureCode,
            long desiredCapturedAmount,
            boolean usageEstimated,
            Instant startedAt,
            Instant completedAt
    );

    SettlementIntent finalizeSuccess(ClaimedExecution execution, Instant now);

    SettlementIntent finalizeFailure(ClaimedExecution execution, Instant now);

    void deferFinalization(ClaimedExecution execution, Instant nextAttemptAt, String blockerCode, Instant now);

    record ClaimedExecution(
            UUID runtimeRunId,
            UUID tenantId,
            UUID taskId,
            UUID taskStepId,
            long executionGeneration,
            String claimedFromStatus,
            String status,
            String leaseOwner,
            long leaseEpoch,
            UUID requestedBy,
            UUID enterpriseAgentId,
            UUID agentVersionId,
            UUID configurationVersionId,
            String roleName,
            String platformProfile,
            String enterpriseInstructions,
            String modelPolicyMode,
            String knowledgeScopeMode,
            String taskGoal,
            String stepTitle,
            String outputContract,
            String desiredArtifactType,
            String inputSnapshotJson,
            String dependencyArtifacts,
            UUID pointReservationId,
            UUID modelRouteBindingId,
            Long modelRouteStateVersion,
            UUID modelDefinitionId,
            Long modelReservationCeiling,
            String providerResponseText,
            int inputTokens,
            int outputTokens,
            boolean usageEstimated,
            long capturedAmount,
            String failureCode
    ) {

        public boolean providerResponseReady() {
            return "RESPONSE_RECEIVED".equals(status);
        }

        public boolean providerFailureReady() {
            return "PROVIDER_FAILED".equals(status);
        }

        public boolean recoveredRunningAttempt() {
            return "RUNNING".equals(claimedFromStatus);
        }
    }

    record SettlementIntent(
            boolean required,
            UUID tenantId,
            UUID actorId,
            UUID reservationId,
            long capturedAmount,
            String idempotencyKey,
            String requestHash,
            String reasonCode
    ) {

        public static SettlementIntent none() {
            return new SettlementIntent(false, null, null, null, 0, null, null, null);
        }
    }
}

package com.dianlian.platform.task.application;

import static org.assertj.core.api.Assertions.assertThat;

import com.dianlian.platform.billing.api.PointSettlementResult;
import com.dianlian.platform.billing.api.PointSettlementService;
import com.dianlian.platform.billing.api.SettlePointsCommand;
import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.ModelChatRequest;
import com.dianlian.platform.model.api.ModelChatResponse;
import com.dianlian.platform.model.api.ModelDefinitionStatus;
import com.dianlian.platform.model.api.ModelDefinitionView;
import com.dianlian.platform.model.api.ModelGateway;
import com.dianlian.platform.model.api.ModelRoutePreference;
import com.dianlian.platform.model.api.ModelRouteQuery;
import com.dianlian.platform.model.api.ResolvedModelRoute;
import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;
import org.springframework.transaction.support.TransactionTemplate;

class TaskExecutionApplicationServiceTests {

    private static final Instant NOW = Instant.parse("2026-08-11T09:00:00Z");
    private static final UUID TENANT_ID = uuid(1);
    private static final UUID TASK_ID = uuid(2);
    private static final UUID STEP_ID = uuid(3);
    private static final UUID RUN_ID = uuid(4);
    private static final UUID ACTOR_ID = uuid(5);
    private static final UUID AGENT_ID = uuid(6);
    private static final UUID ROUTE_ID = uuid(7);
    private static final UUID MODEL_ID = uuid(8);
    private static final UUID RESERVATION_ID = uuid(9);

    @Test
    void invokesModelOutsideLocalTransactionAndPersistsConfirmedUsage() {
        var transactions = new RecordingTransactionManager();
        var repository = new RecordingRepository(claimed("PREPARED", "RUNNING", null));
        var gateway = new RecordingGateway(
                transactions,
                new ModelChatResponse("阶段成果", 1_000, 2_000, true, "provider-1", "STOP")
        );
        var settlement = new RecordingSettlement(transactions);

        assertThat(service(repository, gateway, settlement, transactions).processNext("worker-1")).isTrue();

        assertThat(gateway.request.systemInstruction()).contains("尚未连接任务知识检索");
        assertThat(gateway.request.systemInstruction()).contains("不得声称已经检索");
        assertThat(repository.desiredCapturedAmount).isEqualTo(3);
        assertThat(repository.usageEstimated).isFalse();
        assertThat(repository.successFinalized).isTrue();
        assertThat(settlement.command.capturedAmount()).isEqualTo(3);
    }

    @Test
    void missingProviderUsageUsesFrozenModelCeilingAndIsMarkedEstimated() {
        var transactions = new RecordingTransactionManager();
        var repository = new RecordingRepository(claimed("PREPARED", "RUNNING", null));
        var gateway = new RecordingGateway(
                transactions,
                new ModelChatResponse("阶段成果", 0, 0, false, "provider-2", "STOP")
        );

        service(repository, gateway, new RecordingSettlement(transactions), transactions)
                .processNext("worker-1");

        assertThat(repository.desiredCapturedAmount).isEqualTo(500);
        assertThat(repository.usageEstimated).isTrue();
        assertThat(repository.successFinalized).isTrue();
    }

    @Test
    void recoveredRunningLeaseIsBlockedWithoutChargingOrSettling() {
        var transactions = new RecordingTransactionManager();
        var repository = new RecordingRepository(claimed("RUNNING", "RUNNING", 500L));
        repository.settleOnFailure = false;
        var settlement = new RecordingSettlement(transactions);

        service(
                repository,
                new RecordingGateway(transactions, new ModelChatResponse(
                        "不得调用", 0, 0, false, null, "STOP")),
                settlement,
                transactions
        ).processNext("worker-1");

        assertThat(repository.failureCode).isEqualTo("PROVIDER_OUTCOME_UNKNOWN");
        assertThat(repository.desiredCapturedAmount).isZero();
        assertThat(repository.failureFinalized).isTrue();
        assertThat(settlement.command).isNull();
    }

    @Test
    void legalHighRateConfigurationSaturatesAtCeilingWithoutLosingProviderResponse() {
        var transactions = new RecordingTransactionManager();
        var repository = new RecordingRepository(claimed("PREPARED", "RUNNING", null));
        var gateway = new RecordingGateway(
                transactions,
                new ModelChatResponse("高费率阶段成果", 100_000, 100_000, true, "provider-3", "STOP")
        );
        var highRateRoute = new ModelRouteQuery() {
            @Override
            public ResolvedModelRoute resolve(
                    UUID tenantId,
                    UUID enterpriseAgentId,
                    ModelCapabilityType capabilityType,
                    ModelRoutePreference preference
            ) {
                return route(Long.MAX_VALUE, Long.MAX_VALUE);
            }

            @Override
            public ResolvedModelRoute requireSnapshot(UUID routeBindingId, UUID modelDefinitionId) {
                return route(Long.MAX_VALUE, Long.MAX_VALUE);
            }
        };

        new TaskExecutionApplicationService(
                repository,
                highRateRoute,
                gateway,
                new RecordingSettlement(transactions),
                new TransactionTemplate(transactions),
                Clock.fixed(NOW, ZoneOffset.UTC)
        ).processNext("worker-1");

        assertThat(repository.desiredCapturedAmount).isEqualTo(500);
        assertThat(repository.successFinalized).isTrue();
    }

    private static TaskExecutionApplicationService service(
            RecordingRepository repository,
            ModelGateway gateway,
            PointSettlementService settlement,
            RecordingTransactionManager transactions
    ) {
        return new TaskExecutionApplicationService(
                repository,
                routeQuery(),
                gateway,
                settlement,
                new TransactionTemplate(transactions),
                Clock.fixed(NOW, ZoneOffset.UTC)
        );
    }

    private static ModelRouteQuery routeQuery() {
        return new ModelRouteQuery() {
            @Override
            public ResolvedModelRoute resolve(
                    UUID tenantId,
                    UUID enterpriseAgentId,
                    ModelCapabilityType capabilityType,
                    ModelRoutePreference preference
            ) {
                assertThat(tenantId).isEqualTo(TENANT_ID);
                assertThat(enterpriseAgentId).isEqualTo(AGENT_ID);
                assertThat(preference).isEqualTo(ModelRoutePreference.PLATFORM_ONLY);
                return route();
            }

            @Override
            public ResolvedModelRoute requireSnapshot(UUID routeBindingId, UUID modelDefinitionId) {
                return route();
            }
        };
    }

    private static ResolvedModelRoute route() {
        return route(1_000, 1_000);
    }

    private static ResolvedModelRoute route(long inputRate, long outputRate) {
        return new ResolvedModelRoute(
                ROUTE_ID,
                1,
                "PLATFORM",
                new ModelDefinitionView(
                        MODEL_ID,
                        "TASK_TEST",
                        1,
                        "任务测试模型",
                        "TEST_PROVIDER",
                        "OPENAI_COMPATIBLE",
                        "https://example.invalid/v1",
                        "test-model",
                        "env:DIANLIAN_MODEL_TEST_KEY",
                        ModelCapabilityType.TEXT_CHAT,
                        BigDecimal.ZERO,
                        4_096,
                        inputRate,
                        outputRate,
                        500,
                        ModelDefinitionStatus.ACTIVE,
                        ACTOR_ID,
                        NOW
                )
        );
    }

    private static TaskExecutionRepository.ClaimedExecution claimed(
            String claimedFromStatus,
            String status,
            Long modelCeiling
    ) {
        return new TaskExecutionRepository.ClaimedExecution(
                RUN_ID, TENANT_ID, TASK_ID, STEP_ID, 1, claimedFromStatus, status, "worker-1", 1,
                ACTOR_ID, AGENT_ID, uuid(10), uuid(11), "法务合同审核员工", "平台角色说明",
                "企业合同红线", "PLATFORM_DEFAULT", "NONE", "审核合同", "风险分析",
                "legal.review.output", "DOCUMENT", "{\"goal\":\"审核合同\"}", null,
                RESERVATION_ID, modelCeiling == null ? null : ROUTE_ID,
                modelCeiling == null ? null : 1L, modelCeiling == null ? null : MODEL_ID,
                modelCeiling, null, 0, 0, false, 0, null
        );
    }

    private static TaskExecutionRepository.ClaimedExecution copy(
            TaskExecutionRepository.ClaimedExecution source,
            String status,
            String response,
            boolean estimated,
            long captured,
            String failureCode,
            Long ceiling
    ) {
        return new TaskExecutionRepository.ClaimedExecution(
                source.runtimeRunId(), source.tenantId(), source.taskId(), source.taskStepId(),
                source.executionGeneration(), source.claimedFromStatus(), status, source.leaseOwner(),
                source.leaseEpoch(), source.requestedBy(), source.enterpriseAgentId(), source.agentVersionId(),
                source.configurationVersionId(), source.roleName(), source.platformProfile(),
                source.enterpriseInstructions(), source.modelPolicyMode(), source.knowledgeScopeMode(),
                source.taskGoal(), source.stepTitle(), source.outputContract(), source.desiredArtifactType(),
                source.inputSnapshotJson(), source.dependencyArtifacts(), source.pointReservationId(), ROUTE_ID,
                1L, MODEL_ID, ceiling, response, 0, 0, estimated, captured, failureCode
        );
    }

    private static UUID uuid(long suffix) {
        return UUID.fromString("00000000-0000-0000-0000-" + String.format("%012d", suffix));
    }

    private static final class RecordingRepository implements TaskExecutionRepository {
        private ClaimedExecution claimed;
        private long desiredCapturedAmount;
        private boolean usageEstimated;
        private String failureCode;
        private boolean successFinalized;
        private boolean failureFinalized;
        private boolean settleOnFailure = true;

        private RecordingRepository(ClaimedExecution claimed) {
            this.claimed = claimed;
        }

        @Override
        public Optional<ClaimedExecution> claimNext(String workerId, Instant now, Instant leaseUntil) {
            return Optional.of(claimed);
        }

        @Override
        public ClaimedExecution freezeRoute(ClaimedExecution execution, ResolvedModelRoute route, Instant now) {
            claimed = copy(execution, "RUNNING", null, false, 0, null,
                    route.model().reservationCeilingMicroCredit());
            return claimed;
        }

        @Override
        public ClaimedExecution recordProviderResponse(
                ClaimedExecution execution,
                ModelChatResponse response,
                long desiredCapturedAmount,
                boolean usageEstimated,
                Instant startedAt,
                Instant completedAt
        ) {
            this.desiredCapturedAmount = desiredCapturedAmount;
            this.usageEstimated = usageEstimated;
            claimed = copy(execution, "RESPONSE_RECEIVED", response.text(), usageEstimated,
                    desiredCapturedAmount, null, execution.modelReservationCeiling());
            return claimed;
        }

        @Override
        public ClaimedExecution recordProviderFailure(
                ClaimedExecution execution,
                String failureCode,
                long desiredCapturedAmount,
                boolean usageEstimated,
                Instant startedAt,
                Instant completedAt
        ) {
            this.failureCode = failureCode;
            this.desiredCapturedAmount = desiredCapturedAmount;
            claimed = copy(execution, "PROVIDER_FAILED", null, usageEstimated,
                    desiredCapturedAmount, failureCode, execution.modelReservationCeiling());
            return claimed;
        }

        @Override
        public SettlementIntent finalizeSuccess(ClaimedExecution execution, Instant now) {
            successFinalized = true;
            return settlement(execution, execution.capturedAmount());
        }

        @Override
        public SettlementIntent finalizeFailure(ClaimedExecution execution, Instant now) {
            failureFinalized = true;
            return settleOnFailure ? settlement(execution, execution.capturedAmount()) : SettlementIntent.none();
        }

        @Override
        public void deferFinalization(
                ClaimedExecution execution,
                Instant nextAttemptAt,
                String blockerCode,
                Instant now
        ) {
        }

        private SettlementIntent settlement(ClaimedExecution execution, long captured) {
            return new SettlementIntent(
                    true, TENANT_ID, ACTOR_ID, RESERVATION_ID, captured,
                    "task-settlement:" + TASK_ID, "request-hash", "TASK_SUCCEEDED"
            );
        }
    }

    private static final class RecordingGateway implements ModelGateway {
        private final RecordingTransactionManager transactions;
        private final ModelChatResponse response;
        private ModelChatRequest request;

        private RecordingGateway(RecordingTransactionManager transactions, ModelChatResponse response) {
            this.transactions = transactions;
            this.response = response;
        }

        @Override
        public ModelChatResponse chat(ResolvedModelRoute route, ModelChatRequest request) {
            assertThat(transactions.active).isFalse();
            this.request = request;
            return response;
        }
    }

    private static final class RecordingSettlement implements PointSettlementService {
        private final RecordingTransactionManager transactions;
        private SettlePointsCommand command;

        private RecordingSettlement(RecordingTransactionManager transactions) {
            this.transactions = transactions;
        }

        @Override
        public PointSettlementResult settle(SettlePointsCommand command) {
            assertThat(transactions.active).isTrue();
            this.command = command;
            return new PointSettlementResult(
                    uuid(12), command.reservationId(), command.capturedAmount(),
                    Math.max(0, 500 - command.capturedAmount()), "CAPTURED", NOW, false
            );
        }
    }

    private static final class RecordingTransactionManager implements PlatformTransactionManager {
        private boolean active;

        @Override
        public TransactionStatus getTransaction(TransactionDefinition definition) {
            assertThat(active).isFalse();
            active = true;
            return new SimpleTransactionStatus();
        }

        @Override
        public void commit(TransactionStatus status) {
            active = false;
        }

        @Override
        public void rollback(TransactionStatus status) {
            active = false;
        }
    }
}

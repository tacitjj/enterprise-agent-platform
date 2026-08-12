package com.dianlian.platform.task.application;

import com.dianlian.platform.billing.api.PointSettlementService;
import com.dianlian.platform.billing.api.SettlePointsCommand;
import com.dianlian.platform.employee.api.EnterpriseAgentModelPolicyMode;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.ModelChatMessage;
import com.dianlian.platform.model.api.ModelChatRequest;
import com.dianlian.platform.model.api.ModelChatResponse;
import com.dianlian.platform.model.api.ModelGateway;
import com.dianlian.platform.model.api.ModelProviderUnavailableException;
import com.dianlian.platform.model.api.ModelRoutePreference;
import com.dianlian.platform.model.api.ModelRouteQuery;
import com.dianlian.platform.model.api.ModelRouteUnavailableException;
import com.dianlian.platform.task.api.AgentRuntimePort;
import com.dianlian.platform.task.api.RuntimeAdmission;
import com.dianlian.platform.task.api.RuntimeStartCommand;
import com.dianlian.platform.task.domain.TaskStepExecution;
import java.math.BigInteger;
import java.time.Clock;
import java.time.Duration;
import java.util.List;
import java.util.Objects;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public final class TaskExecutionApplicationService {

    private static final Logger LOGGER = LoggerFactory.getLogger(TaskExecutionApplicationService.class);
    private static final Duration LEASE_DURATION = Duration.ofMinutes(3);
    private static final Duration FINALIZATION_RETRY_DELAY = Duration.ofSeconds(30);

    private final TaskExecutionRepository repository;
    private final ModelRouteQuery modelRouteQuery;
    private final ModelGateway modelGateway;
    private final PointSettlementService pointSettlementService;
    private final TransactionTemplate transactionTemplate;
    private final Clock clock;
    private final AgentRuntimePort legacyAgentRuntimePort;

    @Autowired
    public TaskExecutionApplicationService(
            TaskExecutionRepository repository,
            ModelRouteQuery modelRouteQuery,
            ModelGateway modelGateway,
            PointSettlementService pointSettlementService,
            TransactionTemplate transactionTemplate
    ) {
        this(repository, modelRouteQuery, modelGateway, pointSettlementService,
                transactionTemplate, Clock.systemUTC());
    }

    TaskExecutionApplicationService(
            TaskExecutionRepository repository,
            ModelRouteQuery modelRouteQuery,
            ModelGateway modelGateway,
            PointSettlementService pointSettlementService,
            TransactionTemplate transactionTemplate,
            Clock clock
    ) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
        this.modelRouteQuery = Objects.requireNonNull(modelRouteQuery, "modelRouteQuery must not be null");
        this.modelGateway = Objects.requireNonNull(modelGateway, "modelGateway must not be null");
        this.pointSettlementService = Objects.requireNonNull(
                pointSettlementService,
                "pointSettlementService must not be null"
        );
        this.transactionTemplate = Objects.requireNonNull(transactionTemplate, "transactionTemplate must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
        this.legacyAgentRuntimePort = null;
    }

    /**
     * Compatibility entry point for the disabled Python-runtime integration contract.
     */
    public TaskExecutionApplicationService(AgentRuntimePort agentRuntimePort) {
        this.repository = null;
        this.modelRouteQuery = null;
        this.modelGateway = null;
        this.pointSettlementService = null;
        this.transactionTemplate = null;
        this.clock = null;
        this.legacyAgentRuntimePort = Objects.requireNonNull(agentRuntimePort, "agentRuntimePort must not be null");
    }

    public boolean processNext(String workerId) {
        Objects.requireNonNull(workerId, "workerId must not be null");
        var now = clock.instant();
        var claimed = transactionTemplate.execute(status -> repository.claimNext(
                workerId,
                now,
                now.plus(LEASE_DURATION)
        ));
        if (claimed == null || claimed.isEmpty()) {
            return false;
        }
        var execution = claimed.orElseThrow();
        if (execution.providerResponseReady()) {
            finalizeSuccess(execution);
            return true;
        }
        if (execution.providerFailureReady()) {
            finalizeFailure(execution);
            return true;
        }
        if (execution.recoveredRunningAttempt()) {
            recoverUnknownProviderOutcome(execution);
            return true;
        }
        executeModel(execution);
        return true;
    }

    private void executeModel(TaskExecutionRepository.ClaimedExecution execution) {
        var startedAt = clock.instant();
        final com.dianlian.platform.model.api.ResolvedModelRoute route;
        try {
            route = modelRouteQuery.resolve(
                    execution.tenantId(),
                    execution.enterpriseAgentId(),
                    ModelCapabilityType.TEXT_CHAT,
                    routePreference(execution.modelPolicyMode())
            );
        } catch (ModelRouteUnavailableException exception) {
            var failed = transactionTemplate.execute(status -> repository.recordProviderFailure(
                    execution,
                    "MODEL_ROUTE_UNAVAILABLE",
                    0,
                    false,
                    startedAt,
                    clock.instant()
            ));
            finalizeFailure(Objects.requireNonNull(failed));
            return;
        }

        var frozen = transactionTemplate.execute(status -> repository.freezeRoute(
                execution,
                route,
                clock.instant()
        ));
        var routedExecution = Objects.requireNonNull(frozen, "model route must be frozen before invocation");
        try {
            var response = modelGateway.chat(route, request(routedExecution));
            var desiredCapturedAmount = response.usageConfirmed()
                    ? calculateCharge(response, route)
                    : route.model().reservationCeilingMicroCredit();
            var persisted = transactionTemplate.execute(status -> repository.recordProviderResponse(
                    routedExecution,
                    response,
                    desiredCapturedAmount,
                    !response.usageConfirmed(),
                    startedAt,
                    clock.instant()
            ));
            finalizeSuccess(Objects.requireNonNull(persisted));
        } catch (ModelProviderUnavailableException exception) {
            var failed = transactionTemplate.execute(status -> repository.recordProviderFailure(
                    routedExecution,
                    exception.code(),
                    0,
                    false,
                    startedAt,
                    clock.instant()
            ));
            finalizeFailure(Objects.requireNonNull(failed));
        }
    }

    private void recoverUnknownProviderOutcome(TaskExecutionRepository.ClaimedExecution execution) {
        var persisted = transactionTemplate.execute(status -> repository.recordProviderFailure(
                execution,
                "PROVIDER_OUTCOME_UNKNOWN",
                0,
                false,
                clock.instant(),
                clock.instant()
        ));
        finalizeFailure(Objects.requireNonNull(persisted));
    }

    private void finalizeSuccess(TaskExecutionRepository.ClaimedExecution execution) {
        finalizeExecution(execution, true);
    }

    private void finalizeFailure(TaskExecutionRepository.ClaimedExecution execution) {
        finalizeExecution(execution, false);
    }

    private void finalizeExecution(TaskExecutionRepository.ClaimedExecution execution, boolean success) {
        try {
            transactionTemplate.executeWithoutResult(status -> {
                var intent = success
                        ? repository.finalizeSuccess(execution, clock.instant())
                        : repository.finalizeFailure(execution, clock.instant());
                if (intent.required()) {
                    pointSettlementService.settle(new SettlePointsCommand(
                            intent.tenantId(),
                            intent.actorId(),
                            intent.reservationId(),
                            intent.capturedAmount(),
                            intent.idempotencyKey(),
                            intent.requestHash(),
                            intent.reasonCode()
                    ));
                }
            });
        } catch (RuntimeException exception) {
            LOGGER.warn(
                    "Task execution finalization deferred: taskId={}, runtimeRunId={}",
                    execution.taskId(),
                    execution.runtimeRunId(),
                    exception
            );
            var nextAttemptAt = clock.instant().plus(FINALIZATION_RETRY_DELAY);
            transactionTemplate.executeWithoutResult(status -> repository.deferFinalization(
                    execution,
                    nextAttemptAt,
                    "FINALIZATION_RETRY_PENDING",
                    clock.instant()
            ));
        }
    }

    private ModelChatRequest request(TaskExecutionRepository.ClaimedExecution execution) {
        var systemInstruction = limit("""
                你是点联任务执行器中的数字员工。只能依据本次任务创建时冻结的信息完成当前步骤。
                冻结角色：%s
                平台角色说明：%s
                企业补充指令：%s
                冻结模型策略：%s
                冻结知识模式：%s

                重要边界：当前任务 Worker 尚未连接任务知识检索、个人长期记忆或群聊记忆。
                不得声称已经检索、读取、引用或记住任何未出现在输入快照或前序阶段成果中的资料。
                不得执行外部发布、写库或其他副作用；只输出当前步骤的阶段成果。
                """.formatted(
                execution.roleName(),
                execution.platformProfile(),
                execution.enterpriseInstructions(),
                execution.modelPolicyMode(),
                execution.knowledgeScopeMode()
        ), 59_000);
        var userInstruction = limit("""
                任务目标：%s
                当前步骤：%s
                输出契约：%s
                期望成果类型：%s

                创建时冻结的输入快照：
                %s

                已完成的前序阶段成果：
                %s
                """.formatted(
                execution.taskGoal(),
                execution.stepTitle(),
                execution.outputContract(),
                Objects.toString(execution.desiredArtifactType(), "STAGE_TEXT"),
                execution.inputSnapshotJson(),
                Objects.toString(execution.dependencyArtifacts(), "无")
        ), 39_000);
        return new ModelChatRequest(
                execution.runtimeRunId(),
                systemInstruction,
                List.of(new ModelChatMessage(ModelChatMessage.Role.HUMAN, userInstruction))
        );
    }

    private static ModelRoutePreference routePreference(String modelPolicyMode) {
        var mode = EnterpriseAgentModelPolicyMode.valueOf(modelPolicyMode);
        return switch (mode) {
            case PLATFORM_DEFAULT -> ModelRoutePreference.PLATFORM_ONLY;
            case AGENT_ROUTE -> ModelRoutePreference.AGENT_ONLY;
        };
    }

    private static long calculateCharge(
            ModelChatResponse response,
            com.dianlian.platform.model.api.ResolvedModelRoute route
    ) {
        var model = route.model();
        var divisor = BigInteger.valueOf(1_000_000L);
        var input = ceilDiv(
                BigInteger.valueOf(response.inputTokens())
                        .multiply(BigInteger.valueOf(model.inputRateMicroCreditPerMillionTokens())),
                divisor
        );
        var output = ceilDiv(
                BigInteger.valueOf(response.outputTokens())
                        .multiply(BigInteger.valueOf(model.outputRateMicroCreditPerMillionTokens())),
                divisor
        );
        return input.add(output)
                .min(BigInteger.valueOf(model.reservationCeilingMicroCredit()))
                .longValueExact();
    }

    private static BigInteger ceilDiv(BigInteger value, BigInteger divisor) {
        return value.signum() == 0
                ? BigInteger.ZERO
                : value.add(divisor).subtract(BigInteger.ONE).divide(divisor);
    }

    private static String limit(String value, int maxLength) {
        return value.length() <= maxLength ? value : value.substring(0, maxLength);
    }

    public RuntimeAdmission start(
            TaskStepExecution execution,
            String idempotencyKey,
            String requestHash,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(execution, "execution must not be null");
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        if (legacyAgentRuntimePort == null) {
            throw new IllegalStateException("The legacy AgentRuntimePort is not configured");
        }
        var command = new RuntimeStartCommand(
                execution.taskStepId(),
                execution.executionGeneration().value(),
                execution.runtimeRunId(),
                idempotencyKey,
                requestHash
        );
        return legacyAgentRuntimePort.start(command, accessContext);
    }
}

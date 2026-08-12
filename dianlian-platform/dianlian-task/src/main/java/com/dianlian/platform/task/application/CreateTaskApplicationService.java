package com.dianlian.platform.task.application;

import com.dianlian.platform.billing.api.PointReservationService;
import com.dianlian.platform.billing.api.ReservePointsCommand;
import com.dianlian.platform.employee.api.ExecutableAgentQuery;
import com.dianlian.platform.employee.api.ExecutableAgentSummary;
import com.dianlian.platform.employee.api.ExecutionExecutorType;
import com.dianlian.platform.employee.api.ExecutionStepDescriptor;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.task.api.BillingScopeType;
import com.dianlian.platform.task.api.CollaborationMode;
import com.dianlian.platform.task.api.CreateTaskCommand;
import com.dianlian.platform.task.api.CreateTaskUseCase;
import com.dianlian.platform.task.api.TaskAdmissionRejectedException;
import com.dianlian.platform.task.api.TaskAccessDeniedException;
import com.dianlian.platform.task.api.TaskCommandAccepted;
import com.dianlian.platform.task.api.TaskPermissions;
import com.dianlian.platform.task.api.TaskStatus;
import java.time.Clock;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CreateTaskApplicationService implements CreateTaskUseCase {

    private static final String TASK_BUSINESS_TYPE = "TASK";

    private final ExecutableAgentQuery executableAgentQuery;
    private final PointReservationService pointReservationService;
    private final TaskCreationRepository taskCreationRepository;
    private final TaskPayloadSerializer serializer;
    private final CapabilityInputValidator capabilityInputValidator;
    private final Clock clock;

    @Autowired
    public CreateTaskApplicationService(
            ExecutableAgentQuery executableAgentQuery,
            PointReservationService pointReservationService,
            TaskCreationRepository taskCreationRepository,
            TaskPayloadSerializer serializer,
            CapabilityInputValidator capabilityInputValidator
    ) {
        this(
                executableAgentQuery,
                pointReservationService,
                taskCreationRepository,
                serializer,
                capabilityInputValidator,
                Clock.systemUTC()
        );
    }

    CreateTaskApplicationService(
            ExecutableAgentQuery executableAgentQuery,
            PointReservationService pointReservationService,
            TaskCreationRepository taskCreationRepository,
            TaskPayloadSerializer serializer,
            CapabilityInputValidator capabilityInputValidator,
            Clock clock
    ) {
        this.executableAgentQuery = Objects.requireNonNull(
                executableAgentQuery,
                "executableAgentQuery must not be null"
        );
        this.pointReservationService = Objects.requireNonNull(
                pointReservationService,
                "pointReservationService must not be null"
        );
        this.taskCreationRepository = Objects.requireNonNull(
                taskCreationRepository,
                "taskCreationRepository must not be null"
        );
        this.serializer = Objects.requireNonNull(serializer, "serializer must not be null");
        this.capabilityInputValidator = Objects.requireNonNull(
                capabilityInputValidator,
                "capabilityInputValidator must not be null"
        );
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
    }

    @Override
    @Transactional
    public TaskCommandAccepted create(CreateTaskCommand command, AccessContext accessContext) {
        Objects.requireNonNull(command, "command must not be null");
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        requirePermission(accessContext, TaskPermissions.CREATE);
        validateOwnership(command, accessContext);

        var hashedRequest = serializer.hash(command);
        var occurredAt = clock.instant();
        var idempotency = taskCreationRepository.claim(
                accessContext.tenantId().value(),
                accessContext.actorId().value(),
                command.idempotencyKey(),
                hashedRequest.requestHash(),
                occurredAt
        );
        if (!idempotency.claimed()) {
            return idempotency.replayedResponse();
        }

        var profiles = requireExecutionProfiles(command, accessContext);
        var estimatedUpperBound = estimatedUpperBound(profiles);
        if (command.maxPointCost() < estimatedUpperBound) {
            throw new TaskAdmissionRejectedException(
                    "MAX_POINT_COST_BELOW_ESTIMATE",
                    "maxPointCost is lower than the employee execution profile estimate"
            );
        }

        var taskId = UUID.randomUUID();
        var pointReservation = pointReservationService.reserve(
                new ReservePointsCommand(
                        TASK_BUSINESS_TYPE,
                        taskId,
                        command.ownership().billingScopeType().name(),
                        command.ownership().billingScopeId(),
                        estimatedUpperBound,
                        "task-create:" + command.idempotencyKey()
                ),
                accessContext
        );
        var targetCreations = buildTargets(command, profiles);
        var stepCreations = buildSteps(taskId, command, profiles);
        var initialStatus = initialTaskStatus(stepCreations);
        var resumeEventId = UUID.randomUUID();
        var response = new TaskCommandAccepted(
                taskId,
                1,
                initialStatus,
                occurredAt,
                "/api/v1/tasks/" + taskId,
                "/api/v1/tasks/" + taskId + "/events",
                resumeEventId,
                false
        );
        taskCreationRepository.insert(new TaskCreation(
                accessContext.tenantId().value(),
                accessContext.actorId().value(),
                taskId,
                titleFromGoal(command.goal()),
                profiles.getFirst().capabilityCode(),
                hashedRequest.requestHash(),
                hashedRequest.canonicalJson(),
                serializer.serialize(new ExecutionProfileSnapshot(1, profiles)),
                estimatedUpperBound,
                command,
                pointReservation,
                targetCreations,
                stepCreations,
                response,
                occurredAt
        ));
        return response;
    }

    private void validateOwnership(CreateTaskCommand command, AccessContext accessContext) {
        if (!command.ownership().ownerUserId().equals(accessContext.actorId().value())) {
            throw new TaskAdmissionRejectedException(
                    "TASK_OWNER_MISMATCH",
                    "The initial task owner must be the current actor"
            );
        }
        if (command.ownership().billingScopeType() == BillingScopeType.TENANT
                && !command.ownership().billingScopeId().equals(accessContext.tenantId().value())) {
            throw new TaskAdmissionRejectedException(
                    "BILLING_SCOPE_MISMATCH",
                    "TENANT billing scope must reference the current tenant"
            );
        }
        if (command.ownership().billingScopeType() == BillingScopeType.USER
                && !command.ownership().billingScopeId().equals(command.ownership().ownerUserId())) {
            throw new TaskAdmissionRejectedException(
                    "BILLING_SCOPE_MISMATCH",
                    "USER billing scope must reference the task owner"
            );
        }
    }

    private static void requirePermission(AccessContext accessContext, String permission) {
        if (!accessContext.authorities().contains(permission)) {
            throw new TaskAccessDeniedException(permission);
        }
    }

    private List<ExecutableAgentSummary> requireExecutionProfiles(
            CreateTaskCommand command,
            AccessContext accessContext
    ) {
        var profiles = command.targetAgentIds().stream()
                .map(agentId -> executableAgentQuery.requireExecutableForTask(agentId, accessContext))
                .toList();
        var expectedCapability = profiles.getFirst().capabilityCode();
        var expectedSchemaId = command.capabilityInput().schemaId();
        var expectedSchemaVersion = command.capabilityInput().schemaVersion();
        for (var profile : profiles) {
            if (!expectedCapability.equals(profile.capabilityCode())) {
                throw new TaskAdmissionRejectedException(
                        "INCOMPATIBLE_TARGET_CAPABILITIES",
                        "All target employees in one task must expose the same capability"
                );
            }
            if (!expectedSchemaId.equals(profile.inputSchema().schemaId())
                    || !expectedSchemaVersion.equals(profile.inputSchema().version())) {
                throw new TaskAdmissionRejectedException(
                        "CAPABILITY_INPUT_SCHEMA_MISMATCH",
                        "Capability input does not match the selected employee version"
                );
            }
            if (profile.pointEstimate() < 1) {
                throw new TaskAdmissionRejectedException(
                        "EMPLOYEE_POINT_ESTIMATE_INVALID",
                        "Selected employee version must declare a positive point estimate"
                );
            }
            capabilityInputValidator.validate(command.capabilityInput(), profile.inputSchema());
        }
        return profiles;
    }

    private long estimatedUpperBound(List<ExecutableAgentSummary> profiles) {
        try {
            var total = 0L;
            for (var profile : profiles) {
                total = Math.addExact(total, profile.pointEstimate());
            }
            return total;
        } catch (ArithmeticException exception) {
            throw new TaskAdmissionRejectedException(
                    "POINT_ESTIMATE_OVERFLOW",
                    "Combined employee point estimate exceeds the supported range"
            );
        }
    }

    private List<TaskTargetCreation> buildTargets(
            CreateTaskCommand command,
            List<ExecutableAgentSummary> profiles
    ) {
        var targets = new ArrayList<TaskTargetCreation>();
        for (var index = 0; index < profiles.size(); index++) {
            var profile = profiles.get(index);
            targets.add(new TaskTargetCreation(
                    profile.enterpriseAgentId(),
                    profile.agentVersionId(),
                    targetRole(command, profile.enterpriseAgentId()),
                    index + 1,
                    profile.capabilityCode(),
                    profile.executionTemplate().templateCode(),
                    profile.executionTemplate().version(),
                    profile.pointEstimate()
            ));
        }
        return List.copyOf(targets);
    }

    private TaskTargetRole targetRole(CreateTaskCommand command, UUID enterpriseAgentId) {
        return switch (command.collaborationMode()) {
            case SINGLE_TARGET -> TaskTargetRole.PRIMARY;
            case PARALLEL_SEPARATE -> TaskTargetRole.SEPARATE;
            case PRIMARY_SUMMARY -> enterpriseAgentId.equals(command.primaryAgentId())
                    ? TaskTargetRole.PRIMARY
                    : TaskTargetRole.SUPPORT;
        };
    }

    private List<TaskStepCreation> buildSteps(
            UUID taskId,
            CreateTaskCommand command,
            List<ExecutableAgentSummary> profiles
    ) {
        var steps = new ArrayList<TaskStepCreation>();
        var sequence = 1;
        for (var targetIndex = 0; targetIndex < profiles.size(); targetIndex++) {
            var profile = profiles.get(targetIndex);
            var descriptorSteps = profile.executionTemplate().steps();
            var idsByKey = new HashMap<String, UUID>();
            for (var descriptor : descriptorSteps) {
                idsByKey.put(descriptor.stepKey(), UUID.randomUUID());
            }
            for (var descriptor : descriptorSteps) {
                var dependencies = descriptor.dependsOn().stream().map(idsByKey::get).toList();
                steps.add(new TaskStepCreation(
                        idsByKey.get(descriptor.stepKey()),
                        persistedStepKey(targetIndex, profiles.size(), descriptor.stepKey()),
                        descriptor.title(),
                        initialStepStatus(descriptor, dependencies),
                        descriptor.executorType(),
                        responsibleType(descriptor),
                        responsibleId(taskId, command, profile, descriptor),
                        dependencies,
                        contractRef(descriptor.inputSchemaRef(), profile.inputSchema().schemaId()),
                        contractRef(descriptor.outputSchemaRef(), "unspecified"),
                        descriptor.humanCheckpoint(),
                        initialBlocker(descriptor, dependencies),
                        sequence++
                ));
            }
        }
        return List.copyOf(steps);
    }

    private TaskStatus initialTaskStatus(List<TaskStepCreation> steps) {
        if (steps.stream().anyMatch(step -> "READY".equals(step.status()))) {
            return TaskStatus.QUEUED;
        }
        if (steps.stream().anyMatch(step -> "WAITING_EXTERNAL".equals(step.status())
                && step.executorType() == ExecutionExecutorType.HUMAN_CHECKPOINT)) {
            return TaskStatus.WAITING_CONFIRMATION;
        }
        return TaskStatus.PAUSED;
    }

    private String initialStepStatus(ExecutionStepDescriptor descriptor, List<UUID> dependencies) {
        if (!dependencies.isEmpty()) {
            return "PENDING";
        }
        return descriptor.executorType() == ExecutionExecutorType.MODEL ? "READY" : "WAITING_EXTERNAL";
    }

    private String initialBlocker(ExecutionStepDescriptor descriptor, List<UUID> dependencies) {
        if (!dependencies.isEmpty()) {
            return null;
        }
        return switch (descriptor.executorType()) {
            case MODEL -> null;
            case HUMAN_CHECKPOINT -> "HUMAN_CONFIRMATION_REQUIRED";
            default -> "EXECUTOR_NOT_CONNECTED_" + descriptor.executorType().name();
        };
    }

    private record ExecutionProfileSnapshot(
            int schemaVersion,
            List<ExecutableAgentSummary> agents
    ) {

        private ExecutionProfileSnapshot {
            if (schemaVersion < 1) {
                throw new IllegalArgumentException("schemaVersion must be positive");
            }
            agents = List.copyOf(Objects.requireNonNull(agents, "agents must not be null"));
            if (agents.isEmpty()) {
                throw new IllegalArgumentException("execution profile snapshot requires at least one agent");
            }
        }
    }

    private String persistedStepKey(int targetIndex, int targetCount, String stepKey) {
        return targetCount == 1 ? stepKey : "t" + (targetIndex + 1) + "." + stepKey;
    }

    private String responsibleType(ExecutionStepDescriptor descriptor) {
        return descriptor.executorType() == ExecutionExecutorType.HUMAN_CHECKPOINT ? "USER" : "AGENT";
    }

    private UUID responsibleId(
            UUID taskId,
            CreateTaskCommand command,
            ExecutableAgentSummary profile,
            ExecutionStepDescriptor descriptor
    ) {
        if (descriptor.executorType() == ExecutionExecutorType.HUMAN_CHECKPOINT) {
            return command.ownership().ownerUserId();
        }
        return profile.enterpriseAgentId() == null ? taskId : profile.enterpriseAgentId();
    }

    private String contractRef(String configuredReference, String fallback) {
        return configuredReference == null ? fallback : configuredReference;
    }

    private String titleFromGoal(String goal) {
        var firstLine = goal.strip().lines().findFirst().orElse(goal.strip());
        return firstLine.length() <= 200 ? firstLine : firstLine.substring(0, 200);
    }
}

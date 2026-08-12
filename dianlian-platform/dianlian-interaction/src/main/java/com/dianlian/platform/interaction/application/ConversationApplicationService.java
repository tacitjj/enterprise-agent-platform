package com.dianlian.platform.interaction.application;

import com.dianlian.platform.billing.api.PointReservationService;
import com.dianlian.platform.billing.api.ReservePointsCommand;
import com.dianlian.platform.employee.api.EnterpriseAgentModelPolicyMode;
import com.dianlian.platform.employee.api.ExecutableAgentQuery;
import com.dianlian.platform.employee.api.ExecutableAgentSummary;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.interaction.api.ConversationCollaborationMode;
import com.dianlian.platform.interaction.api.ConversationCommandConflictException;
import com.dianlian.platform.interaction.api.ConversationCommandOutcome;
import com.dianlian.platform.interaction.api.ConversationCommands;
import com.dianlian.platform.interaction.api.ConversationMessagePage;
import com.dianlian.platform.interaction.api.ConversationQuery;
import com.dianlian.platform.interaction.api.ConversationSummary;
import com.dianlian.platform.interaction.api.ConversationType;
import com.dianlian.platform.interaction.api.CreateConversationCommand;
import com.dianlian.platform.interaction.api.InteractionAccessDeniedException;
import com.dianlian.platform.interaction.api.InteractionPermissions;
import com.dianlian.platform.interaction.api.MessageTargetInput;
import com.dianlian.platform.interaction.api.MessageTriggerType;
import com.dianlian.platform.interaction.api.SendConversationMessageCommand;
import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.ModelRoutePreference;
import com.dianlian.platform.model.api.ModelRouteQuery;
import java.time.Clock;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ConversationApplicationService implements ConversationCommands, ConversationQuery {

    private static final String POLICY_VERSION = "conversation-policy-v1";

    private final ConversationRepository repository;
    private final ExecutableAgentQuery executableAgentQuery;
    private final ModelRouteQuery modelRouteQuery;
    private final PointReservationService pointReservationService;
    private final Clock clock;

    @Autowired
    public ConversationApplicationService(
            ConversationRepository repository,
            ExecutableAgentQuery executableAgentQuery,
            ModelRouteQuery modelRouteQuery,
            PointReservationService pointReservationService
    ) {
        this(repository, executableAgentQuery, modelRouteQuery, pointReservationService, Clock.systemUTC());
    }

    ConversationApplicationService(
            ConversationRepository repository,
            ExecutableAgentQuery executableAgentQuery,
            ModelRouteQuery modelRouteQuery,
            PointReservationService pointReservationService,
            Clock clock
    ) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
        this.executableAgentQuery = Objects.requireNonNull(executableAgentQuery, "executableAgentQuery must not be null");
        this.modelRouteQuery = Objects.requireNonNull(modelRouteQuery, "modelRouteQuery must not be null");
        this.pointReservationService = Objects.requireNonNull(pointReservationService, "pointReservationService must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
    }

    @Override
    @Transactional
    public ConversationCommandOutcome<ConversationSummary> create(
            CreateConversationCommand command,
            AccessContext accessContext
    ) {
        requirePermission(accessContext, InteractionPermissions.CREATE);
        UUID tenantId = accessContext.tenantId().value();
        UUID actorId = accessContext.actorId().value();
        var replay = repository.findConversationIntent(tenantId, actorId, command.idempotencyKey());
        if (replay.isPresent()) {
            requireSameHash(replay.get().requestHash(), command.requestHash());
            return new ConversationCommandOutcome<>(replay.get().summary(), List.of(), true);
        }

        var participantIds = new LinkedHashSet<>(command.participantUserIds());
        participantIds.add(actorId);
        var agentIds = new LinkedHashSet<>(command.enterpriseAgentIds());
        validateShape(command.type(), participantIds.size(), agentIds.size());
        repository.requireActiveTenantMembers(tenantId, List.copyOf(participantIds));
        if (!agentIds.isEmpty()) {
            requirePermission(accessContext, InteractionPermissions.INVOKE_AGENT);
            for (UUID agentId : agentIds) {
                executableAgentQuery.requireExecutableForTask(agentId, accessContext);
            }
        }

        var summary = repository.createConversation(new ConversationRepository.CreateConversationWrite(
                UUID.randomUUID(), tenantId, actorId, command.type(), command.title(),
                List.copyOf(participantIds), List.copyOf(agentIds), command.idempotencyKey(),
                command.requestHash(), clock.instant()
        ));
        return new ConversationCommandOutcome<>(summary, List.of(), false);
    }

    @Override
    @Transactional
    public ConversationCommandOutcome<com.dianlian.platform.interaction.api.ConversationMessageView> send(
            SendConversationMessageCommand command,
            AccessContext accessContext
    ) {
        requirePermission(accessContext, InteractionPermissions.SEND);
        UUID tenantId = accessContext.tenantId().value();
        UUID actorId = accessContext.actorId().value();
        var conversation = repository.lockVisibleConversation(tenantId, actorId, command.conversationId());
        var replay = repository.findMessageIntent(
                tenantId, actorId, command.conversationId(), command.idempotencyKey());
        if (replay.isPresent()) {
            requireSameHash(replay.get().requestHash(), command.requestHash());
            return new ConversationCommandOutcome<>(
                    replay.get().message(),
                    repository.listInvocationIds(tenantId, replay.get().message().messageId()),
                    true
            );
        }
        if (conversation.membershipVersion() != command.expectedMembershipVersion()) {
            throw new ConversationCommandConflictException(
                    "CONVERSATION_MEMBERSHIP_CHANGED",
                    "conversation membership changed; refresh before sending"
            );
        }
        if (command.replyToMessageId() != null) {
            repository.requireReplyMessage(tenantId, command.conversationId(), command.replyToMessageId());
        }

        var targets = normalizeTargets(command, conversation);
        validateCollaboration(command, targets);
        if (!targets.isEmpty()) requirePermission(accessContext, InteractionPermissions.INVOKE_AGENT);
        for (MessageTargetInput target : targets) {
            if (target.triggerType() == MessageTriggerType.REPLY) {
                repository.requireReplyMessageFromAgent(
                        tenantId,
                        command.conversationId(),
                        target.replyToMessageId(),
                        target.enterpriseAgentId()
                );
            }
        }

        UUID messageId = UUID.randomUUID();
        var message = repository.appendHumanMessage(new ConversationRepository.AppendHumanMessageWrite(
                messageId, tenantId, actorId, command.conversationId(), command.clientMessageId(),
                command.idempotencyKey(), command.requestHash(), command.text(), command.replyToMessageId(),
                command.collaborationMode(), command.primaryAgentId(), clock.instant()
        ));
        repository.appendAccessSnapshot(new ConversationRepository.AppendAccessSnapshotWrite(
                messageId, tenantId, command.conversationId(), conversation.membershipVersion(),
                conversation.historyFloorSequenceNo(),
                conversation.humanMemberIds(), conversation.agentIds(),
                "tenant:" + tenantId + ":membership:" + conversation.membershipVersion(),
                POLICY_VERSION, clock.instant()
        ));

        var queued = new ArrayList<UUID>();
        for (MessageTargetInput target : targets) {
            ExecutableAgentSummary agent = executableAgentQuery.requireExecutableForTask(
                    target.enterpriseAgentId(), accessContext);
            var route = modelRouteQuery.resolve(
                    tenantId,
                    agent.enterpriseAgentId(),
                    ModelCapabilityType.TEXT_CHAT,
                    routePreference(agent.modelPolicyMode())
            );
            UUID invocationId = UUID.randomUUID();
            var reservation = pointReservationService.reserve(new ReservePointsCommand(
                    "AI_INVOCATION",
                    invocationId,
                    "TENANT",
                    tenantId,
                    route.model().reservationCeilingMicroCredit(),
                    "ai-invocation:" + invocationId
            ), accessContext);
            UUID targetId = repository.appendTarget(new ConversationRepository.AppendTargetWrite(
                    UUID.randomUUID(), tenantId, command.conversationId(), messageId,
                    agent.enterpriseAgentId(), target.triggerType(), target.replyToMessageId(), clock.instant()
            ));
            repository.appendInvocation(new ConversationRepository.AppendInvocationWrite(
                    invocationId, tenantId, command.conversationId(), messageId, targetId, actorId,
                    agent.enterpriseAgentId(), agent.agentVersionId(), agent.configurationVersionId(),
                    agent.roleName(), agent.profile(), agent.enterpriseInstructions(),
                    agent.knowledgeScopeMode().name(), route, reservation.reservationId(), clock.instant()
            ));
            queued.add(invocationId);
        }
        return new ConversationCommandOutcome<>(message, queued, false);
    }

    @Override
    @Transactional(readOnly = true)
    public List<ConversationSummary> list(AccessContext accessContext) {
        requirePermission(accessContext, InteractionPermissions.READ);
        return repository.listVisible(accessContext.tenantId().value(), accessContext.actorId().value(), 200);
    }

    @Override
    @Transactional(readOnly = true)
    public ConversationMessagePage messages(
            UUID conversationId,
            long afterSequenceNo,
            int limit,
            AccessContext accessContext
    ) {
        requirePermission(accessContext, InteractionPermissions.READ);
        if (afterSequenceNo < 0 || limit < 1 || limit > 200) {
            throw new IllegalArgumentException("message cursor or limit is invalid");
        }
        return repository.listMessages(
                accessContext.tenantId().value(), accessContext.actorId().value(),
                conversationId, afterSequenceNo, limit
        );
    }

    private static List<MessageTargetInput> normalizeTargets(
            SendConversationMessageCommand command,
            ConversationRepository.ConversationState conversation
    ) {
        var byAgent = new LinkedHashMap<UUID, MessageTargetInput>();
        for (MessageTargetInput target : command.targets()) {
            if (target.triggerType() == MessageTriggerType.REPLY
                    && !Objects.equals(target.replyToMessageId(), command.replyToMessageId())) {
                throw new IllegalArgumentException("reply target must reference the replied conversation message");
            }
            if (!conversation.agentIds().contains(target.enterpriseAgentId())) {
                throw new ConversationCommandConflictException(
                        "AGENT_NOT_BOUND_TO_CONVERSATION",
                        "target digital employee is not available in this conversation"
                );
            }
            if (byAgent.putIfAbsent(target.enterpriseAgentId(), target) != null) {
                throw new IllegalArgumentException("duplicate digital employee target");
            }
        }
        if (conversation.type() == ConversationType.DIRECT && conversation.agentIds().size() == 1) {
            UUID boundAgentId = conversation.agentIds().getFirst();
            if (byAgent.isEmpty()) {
                byAgent.put(boundAgentId, new MessageTargetInput(boundAgentId, MessageTriggerType.DIRECT, null));
            }
        }
        return List.copyOf(byAgent.values());
    }

    private static void validateCollaboration(
            SendConversationMessageCommand command,
            List<MessageTargetInput> targets
    ) {
        if (command.collaborationMode() == null) {
            throw new IllegalArgumentException("collaborationMode must not be null");
        }
        if (targets.size() <= 1 && command.collaborationMode() != ConversationCollaborationMode.SINGLE_TARGET) {
            throw new ConversationCommandConflictException(
                    "COLLABORATION_MODE_TARGET_MISMATCH",
                    "zero or one target requires SINGLE_TARGET"
            );
        }
        if (targets.size() > 1 && command.collaborationMode() == ConversationCollaborationMode.SINGLE_TARGET) {
            throw new ConversationCommandConflictException(
                    "MULTIPLE_TARGETS_REQUIRE_MODE",
                    "multiple digital employees require an explicit collaboration mode"
            );
        }
        if (command.collaborationMode() == ConversationCollaborationMode.PRIMARY_SUMMARY) {
            if (command.primaryAgentId() == null
                    || targets.stream().noneMatch(target -> target.enterpriseAgentId().equals(command.primaryAgentId()))) {
                throw new ConversationCommandConflictException(
                        "PRIMARY_AGENT_REQUIRED",
                        "PRIMARY_SUMMARY requires a selected primary digital employee"
                );
            }
            throw new ConversationCommandConflictException(
                    "PRIMARY_SUMMARY_REQUIRES_TASK",
                    "primary-summary collaboration must be created as a controlled task"
            );
        }
        if (command.primaryAgentId() != null) {
            throw new IllegalArgumentException("primaryAgentId is only valid for PRIMARY_SUMMARY");
        }
    }

    private static ModelRoutePreference routePreference(EnterpriseAgentModelPolicyMode policyMode) {
        return switch (policyMode) {
            case PLATFORM_DEFAULT -> ModelRoutePreference.PLATFORM_ONLY;
            case AGENT_ROUTE -> ModelRoutePreference.AGENT_ONLY;
        };
    }

    private static void validateShape(ConversationType type, int humanCount, int agentCount) {
        if (type == ConversationType.DIRECT) {
            boolean humanDirect = humanCount == 2 && agentCount == 0;
            boolean agentDirect = humanCount == 1 && agentCount == 1;
            if (!humanDirect && !agentDirect) {
                throw new IllegalArgumentException("DIRECT must contain exactly two humans or one human and one digital employee");
            }
            return;
        }
        if (humanCount + agentCount < 2) {
            throw new IllegalArgumentException("GROUP requires at least two participants");
        }
    }

    private static void requirePermission(AccessContext accessContext, String permission) {
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        if (!accessContext.authorities().contains(permission)) {
            throw new InteractionAccessDeniedException(permission);
        }
    }

    private static void requireSameHash(String storedHash, String requestHash) {
        if (!Objects.equals(storedHash, requestHash)) {
            throw new ConversationCommandConflictException(
                    "IDEMPOTENCY_KEY_REUSED",
                    "idempotency key was already used for another request"
            );
        }
    }
}

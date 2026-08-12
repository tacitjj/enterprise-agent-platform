package com.dianlian.platform.interaction.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.fail;

import com.dianlian.platform.billing.api.PointReservationResult;
import com.dianlian.platform.billing.api.PointReservationService;
import com.dianlian.platform.billing.api.ReservePointsCommand;
import com.dianlian.platform.employee.api.AgentVersionStatus;
import com.dianlian.platform.employee.api.EnterpriseAgentKnowledgeScopeMode;
import com.dianlian.platform.employee.api.EnterpriseAgentModelPolicyMode;
import com.dianlian.platform.employee.api.EnterpriseAgentStatus;
import com.dianlian.platform.employee.api.ExecutableAgentQuery;
import com.dianlian.platform.employee.api.ExecutableAgentSummary;
import com.dianlian.platform.employee.api.ExecutionExecutorType;
import com.dianlian.platform.employee.api.ExecutionStepDescriptor;
import com.dianlian.platform.employee.api.ExecutionTemplateDescriptor;
import com.dianlian.platform.employee.api.InputSchemaDescriptor;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.TenantId;
import com.dianlian.platform.interaction.api.ConversationCollaborationMode;
import com.dianlian.platform.interaction.api.ConversationMessagePage;
import com.dianlian.platform.interaction.api.ConversationMessageView;
import com.dianlian.platform.interaction.api.ConversationStatus;
import com.dianlian.platform.interaction.api.ConversationSummary;
import com.dianlian.platform.interaction.api.ConversationType;
import com.dianlian.platform.interaction.api.InteractionPermissions;
import com.dianlian.platform.interaction.api.MessageSenderType;
import com.dianlian.platform.interaction.api.MessageTargetInput;
import com.dianlian.platform.interaction.api.MessageTriggerType;
import com.dianlian.platform.interaction.api.SendConversationMessageCommand;
import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.ModelDefinitionStatus;
import com.dianlian.platform.model.api.ModelDefinitionView;
import com.dianlian.platform.model.api.ModelRoutePreference;
import com.dianlian.platform.model.api.ModelRouteQuery;
import com.dianlian.platform.model.api.ResolvedModelRoute;
import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class ConversationApplicationServiceTests {

    private static final Instant NOW = Instant.parse("2026-08-11T08:00:00Z");
    private static final UUID TENANT_ID = UUID.fromString("00000000-0000-0000-0000-000000000001");
    private static final UUID ACTOR_ID = UUID.fromString("00000000-0000-0000-0000-000000000011");
    private static final UUID OTHER_USER_ID = UUID.fromString("00000000-0000-0000-0000-000000000012");
    private static final UUID AGENT_ID = UUID.fromString("00000000-0000-0000-0000-000000000121");
    private static final UUID CONVERSATION_ID = UUID.fromString("00000000-0000-0000-0000-000000000201");

    @Test
    void ordinaryGroupMessagePersistsWithoutModelRouteReservationOrInvocation() {
        var repository = new RecordingRepository(new ConversationRepository.ConversationState(
                CONVERSATION_ID, TENANT_ID, ConversationType.GROUP, 1, 0,
                List.of(ACTOR_ID, OTHER_USER_ID), List.of(AGENT_ID)));
        var service = service(repository, unreachableAgentQuery(), unreachableModelRoute(), unreachableReservation());

        var outcome = service.send(command(List.of(), 1, "ordinary-group-message"), access(
                InteractionPermissions.SEND));

        assertThat(outcome.queuedInvocationIds()).isEmpty();
        assertThat(repository.appendedMessages).isEqualTo(1);
        assertThat(repository.appendedAccessSnapshots).isEqualTo(1);
        assertThat(repository.appendedTargets).isZero();
        assertThat(repository.appendedInvocations).isZero();
    }

    @Test
    void directAgentMessageFreezesRoleModelAndPointReservation() {
        var repository = new RecordingRepository(new ConversationRepository.ConversationState(
                CONVERSATION_ID, TENANT_ID, ConversationType.DIRECT, 1, 0,
                List.of(ACTOR_ID), List.of(AGENT_ID)));
        var reservation = new RecordingReservation();
        var service = service(repository, agentQuery(), modelRoute(), reservation);

        var outcome = service.send(command(List.of(), 1, "direct-agent-message"), access(
                InteractionPermissions.SEND, InteractionPermissions.INVOKE_AGENT));

        assertThat(outcome.queuedInvocationIds()).hasSize(1);
        assertThat(repository.appendedTargets).isEqualTo(1);
        assertThat(repository.appendedInvocations).isEqualTo(1);
        assertThat(repository.lastInvocation.enterpriseAgentId()).isEqualTo(AGENT_ID);
        assertThat(repository.lastInvocation.roleName()).isEqualTo("法务合同审核");
        assertThat(repository.lastInvocation.route().routeSource()).isEqualTo("PLATFORM");
        assertThat(reservation.lastCommand.businessType()).isEqualTo("AI_INVOCATION");
        assertThat(reservation.lastCommand.amount()).isEqualTo(500_000);
    }

    @Test
    void exactIdempotentReplayWinsOverLaterMembershipVersionChange() {
        var repository = new RecordingRepository(new ConversationRepository.ConversationState(
                CONVERSATION_ID, TENANT_ID, ConversationType.GROUP, 2, 0,
                List.of(ACTOR_ID, OTHER_USER_ID), List.of()));
        repository.replayedMessage = message();
        var service = service(repository, unreachableAgentQuery(), unreachableModelRoute(), unreachableReservation());

        var outcome = service.send(command(List.of(), 1, "stable-replay"), access(
                InteractionPermissions.SEND));

        assertThat(outcome.replayed()).isTrue();
        assertThat(outcome.resource().messageId()).isEqualTo(repository.replayedMessage.messageId());
        assertThat(repository.appendedMessages).isZero();
    }

    @Test
    void replyTargetMustResolveToTheSelectedDigitalEmployeeMessage() {
        var replyMessageId = UUID.fromString("00000000-0000-0000-0000-000000000211");
        var repository = new RecordingRepository(new ConversationRepository.ConversationState(
                CONVERSATION_ID, TENANT_ID, ConversationType.GROUP, 1, 0,
                List.of(ACTOR_ID, OTHER_USER_ID), List.of(AGENT_ID)));
        var command = new SendConversationMessageCommand(
                CONVERSATION_ID,
                "client-reply",
                "请继续说明",
                List.of(new MessageTargetInput(AGENT_ID, MessageTriggerType.REPLY, replyMessageId)),
                ConversationCollaborationMode.SINGLE_TARGET,
                null,
                replyMessageId,
                1,
                "reply-message",
                "hash-reply-message"
        );

        service(repository, agentQuery(), modelRoute(), new RecordingReservation()).send(
                command,
                access(InteractionPermissions.SEND, InteractionPermissions.INVOKE_AGENT)
        );

        assertThat(repository.verifiedReplyMessageId).isEqualTo(replyMessageId);
        assertThat(repository.verifiedReplyAgentId).isEqualTo(AGENT_ID);
    }

    private static ConversationApplicationService service(
            ConversationRepository repository,
            ExecutableAgentQuery agentQuery,
            ModelRouteQuery modelRouteQuery,
            PointReservationService pointReservationService
    ) {
        return new ConversationApplicationService(
                repository,
                agentQuery,
                modelRouteQuery,
                pointReservationService,
                Clock.fixed(NOW, ZoneOffset.UTC)
        );
    }

    private static SendConversationMessageCommand command(
            List<com.dianlian.platform.interaction.api.MessageTargetInput> targets,
            long expectedMembershipVersion,
            String idempotencyKey
    ) {
        return new SendConversationMessageCommand(
                CONVERSATION_ID,
                "client-" + idempotencyKey,
                "请处理这条消息",
                targets,
                ConversationCollaborationMode.SINGLE_TARGET,
                null,
                null,
                expectedMembershipVersion,
                idempotencyKey,
                "hash-" + idempotencyKey
        );
    }

    private static AccessContext access(String... permissions) {
        var principal = new AuthenticatedPrincipal(
                UUID.fromString("00000000-0000-0000-0000-000000000901"),
                new ActorId(ACTOR_ID),
                "测试用户",
                null,
                SessionView.AccountStatus.ACTIVE,
                new SessionView.Tenant(
                        new TenantId(TENANT_ID),
                        "测试企业",
                        SessionView.TenantStatus.ACTIVE,
                        SessionView.MembershipStatus.ACTIVE
                ),
                List.of(),
                Set.of(permissions),
                "permission-v1",
                NOW,
                NOW.plusSeconds(900)
        );
        return AccessContext.fromAuthenticatedPrincipal(principal);
    }

    private static ExecutableAgentQuery agentQuery() {
        return new ExecutableAgentQuery() {
            @Override
            public List<ExecutableAgentSummary> listExecutableForOffice(AccessContext accessContext) {
                return List.of(agent());
            }

            @Override
            public ExecutableAgentSummary requireExecutableForTask(UUID enterpriseAgentId, AccessContext accessContext) {
                assertThat(enterpriseAgentId).isEqualTo(AGENT_ID);
                return agent();
            }

            @Override
            public ExecutableAgentSummary requireExecutableForTask(
                    UUID enterpriseAgentId,
                    String requiredCapabilityCode,
                    AccessContext accessContext
            ) {
                return requireExecutableForTask(enterpriseAgentId, accessContext);
            }
        };
    }

    private static ExecutableAgentQuery unreachableAgentQuery() {
        return new ExecutableAgentQuery() {
            @Override
            public List<ExecutableAgentSummary> listExecutableForOffice(AccessContext accessContext) {
                fail("ordinary human message must not query a digital employee");
                return List.of();
            }

            @Override
            public ExecutableAgentSummary requireExecutableForTask(UUID enterpriseAgentId, AccessContext accessContext) {
                fail("ordinary human message must not query a digital employee");
                return null;
            }

            @Override
            public ExecutableAgentSummary requireExecutableForTask(
                    UUID enterpriseAgentId,
                    String requiredCapabilityCode,
                    AccessContext accessContext
            ) {
                fail("ordinary human message must not query a digital employee");
                return null;
            }
        };
    }

    private static ModelRouteQuery modelRoute() {
        return new ModelRouteQuery() {
            @Override
            public ResolvedModelRoute resolve(
                    UUID tenantId,
                    UUID enterpriseAgentId,
                    ModelCapabilityType capabilityType,
                    ModelRoutePreference preference
            ) {
                assertThat(preference).isEqualTo(ModelRoutePreference.PLATFORM_ONLY);
                return route();
            }

            @Override
            public ResolvedModelRoute requireSnapshot(UUID routeBindingId, UUID modelDefinitionId) {
                return route();
            }
        };
    }

    private static ModelRouteQuery unreachableModelRoute() {
        return new ModelRouteQuery() {
            @Override
            public ResolvedModelRoute resolve(
                    UUID tenantId,
                    UUID enterpriseAgentId,
                    ModelCapabilityType capabilityType,
                    ModelRoutePreference preference
            ) {
                fail("ordinary human message must not resolve a model route");
                return null;
            }

            @Override
            public ResolvedModelRoute requireSnapshot(UUID routeBindingId, UUID modelDefinitionId) {
                fail("ordinary human message must not resolve a model route");
                return null;
            }
        };
    }

    private static PointReservationService unreachableReservation() {
        return (command, accessContext) -> {
            fail("ordinary human message must not reserve points");
            return null;
        };
    }

    private static ExecutableAgentSummary agent() {
        return new ExecutableAgentSummary(
                AGENT_ID,
                UUID.fromString("00000000-0000-0000-0000-000000000122"),
                UUID.fromString("00000000-0000-0000-0000-000000000123"),
                UUID.fromString("00000000-0000-0000-0000-000000000124"),
                "CONTRACT_REVIEW",
                "法务合同审核",
                "法务合同审核",
                "识别合同风险并给出引用依据。",
                "采用本企业法务红线。",
                EnterpriseAgentModelPolicyMode.PLATFORM_DEFAULT,
                EnterpriseAgentKnowledgeScopeMode.ENTERPRISE_AUTHORIZED,
                List.of("合同解析"),
                null,
                "CONTRACT_REVIEW",
                new InputSchemaDescriptor("contract-review-input", "1", "{\"type\":\"object\"}"),
                new ExecutionTemplateDescriptor(
                        "CONTRACT_REVIEW",
                        "1",
                        List.of(new ExecutionStepDescriptor(
                                "review", "审核", ExecutionExecutorType.MODEL,
                                List.of(), null, null, false
                        ))
                ),
                500_000,
                EnterpriseAgentStatus.ACTIVE,
                AgentVersionStatus.PUBLISHED
        );
    }

    private static ResolvedModelRoute route() {
        var definition = new ModelDefinitionView(
                UUID.fromString("00000000-0000-0000-0000-000000000401"),
                "QWEN.PLUS",
                1,
                "通义千问 Plus",
                "ALIBABA",
                "OPENAI_COMPATIBLE",
                "https://example.invalid/v1",
                "qwen-plus",
                "env:DIANLIAN_MODEL_TEST_API_KEY",
                ModelCapabilityType.TEXT_CHAT,
                new BigDecimal("0.20"),
                4096,
                100_000,
                200_000,
                500_000,
                ModelDefinitionStatus.ACTIVE,
                ACTOR_ID,
                NOW
        );
        return new ResolvedModelRoute(
                UUID.fromString("00000000-0000-0000-0000-000000000402"),
                1,
                "PLATFORM",
                definition
        );
    }

    private static ConversationMessageView message() {
        return new ConversationMessageView(
                UUID.fromString("00000000-0000-0000-0000-000000000501"),
                CONVERSATION_ID,
                1,
                MessageSenderType.HUMAN,
                ACTOR_ID,
                null,
                "测试用户",
                null,
                "请处理这条消息",
                null,
                List.of(),
                null,
                null,
                null,
                0,
                NOW
        );
    }

    private static final class RecordingReservation implements PointReservationService {
        private ReservePointsCommand lastCommand;

        @Override
        public PointReservationResult reserve(ReservePointsCommand command, AccessContext accessContext) {
            lastCommand = command;
            return new PointReservationResult(
                    UUID.fromString("00000000-0000-0000-0000-000000000601"),
                    UUID.fromString("00000000-0000-0000-0000-000000000602"),
                    command.amount(),
                    "ACTIVE",
                    NOW,
                    false
            );
        }
    }

    private static final class RecordingRepository implements ConversationRepository {
        private final ConversationState state;
        private ConversationMessageView replayedMessage;
        private int appendedMessages;
        private int appendedAccessSnapshots;
        private int appendedTargets;
        private int appendedInvocations;
        private AppendInvocationWrite lastInvocation;
        private UUID verifiedReplyMessageId;
        private UUID verifiedReplyAgentId;

        private RecordingRepository(ConversationState state) {
            this.state = state;
        }

        @Override
        public Optional<StoredConversationIntent> findConversationIntent(UUID tenantId, UUID actorId, String key) {
            return Optional.empty();
        }

        @Override
        public void requireActiveTenantMembers(UUID tenantId, List<UUID> userIds) {
        }

        @Override
        public ConversationSummary createConversation(CreateConversationWrite write) {
            return summary();
        }

        @Override
        public ConversationState lockVisibleConversation(UUID tenantId, UUID actorId, UUID conversationId) {
            return state;
        }

        @Override
        public Optional<StoredMessageIntent> findMessageIntent(
                UUID tenantId,
                UUID actorId,
                UUID conversationId,
                String idempotencyKey
        ) {
            return Optional.ofNullable(replayedMessage)
                    .map(value -> new StoredMessageIntent(value, "hash-" + idempotencyKey));
        }

        @Override
        public void requireReplyMessage(UUID tenantId, UUID conversationId, UUID replyToMessageId) {
        }

        @Override
        public void requireReplyMessageFromAgent(
                UUID tenantId,
                UUID conversationId,
                UUID replyToMessageId,
                UUID enterpriseAgentId
        ) {
            verifiedReplyMessageId = replyToMessageId;
            verifiedReplyAgentId = enterpriseAgentId;
        }

        @Override
        public ConversationMessageView appendHumanMessage(AppendHumanMessageWrite write) {
            appendedMessages++;
            return message();
        }

        @Override
        public UUID appendTarget(AppendTargetWrite write) {
            appendedTargets++;
            return write.targetId();
        }

        @Override
        public void appendAccessSnapshot(AppendAccessSnapshotWrite write) {
            appendedAccessSnapshots++;
        }

        @Override
        public void appendInvocation(AppendInvocationWrite write) {
            appendedInvocations++;
            lastInvocation = write;
        }

        @Override
        public List<UUID> listInvocationIds(UUID tenantId, UUID sourceMessageId) {
            return List.of();
        }

        @Override
        public List<ConversationSummary> listVisible(UUID tenantId, UUID actorId, int limit) {
            return List.of(summary());
        }

        @Override
        public ConversationMessagePage listMessages(
                UUID tenantId,
                UUID actorId,
                UUID conversationId,
                long afterSequenceNo,
                int limit
        ) {
            return new ConversationMessagePage(List.of(), 0, false, state.membershipVersion());
        }

        private ConversationSummary summary() {
            return new ConversationSummary(
                    CONVERSATION_ID,
                    state.type(),
                    "测试会话",
                    ConversationStatus.ACTIVE,
                    state.membershipVersion(),
                    List.of(),
                    List.of(),
                    null,
                    null,
                    0,
                    List.of("VIEW", "SEND")
            );
        }
    }
}

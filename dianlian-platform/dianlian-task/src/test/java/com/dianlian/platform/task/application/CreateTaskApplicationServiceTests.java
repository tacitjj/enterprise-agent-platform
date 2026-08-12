package com.dianlian.platform.task.application;

import static com.dianlian.platform.identity.api.AccessContextFixtures.ACTOR_ID;
import static com.dianlian.platform.identity.api.AccessContextFixtures.TENANT_ID;
import static com.dianlian.platform.identity.api.AccessContextFixtures.authenticated;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.billing.api.InsufficientPointsException;
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
import com.dianlian.platform.task.api.BillingScopeType;
import com.dianlian.platform.task.api.CapabilityInput;
import com.dianlian.platform.task.api.CollaborationMode;
import com.dianlian.platform.task.api.CreateTaskCommand;
import com.dianlian.platform.task.api.IdempotencyRequestConflictException;
import com.dianlian.platform.task.api.TaskAdmissionRejectedException;
import com.dianlian.platform.task.api.TaskOwnership;
import com.dianlian.platform.task.infrastructure.JacksonCapabilityInputValidator;
import com.dianlian.platform.task.infrastructure.JacksonTaskPayloadSerializer;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class CreateTaskApplicationServiceTests {

    private static final UUID AGENT_ID = UUID.fromString("10000000-0000-0000-0000-000000000001");
    private static final UUID AGENT_VERSION_ID = UUID.fromString("20000000-0000-0000-0000-000000000001");
    private static final UUID CONFIGURATION_VERSION_ID =
            UUID.fromString("50000000-0000-0000-0000-000000000001");
    private static final Instant NOW = Instant.parse("2026-01-02T03:04:05Z");

    @Test
    void replaysTheCompleteFirstResultWithoutASecondReservationOrTask() {
        var fixture = new Fixture(false);
        var command = validCommand("task-create-request-0001", "Prepare a customer deliverable");

        var first = fixture.service.create(command, authenticated());
        var replay = fixture.service.create(command, authenticated());

        assertThat(replay.taskId()).isEqualTo(first.taskId());
        assertThat(replay.acceptedAt()).isEqualTo(first.acceptedAt());
        assertThat(replay.resumeEventId()).isEqualTo(first.resumeEventId());
        assertThat(replay.idempotencyReplayed()).isTrue();
        assertThat(fixture.points.calls).isEqualTo(1);
        assertThat(fixture.repository.insertCalls).isEqualTo(1);
    }

    @Test
    void rejectsTheSameIdempotencyKeyForADifferentRequestHash() {
        var fixture = new Fixture(false);
        fixture.service.create(
                validCommand("task-create-request-0002", "Prepare version A"),
                authenticated()
        );

        assertThatThrownBy(() -> fixture.service.create(
                validCommand("task-create-request-0002", "Prepare version B"),
                authenticated()
        )).isInstanceOf(IdempotencyRequestConflictException.class);
        assertThat(fixture.points.calls).isEqualTo(1);
        assertThat(fixture.repository.insertCalls).isEqualTo(1);
    }

    @Test
    void doesNotInsertATaskWhenThePointBalanceIsInsufficient() {
        var fixture = new Fixture(true);

        assertThatThrownBy(() -> fixture.service.create(
                validCommand("task-create-request-0003", "Prepare an expensive deliverable"),
                authenticated()
        )).isInstanceOf(InsufficientPointsException.class);
        assertThat(fixture.repository.insertCalls).isZero();
    }

    @Test
    void validatesCapabilityValuesBeforeReservingPoints() {
        var fixture = new Fixture(false);
        var invalid = validCommand("task-create-request-0004", "Prepare a deliverable", Map.of());

        assertThatThrownBy(() -> fixture.service.create(invalid, authenticated()))
                .isInstanceOfSatisfying(TaskAdmissionRejectedException.class, exception ->
                        assertThat(exception.errorCode()).isEqualTo("CAPABILITY_INPUT_INVALID")
                );
        assertThat(fixture.points.calls).isZero();
        assertThat(fixture.repository.insertCalls).isZero();
    }

    @Test
    void storesTheExecutionProfileAsAVersionedJsonObject() throws Exception {
        var fixture = new Fixture(false);

        fixture.service.create(
                validCommand("task-create-request-0005", "Prepare a versioned snapshot"),
                authenticated()
        );

        var storedCreation = fixture.repository.intents.values().iterator().next().creation();
        var snapshot = new ObjectMapper().readTree(storedCreation.executionProfileJson());
        assertThat(snapshot.isObject()).isTrue();
        assertThat(snapshot.path("schemaVersion").asInt()).isEqualTo(1);
        assertThat(snapshot.path("agents").isArray()).isTrue();
        assertThat(snapshot.path("agents")).hasSize(1);
        assertThat(snapshot.path("agents").get(0).path("configurationVersionId").asText())
                .isEqualTo(CONFIGURATION_VERSION_ID.toString());
        assertThat(snapshot.path("agents").get(0).path("enterpriseInstructions").asText())
                .isEqualTo("Use only data authorized for this enterprise.");
        assertThat(storedCreation.response().status()).isEqualTo(com.dianlian.platform.task.api.TaskStatus.QUEUED);
        assertThat(storedCreation.steps()).extracting(TaskStepCreation::status)
                .containsExactly("READY", "PENDING");
        assertThat(storedCreation.steps()).extracting(TaskStepCreation::executorType)
                .containsExactly(ExecutionExecutorType.MODEL, ExecutionExecutorType.HUMAN_CHECKPOINT);
    }

    @Test
    void rejectsTaskCreationWithoutTaskCreatePermissionBeforeClaimOrReservation() {
        var fixture = new Fixture(false);

        assertThatThrownBy(() -> fixture.service.create(
                validCommand("task-create-request-0006", "Attempt an unauthorized task"),
                authenticated(Set.of("enterprise.employee.execute"))
        )).isInstanceOf(com.dianlian.platform.task.api.TaskAccessDeniedException.class);

        assertThat(fixture.points.calls).isZero();
        assertThat(fixture.repository.intents).isEmpty();
        assertThat(fixture.repository.insertCalls).isZero();
    }

    private static CreateTaskCommand validCommand(String idempotencyKey, String goal) {
        return validCommand(idempotencyKey, goal, Map.of("subject", "Autumn campaign"));
    }

    private static CreateTaskCommand validCommand(
            String idempotencyKey,
            String goal,
            Map<String, Object> capabilityValues
    ) {
        return new CreateTaskCommand(
                idempotencyKey,
                null,
                null,
                null,
                goal,
                List.of(),
                List.of(),
                CollaborationMode.SINGLE_TARGET,
                List.of(AGENT_ID),
                null,
                new TaskOwnership(ACTOR_ID, null, BillingScopeType.TENANT, TENANT_ID),
                100,
                new CapabilityInput("generic.task.input", "1", capabilityValues),
                "DOCUMENT"
        );
    }

    private static ExecutableAgentSummary executionProfile() {
        var schema = new InputSchemaDescriptor(
                "generic.task.input",
                "1",
                """
                {
                  "type": "object",
                  "additionalProperties": false,
                  "required": ["subject"],
                  "properties": {
                    "subject": {"type": "string", "minLength": 1, "maxLength": 100}
                  }
                }
                """
        );
        var template = new ExecutionTemplateDescriptor(
                "generic.task.execution",
                "1",
                List.of(
                        new ExecutionStepDescriptor(
                                "prepare",
                                "Prepare",
                                ExecutionExecutorType.MODEL,
                                List.of(),
                                "generic.task.input",
                                "generic.task.draft",
                                false
                        ),
                        new ExecutionStepDescriptor(
                                "confirm",
                                "Confirm",
                                ExecutionExecutorType.HUMAN_CHECKPOINT,
                                List.of("prepare"),
                                "generic.task.draft",
                                "generic.task.confirmed",
                                true
                        )
                )
        );
        return new ExecutableAgentSummary(
                AGENT_ID,
                UUID.fromString("30000000-0000-0000-0000-000000000001"),
                AGENT_VERSION_ID,
                CONFIGURATION_VERSION_ID,
                "generic.employee",
                "General specialist",
                "General specialist",
                "Handles a generic deterministic task flow",
                "Use only data authorized for this enterprise.",
                EnterpriseAgentModelPolicyMode.PLATFORM_DEFAULT,
                EnterpriseAgentKnowledgeScopeMode.NONE,
                List.of("Preparation", "Confirmation"),
                null,
                "GENERIC_TASK",
                schema,
                template,
                40,
                EnterpriseAgentStatus.ACTIVE,
                AgentVersionStatus.PUBLISHED
        );
    }

    private static final class Fixture {

        private final InMemoryTaskRepository repository = new InMemoryTaskRepository();
        private final RecordingPointReservationService points;
        private final CreateTaskApplicationService service;

        private Fixture(boolean insufficientPoints) {
            var objectMapper = new ObjectMapper();
            var serializer = new JacksonTaskPayloadSerializer(objectMapper);
            points = new RecordingPointReservationService(insufficientPoints);
            service = new CreateTaskApplicationService(
                    new FixedExecutableAgentQuery(executionProfile()),
                    points,
                    repository,
                    serializer,
                    new JacksonCapabilityInputValidator(objectMapper),
                    Clock.fixed(NOW, ZoneOffset.UTC)
            );
        }
    }

    private static final class FixedExecutableAgentQuery implements ExecutableAgentQuery {

        private final ExecutableAgentSummary profile;

        private FixedExecutableAgentQuery(ExecutableAgentSummary profile) {
            this.profile = profile;
        }

        @Override
        public List<ExecutableAgentSummary> listExecutableForOffice(AccessContext accessContext) {
            return List.of(profile);
        }

        @Override
        public ExecutableAgentSummary requireExecutableForTask(
                UUID enterpriseAgentId,
                AccessContext accessContext
        ) {
            return profile;
        }

        @Override
        public ExecutableAgentSummary requireExecutableForTask(
                UUID enterpriseAgentId,
                String requiredCapabilityCode,
                AccessContext accessContext
        ) {
            return profile;
        }
    }

    private static final class RecordingPointReservationService implements PointReservationService {

        private final boolean insufficient;
        private int calls;

        private RecordingPointReservationService(boolean insufficient) {
            this.insufficient = insufficient;
        }

        @Override
        public PointReservationResult reserve(ReservePointsCommand command, AccessContext accessContext) {
            calls++;
            if (insufficient) {
                throw new InsufficientPointsException(10, command.amount());
            }
            return new PointReservationResult(
                    UUID.fromString("40000000-0000-0000-0000-000000000001"),
                    UUID.fromString("50000000-0000-0000-0000-000000000001"),
                    command.amount(),
                    "ACTIVE",
                    NOW,
                    false
            );
        }
    }

    private static final class InMemoryTaskRepository implements TaskCreationRepository {

        private final Map<String, StoredIntent> intents = new HashMap<>();
        private String claimedKey;
        private String claimedHash;
        private int insertCalls;

        @Override
        public IdempotencyDecision claim(
                UUID tenantId,
                UUID actorId,
                String idempotencyKey,
                String requestHash,
                Instant occurredAt
        ) {
            var existing = intents.get(idempotencyKey);
            if (existing != null) {
                if (!existing.requestHash.equals(requestHash)) {
                    throw new IdempotencyRequestConflictException();
                }
                return IdempotencyDecision.replay(existing.creation.response());
            }
            claimedKey = idempotencyKey;
            claimedHash = requestHash;
            return IdempotencyDecision.newClaim();
        }

        @Override
        public void insert(TaskCreation creation) {
            insertCalls++;
            intents.put(claimedKey, new StoredIntent(claimedHash, creation));
        }

        private record StoredIntent(String requestHash, TaskCreation creation) {
        }
    }
}

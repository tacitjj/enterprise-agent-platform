package com.dianlian.platform.task.application;

import static com.dianlian.platform.identity.api.AccessContextFixtures.ACTOR_ID;
import static com.dianlian.platform.identity.api.AccessContextFixtures.TENANT_ID;
import static com.dianlian.platform.identity.api.AccessContextFixtures.authenticated;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.task.api.TaskAccessDeniedException;
import com.dianlian.platform.task.api.TaskNotFoundException;
import com.dianlian.platform.task.api.TaskPermissions;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class TaskEventStreamApplicationServiceTests {

    private static final UUID TASK_ID = UUID.fromString("10000000-0000-0000-0000-000000000001");
    private static final UUID CURSOR_EVENT_ID = UUID.fromString("20000000-0000-0000-0000-000000000000");
    private static final UUID FIRST_EVENT_ID = UUID.fromString("20000000-0000-0000-0000-000000000001");
    private static final UUID SECOND_EVENT_ID = UUID.fromString("20000000-0000-0000-0000-000000000002");
    private static final Instant NOW = Instant.parse("2026-08-11T02:00:00Z");

    @Test
    void replaysPersistedEventsAfterResolvedCursorInStreamSequenceOrder() {
        var repository = visibleRepository();
        repository.cursor = Optional.of(new TaskEventQueryRepository.TaskEventCursor(10, "participants:v1"));
        repository.events.add(event(12, SECOND_EVENT_ID));
        repository.events.add(event(11, FIRST_EVENT_ID));
        repository.events.sort(java.util.Comparator.comparingLong(
                TaskEventQueryRepository.PersistedTaskEvent::streamSequence
        ));
        var service = service(repository);

        var batch = service.read(TASK_ID, CURSOR_EVENT_ID.toString(), 100, readAccess());

        assertThat(batch.resetRequired()).isFalse();
        assertThat(batch.events()).extracting(event -> event.eventId())
                .containsExactly(FIRST_EVENT_ID.toString(), SECOND_EVENT_ID.toString());
        assertThat(batch.events()).allSatisfy(event -> {
            assertThat(event.streamType()).isEqualTo("TASK");
            assertThat(event.streamId()).isEqualTo(TASK_ID.toString());
            assertThat(event.aggregateType()).isEqualTo("TASK");
            assertThat(event.eventType()).isEqualTo("task.snapshot.invalidated");
            assertThat(event.payload()).containsExactlyInAnyOrderEntriesOf(Map.of(
                    "taskId", TASK_ID,
                    "reason", "TASK_CHANGED"
            ));
        });
        assertThat(repository.lastTenantId).isEqualTo(TENANT_ID);
        assertThat(repository.lastActorId).isEqualTo(ACTOR_ID);
        assertThat(repository.lastAfterSequence).isEqualTo(10);
        assertThat(repository.lastLimit).isEqualTo(100);
    }

    @Test
    void returnsResetNotificationForUnknownOrExpiredCursor() {
        var repository = visibleRepository();
        repository.cursor = Optional.empty();

        var batch = service(repository).read(TASK_ID, "expired:event", 100, readAccess());

        assertThat(batch.resetRequired()).isTrue();
        assertThat(batch.events()).singleElement().satisfies(event -> {
            assertThat(event.eventType()).isEqualTo("stream.reset_required");
            assertThat(event.aggregateType()).isEqualTo("STREAM");
            assertThat(event.payload()).containsEntry("reason", "CURSOR_EXPIRED");
            assertThat(event.payload()).containsEntry("recoveryResource", "/api/v1/tasks/" + TASK_ID);
        });
        assertThat(repository.findEventsCalls).isZero();
    }

    @Test
    void returnsResetWhenCursorVisibilityVersionNoLongerMatchesCurrentStream() {
        var repository = visibleRepository();
        repository.cursor = Optional.of(new TaskEventQueryRepository.TaskEventCursor(10, "participants:v0"));

        var batch = service(repository).read(TASK_ID, CURSOR_EVENT_ID.toString(), 100, readAccess());

        assertThat(batch.resetRequired()).isTrue();
        assertThat(batch.events().getFirst().payload()).containsEntry("reason", "VISIBILITY_CHANGED");
        assertThat(repository.findEventsCalls).isZero();
    }

    @Test
    void requiresReadPermissionBeforeLookingUpTaskOrEvents() {
        var repository = visibleRepository();

        assertThatThrownBy(() -> service(repository).read(
                TASK_ID,
                null,
                100,
                authenticated(Set.of(TaskPermissions.CREATE))
        )).isInstanceOf(TaskAccessDeniedException.class);

        assertThat(repository.findStateCalls).isZero();
        assertThat(repository.findEventsCalls).isZero();
    }

    @Test
    void hidesMissingOrRevokedParticipantAsNonDiscoverable() {
        var repository = visibleRepository();
        repository.state = Optional.empty();

        assertThatThrownBy(() -> service(repository).read(TASK_ID, null, 100, readAccess()))
                .isInstanceOf(TaskNotFoundException.class);

        assertThat(repository.findEventsCalls).isZero();
    }

    private static TaskEventStreamApplicationService service(FakeRepository repository) {
        return new TaskEventStreamApplicationService(
                repository,
                Clock.fixed(NOW, ZoneOffset.UTC)
        );
    }

    private static com.dianlian.platform.identity.api.AccessContext readAccess() {
        return authenticated(Set.of(TaskPermissions.READ));
    }

    private static FakeRepository visibleRepository() {
        var repository = new FakeRepository();
        repository.state = Optional.of(new TaskEventQueryRepository.TaskStreamState(7, "participants:v1"));
        return repository;
    }

    private static TaskEventQueryRepository.PersistedTaskEvent event(
            long sequence,
            UUID eventId
    ) {
        return new TaskEventQueryRepository.PersistedTaskEvent(
                sequence,
                eventId,
                TASK_ID,
                7,
                "participants:v1",
                UUID.fromString("30000000-0000-0000-0000-000000000001"),
                NOW.plusSeconds(sequence)
        );
    }

    private static final class FakeRepository implements TaskEventQueryRepository {
        private Optional<TaskStreamState> state = Optional.empty();
        private Optional<TaskEventCursor> cursor = Optional.empty();
        private final List<PersistedTaskEvent> events = new ArrayList<>();
        private int findStateCalls;
        private int findEventsCalls;
        private UUID lastTenantId;
        private UUID lastActorId;
        private long lastAfterSequence;
        private int lastLimit;

        @Override
        public Optional<TaskStreamState> findVisibleState(UUID tenantId, UUID actorId, UUID taskId) {
            findStateCalls++;
            lastTenantId = tenantId;
            lastActorId = actorId;
            return TASK_ID.equals(taskId) ? state : Optional.empty();
        }

        @Override
        public Optional<TaskEventCursor> findCursor(UUID tenantId, UUID taskId, String eventId) {
            return TASK_ID.equals(taskId) ? cursor : Optional.empty();
        }

        @Override
        public List<PersistedTaskEvent> findVisibleAfter(
                UUID tenantId,
                UUID actorId,
                UUID taskId,
                long streamSequence,
                int limit
        ) {
            findEventsCalls++;
            lastTenantId = tenantId;
            lastActorId = actorId;
            lastAfterSequence = streamSequence;
            lastLimit = limit;
            return events.stream()
                    .filter(event -> event.streamSequence() > streamSequence)
                    .limit(limit)
                    .toList();
        }
    }
}

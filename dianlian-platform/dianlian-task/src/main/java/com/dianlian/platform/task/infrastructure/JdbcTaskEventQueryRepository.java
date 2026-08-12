package com.dianlian.platform.task.infrastructure;

import com.dianlian.platform.task.application.TaskEventQueryRepository;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcTaskEventQueryRepository implements TaskEventQueryRepository {

    private final JdbcTemplate jdbcTemplate;

    public JdbcTaskEventQueryRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = Objects.requireNonNull(jdbcTemplate, "jdbcTemplate must not be null");
    }

    @Override
    public Optional<TaskStreamState> findVisibleState(UUID tenantId, UUID actorId, UUID taskId) {
        var rows = jdbcTemplate.query(
                """
                SELECT task.task_version,
                       COALESCE(latest_event.visibility_version, 'task-participants:v1') AS visibility_version
                  FROM dianlian_business.task_run task
                  LEFT JOIN LATERAL (
                      SELECT event.visibility_version
                        FROM dianlian_business.task_event event
                       WHERE event.tenant_id = task.tenant_id AND event.task_id = task.task_id
                       ORDER BY event.stream_sequence DESC
                       LIMIT 1
                  ) latest_event ON TRUE
                 WHERE task.tenant_id = ? AND task.task_id = ?
                   AND EXISTS (
                       SELECT 1
                         FROM dianlian_business.task_participant participant
                        WHERE participant.tenant_id = task.tenant_id
                          AND participant.task_id = task.task_id
                          AND participant.user_id = ?
                          AND participant.status = 'ACTIVE'
                   )
                """,
                (resultSet, rowNum) -> new TaskStreamState(
                        resultSet.getLong("task_version"),
                        resultSet.getString("visibility_version")
                ),
                tenantId,
                taskId,
                actorId
        );
        return rows.stream().findFirst();
    }

    @Override
    public Optional<TaskEventCursor> findCursor(UUID tenantId, UUID taskId, String eventId) {
        final UUID parsedEventId;
        try {
            parsedEventId = UUID.fromString(eventId);
        } catch (IllegalArgumentException exception) {
            return Optional.empty();
        }
        var rows = jdbcTemplate.query(
                """
                SELECT stream_sequence, visibility_version
                  FROM dianlian_business.task_event
                 WHERE tenant_id = ? AND task_id = ? AND event_id = ?
                """,
                (resultSet, rowNum) -> new TaskEventCursor(
                        resultSet.getLong("stream_sequence"),
                        resultSet.getString("visibility_version")
                ),
                tenantId,
                taskId,
                parsedEventId
        );
        return rows.stream().findFirst();
    }

    @Override
    public List<PersistedTaskEvent> findVisibleAfter(
            UUID tenantId,
            UUID actorId,
            UUID taskId,
            long streamSequence,
            int limit
    ) {
        return jdbcTemplate.query(
                """
                SELECT event.stream_sequence, event.event_id, event.task_id, event.task_version,
                       event.visibility_version, event.trace_id, event.occurred_at
                  FROM dianlian_business.task_event event
                 WHERE event.tenant_id = ? AND event.task_id = ? AND event.stream_sequence > ?
                   AND EXISTS (
                       SELECT 1
                         FROM dianlian_business.task_participant participant
                        WHERE participant.tenant_id = event.tenant_id
                          AND participant.task_id = event.task_id
                          AND participant.user_id = ?
                          AND participant.status = 'ACTIVE'
                   )
                 ORDER BY event.stream_sequence
                 LIMIT ?
                """,
                (resultSet, rowNum) -> new PersistedTaskEvent(
                        resultSet.getLong("stream_sequence"),
                        resultSet.getObject("event_id", UUID.class),
                        resultSet.getObject("task_id", UUID.class),
                        resultSet.getLong("task_version"),
                        resultSet.getString("visibility_version"),
                        resultSet.getObject("trace_id", UUID.class),
                        resultSet.getTimestamp("occurred_at").toInstant()
                ),
                tenantId,
                taskId,
                streamSequence,
                actorId,
                limit
        );
    }

}

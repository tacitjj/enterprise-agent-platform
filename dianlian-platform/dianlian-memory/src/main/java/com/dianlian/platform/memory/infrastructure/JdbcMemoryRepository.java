package com.dianlian.platform.memory.infrastructure;

import com.dianlian.platform.memory.api.MemoryCandidateStatus;
import com.dianlian.platform.memory.api.MemoryItemStatus;
import com.dianlian.platform.memory.api.MemoryScopeRef;
import com.dianlian.platform.memory.api.MemoryScopeType;
import com.dianlian.platform.memory.api.InvocationMemoryAuthoritySource.MemoryEvidenceKey;
import com.dianlian.platform.memory.application.MemoryIndexJobWrite;
import com.dianlian.platform.memory.application.MemoryRepository;
import com.dianlian.platform.memory.domain.MemoryCandidate;
import com.dianlian.platform.memory.domain.MemoryEvent;
import com.dianlian.platform.memory.domain.MemoryItem;
import com.dianlian.platform.memory.domain.MemoryVersion;
import com.dianlian.platform.memory.domain.MemoryVersionChangeType;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcMemoryRepository implements MemoryRepository {

    private static final String CANDIDATE_COLUMNS = """
            candidate_id, tenant_id, enterprise_agent_id, scope_type, scope_id, content, semantic_key,
            source_conversation_id, source_message_id, status, request_hash, idempotency_key,
            proposed_by, proposed_at, decided_by, decided_at, decision_reason, decision_request_hash,
            decision_idempotency_key, confirmed_memory_id
            """;
    private static final String MEMORY_COLUMNS = """
            i.memory_id, i.tenant_id, i.enterprise_agent_id, i.scope_type, i.scope_id, i.status,
            i.current_version, v.content, v.semantic_key, i.created_by, i.created_at, i.updated_at,
            i.forgotten_by, i.forgotten_at, i.forget_reason, i.forget_request_hash, i.forget_idempotency_key
            """;

    private final JdbcTemplate jdbcTemplate;

    public JdbcMemoryRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public Optional<MemoryCandidate> findCandidateByProposeIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        return queryCandidate("""
                SELECT %s
                  FROM dianlian_business.ai_memory_candidate
                 WHERE tenant_id = ? AND proposed_by = ? AND idempotency_key = ?
                """.formatted(CANDIDATE_COLUMNS), tenantId, actorId, idempotencyKey);
    }

    @Override
    public Optional<MemoryCandidate> findCandidateByDecisionIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        return queryCandidate("""
                SELECT %s
                  FROM dianlian_business.ai_memory_candidate
                 WHERE tenant_id = ? AND decided_by = ? AND decision_idempotency_key = ?
                """.formatted(CANDIDATE_COLUMNS), tenantId, actorId, idempotencyKey);
    }

    @Override
    public Optional<MemoryCandidate> lockCandidate(UUID tenantId, UUID candidateId) {
        return queryCandidate("""
                SELECT %s
                  FROM dianlian_business.ai_memory_candidate
                 WHERE tenant_id = ? AND candidate_id = ?
                   FOR UPDATE
                """.formatted(CANDIDATE_COLUMNS), tenantId, candidateId);
    }

    @Override
    public boolean insertCandidateIfAbsent(MemoryCandidate candidate) {
        return jdbcTemplate.update("""
                INSERT INTO dianlian_business.ai_memory_candidate (
                    candidate_id, tenant_id, enterprise_agent_id, scope_type, scope_id, content, semantic_key,
                    source_conversation_id, source_message_id, status, request_hash, idempotency_key,
                    proposed_by, proposed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (tenant_id, proposed_by, idempotency_key) DO NOTHING
                """,
                candidate.candidateId(), candidate.tenantId(), candidate.enterpriseAgentId(),
                candidate.scope().scopeType().name(), candidate.scope().scopeId(), candidate.content(),
                candidate.semanticKey(), candidate.sourceConversationId(), candidate.sourceMessageId(),
                candidate.status().name(), candidate.requestHash(), candidate.idempotencyKey(),
                candidate.proposedBy(), Timestamp.from(candidate.proposedAt())
        ) == 1;
    }

    @Override
    public boolean markCandidateConfirmed(
            UUID tenantId,
            UUID candidateId,
            UUID memoryId,
            UUID actorId,
            Instant decidedAt,
            String reason,
            String requestHash,
            String idempotencyKey
    ) {
        return updateCandidateDecision(
                tenantId, candidateId, "CONFIRMED", memoryId, actorId, decidedAt, reason, requestHash, idempotencyKey
        );
    }

    @Override
    public boolean markCandidateRejected(
            UUID tenantId,
            UUID candidateId,
            UUID actorId,
            Instant decidedAt,
            String reason,
            String requestHash,
            String idempotencyKey
    ) {
        return updateCandidateDecision(
                tenantId, candidateId, "REJECTED", null, actorId, decidedAt, reason, requestHash, idempotencyKey
        );
    }

    @Override
    public Optional<MemoryItem> lockMemory(UUID tenantId, UUID memoryId) {
        return queryMemory("""
                SELECT %s
                  FROM dianlian_business.ai_memory_item i
                  JOIN dianlian_business.ai_memory_version v
                    ON v.tenant_id = i.tenant_id
                   AND v.memory_id = i.memory_id
                   AND v.version_no = i.current_version
                 WHERE i.tenant_id = ? AND i.memory_id = ?
                   FOR UPDATE OF i
                """.formatted(MEMORY_COLUMNS), tenantId, memoryId);
    }

    @Override
    public Optional<MemoryItem> findMemory(UUID tenantId, UUID memoryId) {
        return queryMemory("""
                SELECT %s
                  FROM dianlian_business.ai_memory_item i
                  JOIN dianlian_business.ai_memory_version v
                    ON v.tenant_id = i.tenant_id
                   AND v.memory_id = i.memory_id
                   AND v.version_no = i.current_version
                 WHERE i.tenant_id = ? AND i.memory_id = ?
                """.formatted(MEMORY_COLUMNS), tenantId, memoryId);
    }

    @Override
    public Optional<MemoryVersion> findCorrectionByIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        return jdbcTemplate.query("""
                SELECT memory_id, tenant_id, version_no, content, semantic_key, source_candidate_id,
                       change_type, reason, request_hash, idempotency_key, created_by, created_at
                 FROM dianlian_business.ai_memory_version
                 WHERE tenant_id = ? AND created_by = ? AND change_type = 'CORRECTED' AND idempotency_key = ?
                """, JdbcMemoryRepository::mapVersion, tenantId, actorId, idempotencyKey).stream().findFirst();
    }

    @Override
    public Optional<MemoryItem> findForgetByIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        return queryMemory("""
                SELECT %s
                  FROM dianlian_business.ai_memory_item i
                  JOIN dianlian_business.ai_memory_version v
                    ON v.tenant_id = i.tenant_id
                   AND v.memory_id = i.memory_id
                   AND v.version_no = i.current_version
                 WHERE i.tenant_id = ? AND i.forgotten_by = ? AND i.forget_idempotency_key = ?
                """.formatted(MEMORY_COLUMNS), tenantId, actorId, idempotencyKey);
    }

    @Override
    public void insertMemory(MemoryItem memory) {
        jdbcTemplate.update("""
                INSERT INTO dianlian_business.ai_memory_item (
                    memory_id, tenant_id, enterprise_agent_id, scope_type, scope_id, status,
                    current_version, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                memory.memoryId(), memory.tenantId(), memory.enterpriseAgentId(), memory.scope().scopeType().name(),
                memory.scope().scopeId(), memory.status().name(), memory.currentVersion(), memory.createdBy(),
                Timestamp.from(memory.createdAt()), Timestamp.from(memory.updatedAt())
        );
    }

    @Override
    public void insertVersion(MemoryVersion version) {
        jdbcTemplate.update("""
                INSERT INTO dianlian_business.ai_memory_version (
                    memory_id, tenant_id, version_no, content, semantic_key, source_candidate_id,
                    change_type, reason, request_hash, idempotency_key, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                version.memoryId(), version.tenantId(), version.version(), version.content(), version.semanticKey(),
                version.sourceCandidateId(), version.changeType().name(), version.reason(), version.requestHash(),
                version.idempotencyKey(), version.createdBy(), Timestamp.from(version.createdAt())
        );
    }

    @Override
    public boolean advanceMemoryVersion(
            UUID tenantId,
            UUID memoryId,
            long expectedVersion,
            String content,
            String semanticKey,
            Instant updatedAt
    ) {
        return jdbcTemplate.update("""
                UPDATE dianlian_business.ai_memory_item
                   SET current_version = current_version + 1,
                       updated_at = ?
                 WHERE tenant_id = ? AND memory_id = ? AND current_version = ? AND status = 'ACTIVE'
                """, Timestamp.from(updatedAt), tenantId, memoryId, expectedVersion) == 1;
    }

    @Override
    public boolean forgetMemory(
            UUID tenantId,
            UUID memoryId,
            long expectedVersion,
            UUID actorId,
            Instant forgottenAt,
            String reason,
            String requestHash,
            String idempotencyKey
    ) {
        return jdbcTemplate.update("""
                UPDATE dianlian_business.ai_memory_item
                   SET status = 'FORGOTTEN', updated_at = ?, forgotten_by = ?, forgotten_at = ?,
                       forget_reason = ?, forget_request_hash = ?, forget_idempotency_key = ?
                 WHERE tenant_id = ? AND memory_id = ? AND current_version = ? AND status = 'ACTIVE'
                """, Timestamp.from(forgottenAt), actorId, Timestamp.from(forgottenAt), reason, requestHash,
                idempotencyKey, tenantId, memoryId, expectedVersion) == 1;
    }

    @Override
    public long insertEvent(MemoryEvent event) {
        Long eventSequence = jdbcTemplate.queryForObject("""
                INSERT INTO dianlian_business.ai_memory_event (
                    event_id, tenant_id, enterprise_agent_id, scope_type, scope_id, event_type,
                    candidate_id, memory_id, resulting_version, from_status, to_status, reason,
                    request_hash, idempotency_key, actor_id, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING event_sequence
                """,
                Long.class,
                event.eventId(), event.tenantId(), event.enterpriseAgentId(), event.scope().scopeType().name(),
                event.scope().scopeId(), event.eventType().name(), event.candidateId(), event.memoryId(),
                event.resultingVersion(), event.fromStatus(), event.toStatus(), event.reason(), event.requestHash(),
                event.idempotencyKey(), event.actorId(), Timestamp.from(event.occurredAt())
        );
        return java.util.Objects.requireNonNull(eventSequence, "memory event sequence must not be null");
    }

    @Override
    public void insertIndexJob(MemoryIndexJobWrite write) {
        jdbcTemplate.update("""
                INSERT INTO dianlian_business.context_index_job (
                    job_id, tenant_id, authority_scope, resource_type, resource_id,
                    resource_version, event_sequence, index_target, operation, status,
                    attempt_count, next_attempt_at, created_at, updated_at
                ) VALUES (?, ?, 'TENANT', 'MEMORY_ITEM_VERSION', ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                write.jobId(), write.tenantId(), write.resourceId(), write.resourceVersion(), write.eventSequence(),
                write.indexTarget().name(), write.operation().name(), Timestamp.from(write.occurredAt()),
                Timestamp.from(write.occurredAt()), Timestamp.from(write.occurredAt())
        );
    }

    @Override
    public List<MemoryItem> recallConfirmed(
            UUID tenantId,
            UUID enterpriseAgentId,
            List<MemoryScopeRef> scopes,
            String query,
            int limit
    ) {
        StringBuilder scopePredicate = new StringBuilder();
        var parameters = new ArrayList<>();
        parameters.add(tenantId);
        parameters.add(enterpriseAgentId);
        for (MemoryScopeRef scope : scopes) {
            if (!scopePredicate.isEmpty()) {
                scopePredicate.append(" OR ");
            }
            scopePredicate.append("(i.scope_type = ? AND i.scope_id = ?)");
            parameters.add(scope.scopeType().name());
            parameters.add(scope.scopeId());
        }
        parameters.add("%" + escapeLike(query.toLowerCase()) + "%");
        parameters.add(limit);
        String sql = """
                SELECT %s
                  FROM dianlian_business.ai_memory_item i
                  JOIN dianlian_business.ai_memory_version v
                    ON v.tenant_id = i.tenant_id
                   AND v.memory_id = i.memory_id
                   AND v.version_no = i.current_version
                 WHERE i.tenant_id = ?
                   AND i.enterprise_agent_id = ?
                   AND i.status = 'ACTIVE'
                   AND (%s)
                   AND LOWER(v.content) LIKE ? ESCAPE '\\'
                 ORDER BY i.updated_at DESC, i.memory_id
                 LIMIT ?
                """.formatted(MEMORY_COLUMNS, scopePredicate);
        return jdbcTemplate.query(sql, JdbcMemoryRepository::mapMemory, parameters.toArray());
    }

    @Override
    public List<MemoryRepository.MemoryAuthoritySnapshot> findAuthoritySnapshots(
            UUID tenantId,
            List<MemoryEvidenceKey> evidenceKeys
    ) {
        if (evidenceKeys.isEmpty()) {
            return List.of();
        }
        StringBuilder requestedValues = new StringBuilder();
        var parameters = new ArrayList<>();
        for (MemoryEvidenceKey key : evidenceKeys) {
            if (!requestedValues.isEmpty()) requestedValues.append(", ");
            requestedValues.append("(CAST(? AS UUID), CAST(? AS BIGINT))");
            parameters.add(key.memoryId());
            parameters.add(key.versionNo());
        }
        parameters.add(tenantId);
        String sql = """
                WITH requested(memory_id, version_no) AS (VALUES %s),
                origin AS (
                    SELECT item.memory_id,
                           requested.version_no,
                           COALESCE(requested_version.source_candidate_id, first_version.source_candidate_id)
                               AS source_candidate_id
                      FROM requested
                      JOIN dianlian_business.ai_memory_item item
                        ON item.memory_id = requested.memory_id
                       AND item.tenant_id = ?
                      JOIN dianlian_business.ai_memory_version requested_version
                        ON requested_version.tenant_id = item.tenant_id
                       AND requested_version.memory_id = item.memory_id
                       AND requested_version.version_no = requested.version_no
                      LEFT JOIN dianlian_business.ai_memory_version first_version
                        ON first_version.tenant_id = item.tenant_id
                       AND first_version.memory_id = item.memory_id
                       AND first_version.version_no = 1
                )
                SELECT requested.memory_id,
                       requested.version_no,
                       item.enterprise_agent_id,
                       item.scope_type,
                       item.scope_id,
                       item.status,
                       item.current_version,
                       source_message.sequence_no AS source_message_sequence_no
                  FROM requested
                  JOIN dianlian_business.ai_memory_item item
                    ON item.memory_id = requested.memory_id
                   AND item.tenant_id = ?
                  JOIN origin
                    ON origin.memory_id = item.memory_id
                   AND origin.version_no = requested.version_no
                  LEFT JOIN dianlian_business.ai_memory_candidate candidate
                    ON candidate.tenant_id = item.tenant_id
                   AND candidate.candidate_id = origin.source_candidate_id
                  LEFT JOIN dianlian_business.conversation_message source_message
                    ON source_message.tenant_id = candidate.tenant_id
                   AND source_message.message_id = candidate.source_message_id
                 ORDER BY requested.memory_id, requested.version_no
                """.formatted(requestedValues);
        parameters.add(tenantId);
        Map<MemoryEvidenceKey, MemoryRepository.MemoryAuthoritySnapshot> byKey = new LinkedHashMap<>();
        for (var snapshot : jdbcTemplate.query(sql, (resultSet, rowNumber) -> {
            var key = new MemoryEvidenceKey(
                    resultSet.getObject("memory_id", UUID.class),
                    resultSet.getLong("version_no")
            );
            return new MemoryRepository.MemoryAuthoritySnapshot(
                    key,
                    resultSet.getObject("enterprise_agent_id", UUID.class),
                    new MemoryScopeRef(
                            MemoryScopeType.valueOf(resultSet.getString("scope_type")),
                            resultSet.getObject("scope_id", UUID.class)
                    ),
                    MemoryItemStatus.valueOf(resultSet.getString("status")),
                    resultSet.getLong("current_version"),
                    resultSet.getObject("source_message_sequence_no", Long.class)
            );
        }, parameters.toArray())) {
            byKey.put(snapshot.key(), snapshot);
        }
        return List.copyOf(byKey.values());
    }

    private boolean updateCandidateDecision(
            UUID tenantId,
            UUID candidateId,
            String status,
            UUID memoryId,
            UUID actorId,
            Instant decidedAt,
            String reason,
            String requestHash,
            String idempotencyKey
    ) {
        return jdbcTemplate.update("""
                UPDATE dianlian_business.ai_memory_candidate
                   SET status = ?, confirmed_memory_id = ?, decided_by = ?, decided_at = ?, decision_reason = ?,
                       decision_request_hash = ?, decision_idempotency_key = ?
                 WHERE tenant_id = ? AND candidate_id = ? AND status = 'PENDING'
                """, status, memoryId, actorId, Timestamp.from(decidedAt), reason, requestHash, idempotencyKey,
                tenantId, candidateId) == 1;
    }

    private Optional<MemoryCandidate> queryCandidate(String sql, Object... parameters) {
        return jdbcTemplate.query(sql, JdbcMemoryRepository::mapCandidate, parameters).stream().findFirst();
    }

    private Optional<MemoryItem> queryMemory(String sql, Object... parameters) {
        return jdbcTemplate.query(sql, JdbcMemoryRepository::mapMemory, parameters).stream().findFirst();
    }

    private static MemoryCandidate mapCandidate(ResultSet resultSet, int rowNum) throws SQLException {
        return new MemoryCandidate(
                resultSet.getObject("candidate_id", UUID.class),
                resultSet.getObject("tenant_id", UUID.class),
                resultSet.getObject("enterprise_agent_id", UUID.class),
                new MemoryScopeRef(
                        MemoryScopeType.valueOf(resultSet.getString("scope_type")),
                        resultSet.getObject("scope_id", UUID.class)
                ),
                resultSet.getString("content"),
                resultSet.getString("semantic_key"),
                resultSet.getObject("source_conversation_id", UUID.class),
                resultSet.getObject("source_message_id", UUID.class),
                MemoryCandidateStatus.valueOf(resultSet.getString("status")),
                resultSet.getString("request_hash"),
                resultSet.getString("idempotency_key"),
                resultSet.getObject("proposed_by", UUID.class),
                instant(resultSet, "proposed_at"),
                resultSet.getObject("decided_by", UUID.class),
                instant(resultSet, "decided_at"),
                resultSet.getString("decision_reason"),
                resultSet.getString("decision_request_hash"),
                resultSet.getString("decision_idempotency_key"),
                resultSet.getObject("confirmed_memory_id", UUID.class)
        );
    }

    private static MemoryItem mapMemory(ResultSet resultSet, int rowNum) throws SQLException {
        return new MemoryItem(
                resultSet.getObject("memory_id", UUID.class),
                resultSet.getObject("tenant_id", UUID.class),
                resultSet.getObject("enterprise_agent_id", UUID.class),
                new MemoryScopeRef(
                        MemoryScopeType.valueOf(resultSet.getString("scope_type")),
                        resultSet.getObject("scope_id", UUID.class)
                ),
                MemoryItemStatus.valueOf(resultSet.getString("status")),
                resultSet.getLong("current_version"),
                resultSet.getString("content"),
                resultSet.getString("semantic_key"),
                resultSet.getObject("created_by", UUID.class),
                instant(resultSet, "created_at"),
                instant(resultSet, "updated_at"),
                resultSet.getObject("forgotten_by", UUID.class),
                instant(resultSet, "forgotten_at"),
                resultSet.getString("forget_reason"),
                resultSet.getString("forget_request_hash"),
                resultSet.getString("forget_idempotency_key")
        );
    }

    private static MemoryVersion mapVersion(ResultSet resultSet, int rowNum) throws SQLException {
        return new MemoryVersion(
                resultSet.getObject("memory_id", UUID.class),
                resultSet.getObject("tenant_id", UUID.class),
                resultSet.getLong("version_no"),
                resultSet.getString("content"),
                resultSet.getString("semantic_key"),
                resultSet.getObject("source_candidate_id", UUID.class),
                MemoryVersionChangeType.valueOf(resultSet.getString("change_type")),
                resultSet.getString("reason"),
                resultSet.getString("request_hash"),
                resultSet.getString("idempotency_key"),
                resultSet.getObject("created_by", UUID.class),
                instant(resultSet, "created_at")
        );
    }

    private static Instant instant(ResultSet resultSet, String column) throws SQLException {
        Timestamp timestamp = resultSet.getTimestamp(column);
        return timestamp == null ? null : timestamp.toInstant();
    }

    private static String escapeLike(String value) {
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }
}

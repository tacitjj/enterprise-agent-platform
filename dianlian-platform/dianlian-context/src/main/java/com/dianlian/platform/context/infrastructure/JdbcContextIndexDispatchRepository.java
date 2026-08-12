package com.dianlian.platform.context.infrastructure;

import com.dianlian.platform.context.api.ContextIndexDispatch.AuthorityScope;
import com.dianlian.platform.context.api.ContextIndexDispatch.FailureDisposition;
import com.dianlian.platform.context.api.ContextIndexDispatch.IndexOperation;
import com.dianlian.platform.context.api.ContextIndexDispatch.IndexTarget;
import com.dianlian.platform.context.api.ContextIndexDispatch.MemoryScopeType;
import com.dianlian.platform.context.api.ContextIndexDispatch.RemoteReceipt;
import com.dianlian.platform.context.api.ContextIndexDispatch.ResourceType;
import com.dianlian.platform.context.application.ContextIndexDispatchRepository;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/**
 * PostgreSQL queue implementation. Claiming, authority re-read and lease transitions are all
 * fenced in SQL; a database failure propagates so the surrounding transaction rolls back.
 */
@Repository
public final class JdbcContextIndexDispatchRepository implements ContextIndexDispatchRepository {

    static final String CLAIM_SQL = """
            WITH candidate AS (
                SELECT job_id
                  FROM dianlian_business.context_index_job
                 WHERE index_target = :indexTarget
                   AND index_profile_version = :indexProfileVersion
                   AND attempt_count < :maxAttempts
                   AND (
                       (status IN ('PENDING', 'FAILED') AND next_attempt_at <= :now)
                       OR (status = 'RUNNING' AND lease_expires_at <= :now)
                   )
                 ORDER BY CASE operation WHEN 'DELETE' THEN 0 ELSE 1 END,
                          event_sequence, job_id
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
            )
            UPDATE dianlian_business.context_index_job job
               SET status = 'RUNNING',
                   attempt_count = job.attempt_count + 1,
                   lease_owner = :workerId,
                   lease_epoch = job.lease_epoch + 1,
                   lease_expires_at = :leaseExpiresAt,
                   last_error_code = NULL,
                   last_error_message = NULL,
                   completed_at = NULL,
                   updated_at = :now
              FROM candidate
             WHERE job.job_id = candidate.job_id
            RETURNING job.job_id, job.tenant_id, job.authority_scope, job.resource_type,
                      job.resource_id, job.resource_version, job.event_sequence, job.index_target,
                      job.index_profile_version, job.operation, job.lease_owner, job.attempt_count,
                      job.lease_epoch, job.lease_expires_at
            """;

    static final String KNOWLEDGE_AUTHORITY_SQL = """
            SELECT version.tenant_id,
                   space.owner_scope AS authority_scope,
                   version.document_version_id,
                   version.document_id,
                   document.current_version_id,
                   version.space_id,
                   space.status AS space_status,
                   document.status AS document_status,
                   version.status AS version_status,
                   version.access_state,
                   version.resource_version,
                   GREATEST(version.event_sequence, document.event_sequence, space.event_sequence)
                       AS authority_event_sequence,
                   document.title,
                   version.object_key,
                   version.content_hash,
                   version.normalized_text,
                   version.normalized_text_hash,
                   version.normalization_profile_version,
                   version.normalized_at,
                   version.mime_type,
                   version.byte_size,
                   version.metadata::TEXT AS metadata_json
              FROM dianlian_business.knowledge_document_version version
              JOIN dianlian_business.knowledge_document document
                ON document.document_id = version.document_id
               AND document.space_id = version.space_id
             JOIN dianlian_business.knowledge_space space
                ON space.space_id = version.space_id
             WHERE version.document_version_id = :documentVersionId
               AND space.owner_scope = :authorityScope
               AND version.tenant_id IS NOT DISTINCT FROM CAST(:tenantId AS UUID)
            """;

    static final String MEMORY_AUTHORITY_SQL = """
            SELECT item.tenant_id,
                   item.memory_id,
                   item.current_version,
                   item.status AS item_status,
                   item.event_sequence AS authority_event_sequence,
                   requested.version_no AS requested_version,
                   item.enterprise_agent_id,
                   item.scope_type,
                   item.scope_id,
                   requested.content,
                   requested.semantic_key,
                   source_message.sequence_no AS source_message_sequence_no
              FROM dianlian_business.ai_memory_item item
              LEFT JOIN dianlian_business.ai_memory_version requested
                ON requested.tenant_id = item.tenant_id
               AND requested.memory_id = item.memory_id
               AND requested.version_no = :requestedVersion
              LEFT JOIN dianlian_business.ai_memory_version origin
                ON origin.tenant_id = item.tenant_id
               AND origin.memory_id = item.memory_id
               AND origin.version_no = 1
              LEFT JOIN dianlian_business.ai_memory_candidate candidate
                ON candidate.tenant_id = item.tenant_id
               AND candidate.candidate_id = COALESCE(requested.source_candidate_id, origin.source_candidate_id)
              LEFT JOIN dianlian_business.conversation_message source_message
                ON source_message.tenant_id = candidate.tenant_id
               AND source_message.message_id = candidate.source_message_id
             WHERE item.memory_id = :memoryId
               AND item.tenant_id = :tenantId
            """;

    private final JdbcClient jdbcClient;

    public JdbcContextIndexDispatchRepository(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    @Override
    public void deadLetterExhausted(int maxAttempts, Instant now) {
        jdbcClient.sql("""
                        WITH exhausted AS (
                            SELECT job_id
                              FROM dianlian_business.context_index_job
                             WHERE attempt_count >= :maxAttempts
                               AND (
                                   status IN ('PENDING', 'FAILED')
                                   OR (status = 'RUNNING' AND lease_expires_at <= :now)
                               )
                             ORDER BY event_sequence, job_id
                             FOR UPDATE SKIP LOCKED
                             LIMIT 100
                        )
                        UPDATE dianlian_business.context_index_job job
                           SET status = 'DEAD_LETTER',
                               lease_owner = NULL,
                               lease_expires_at = NULL,
                               last_error_code = COALESCE(last_error_code, 'INDEX_ATTEMPTS_EXHAUSTED'),
                               last_error_message = COALESCE(last_error_message, 'context index attempts exhausted'),
                               updated_at = :now
                          FROM exhausted
                         WHERE job.job_id = exhausted.job_id
                        """)
                .param("maxAttempts", maxAttempts)
                .param("now", timestamp(now))
                .update();
    }

    @Override
    public Optional<ClaimedIndexJob> claimNext(
            String workerId,
            IndexTarget indexTarget,
            String indexProfileVersion,
            int maxAttempts,
            Instant now,
            Instant leaseExpiresAt
    ) {
        return jdbcClient.sql(CLAIM_SQL)
                .param("indexTarget", indexTarget.name())
                .param("indexProfileVersion", indexProfileVersion)
                .param("maxAttempts", maxAttempts)
                .param("now", timestamp(now))
                .param("workerId", workerId)
                .param("leaseExpiresAt", timestamp(leaseExpiresAt))
                .query(JdbcContextIndexDispatchRepository::mapClaimedJob)
                .optional();
    }

    @Override
    public Optional<KnowledgeAuthoritySnapshot> findKnowledgeAuthority(
            UUID tenantId,
            AuthorityScope authorityScope,
            UUID documentVersionId
    ) {
        return jdbcClient.sql(KNOWLEDGE_AUTHORITY_SQL)
                .param("documentVersionId", documentVersionId)
                .param("authorityScope", authorityScope.name())
                .param("tenantId", tenantId)
                .query(JdbcContextIndexDispatchRepository::mapKnowledgeAuthority)
                .optional();
    }

    @Override
    public Optional<MemoryAuthoritySnapshot> findMemoryAuthority(
            UUID tenantId,
            UUID memoryId,
            long requestedVersion
    ) {
        return jdbcClient.sql(MEMORY_AUTHORITY_SQL)
                .param("tenantId", tenantId)
                .param("memoryId", memoryId)
                .param("requestedVersion", requestedVersion)
                .query(JdbcContextIndexDispatchRepository::mapMemoryAuthority)
                .optional();
    }

    @Override
    public Optional<Instant> heartbeat(
            UUID jobId,
            String workerId,
            int attempt,
            long leaseEpoch,
            Instant now,
            Instant newLeaseExpiresAt
    ) {
        return jdbcClient.sql("""
                        UPDATE dianlian_business.context_index_job
                           SET lease_expires_at = GREATEST(lease_expires_at, :newLeaseExpiresAt),
                               updated_at = :now
                         WHERE job_id = :jobId
                           AND status = 'RUNNING'
                           AND lease_owner = :workerId
                           AND attempt_count = :attempt
                           AND lease_epoch = :leaseEpoch
                           AND lease_expires_at > :now
                        RETURNING lease_expires_at
                        """)
                .param("jobId", jobId)
                .param("workerId", workerId)
                .param("attempt", attempt)
                .param("leaseEpoch", leaseEpoch)
                .param("now", timestamp(now))
                .param("newLeaseExpiresAt", timestamp(newLeaseExpiresAt))
                .query(Timestamp.class)
                .optional()
                .map(Timestamp::toInstant);
    }

    @Override
    public boolean complete(
            UUID jobId,
            String workerId,
            int attempt,
            long leaseEpoch,
            Instant now,
            RemoteReceipt receipt
    ) {
        return jdbcClient.sql("""
                        UPDATE dianlian_business.context_index_job
                           SET status = 'SUCCEEDED',
                               lease_owner = NULL,
                               lease_expires_at = NULL,
                               last_error_code = NULL,
                               last_error_message = NULL,
                               remote_receipt = JSONB_STRIP_NULLS(JSONB_BUILD_OBJECT(
                                   'receiptId', :receiptId,
                                   'outcome', :outcome,
                                   'appliedEventSequence', :appliedEventSequence,
                                   'contentHash', :contentHash
                               )),
                               completed_at = :now,
                               updated_at = :now
                         WHERE job_id = :jobId
                           AND status = 'RUNNING'
                           AND lease_owner = :workerId
                           AND attempt_count = :attempt
                           AND lease_epoch = :leaseEpoch
                           AND lease_expires_at > :now
                        """)
                .param("jobId", jobId)
                .param("workerId", workerId)
                .param("attempt", attempt)
                .param("leaseEpoch", leaseEpoch)
                .param("receiptId", receipt.receiptId())
                .param("outcome", receipt.outcome().name())
                .param("appliedEventSequence", receipt.appliedEventSequence())
                .param("contentHash", receipt.contentHash())
                .param("now", timestamp(now))
                .update() == 1;
    }

    @Override
    public Optional<FailureDisposition> fail(
            UUID jobId,
            String workerId,
            int attempt,
            long leaseEpoch,
            Instant now,
            Instant nextAttemptAt,
            int maxAttempts,
            boolean retryable,
            String errorCode,
            String errorMessage
    ) {
        return jdbcClient.sql("""
                        UPDATE dianlian_business.context_index_job
                           SET status = CASE
                                   WHEN :retryable AND attempt_count < :maxAttempts THEN 'FAILED'
                                   ELSE 'DEAD_LETTER'
                               END,
                               next_attempt_at = CASE
                                   WHEN :retryable AND attempt_count < :maxAttempts THEN :nextAttemptAt
                                   ELSE next_attempt_at
                               END,
                               lease_owner = NULL,
                               lease_expires_at = NULL,
                               last_error_code = :errorCode,
                               last_error_message = :errorMessage,
                               updated_at = :now
                         WHERE job_id = :jobId
                           AND status = 'RUNNING'
                           AND lease_owner = :workerId
                           AND attempt_count = :attempt
                           AND lease_epoch = :leaseEpoch
                           AND lease_expires_at > :now
                        RETURNING status
                        """)
                .param("jobId", jobId)
                .param("workerId", workerId)
                .param("attempt", attempt)
                .param("leaseEpoch", leaseEpoch)
                .param("now", timestamp(now))
                .param("nextAttemptAt", timestamp(nextAttemptAt))
                .param("maxAttempts", maxAttempts)
                .param("retryable", retryable)
                .param("errorCode", errorCode)
                .param("errorMessage", errorMessage)
                .query(String.class)
                .optional()
                .map(status -> "FAILED".equals(status)
                        ? FailureDisposition.RETRY_SCHEDULED
                        : FailureDisposition.DEAD_LETTERED);
    }

    private static ClaimedIndexJob mapClaimedJob(ResultSet resultSet, int rowNumber) throws SQLException {
        return new ClaimedIndexJob(
                resultSet.getObject("job_id", UUID.class),
                resultSet.getObject("tenant_id", UUID.class),
                AuthorityScope.valueOf(resultSet.getString("authority_scope")),
                ResourceType.valueOf(resultSet.getString("resource_type")),
                resultSet.getObject("resource_id", UUID.class),
                resultSet.getLong("resource_version"),
                resultSet.getLong("event_sequence"),
                IndexTarget.valueOf(resultSet.getString("index_target")),
                resultSet.getString("index_profile_version"),
                IndexOperation.valueOf(resultSet.getString("operation")),
                resultSet.getString("lease_owner"),
                resultSet.getInt("attempt_count"),
                resultSet.getLong("lease_epoch"),
                resultSet.getTimestamp("lease_expires_at").toInstant()
        );
    }

    private static KnowledgeAuthoritySnapshot mapKnowledgeAuthority(ResultSet resultSet, int rowNumber)
            throws SQLException {
        return new KnowledgeAuthoritySnapshot(
                resultSet.getObject("tenant_id", UUID.class),
                AuthorityScope.valueOf(resultSet.getString("authority_scope")),
                resultSet.getObject("document_version_id", UUID.class),
                resultSet.getObject("document_id", UUID.class),
                resultSet.getObject("current_version_id", UUID.class),
                resultSet.getObject("space_id", UUID.class),
                resultSet.getString("space_status"),
                resultSet.getString("document_status"),
                resultSet.getString("version_status"),
                resultSet.getString("access_state"),
                resultSet.getLong("resource_version"),
                resultSet.getLong("authority_event_sequence"),
                resultSet.getString("title"),
                resultSet.getString("object_key"),
                resultSet.getString("content_hash"),
                resultSet.getString("normalized_text"),
                resultSet.getString("normalized_text_hash"),
                resultSet.getString("normalization_profile_version"),
                resultSet.getTimestamp("normalized_at") == null
                        ? null : resultSet.getTimestamp("normalized_at").toInstant(),
                resultSet.getString("mime_type"),
                resultSet.getLong("byte_size"),
                resultSet.getString("metadata_json")
        );
    }

    private static MemoryAuthoritySnapshot mapMemoryAuthority(ResultSet resultSet, int rowNumber)
            throws SQLException {
        return new MemoryAuthoritySnapshot(
                resultSet.getObject("tenant_id", UUID.class),
                resultSet.getObject("memory_id", UUID.class),
                resultSet.getLong("current_version"),
                resultSet.getString("item_status"),
                resultSet.getLong("authority_event_sequence"),
                resultSet.getObject("requested_version", Long.class),
                resultSet.getObject("enterprise_agent_id", UUID.class),
                MemoryScopeType.valueOf(resultSet.getString("scope_type")),
                resultSet.getObject("scope_id", UUID.class),
                resultSet.getString("content"),
                resultSet.getString("semantic_key"),
                resultSet.getObject("source_message_sequence_no", Long.class)
        );
    }

    private static Timestamp timestamp(Instant value) {
        return Timestamp.from(value);
    }
}

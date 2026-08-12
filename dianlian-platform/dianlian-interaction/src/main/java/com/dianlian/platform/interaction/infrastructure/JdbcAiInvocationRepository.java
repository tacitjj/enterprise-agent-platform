package com.dianlian.platform.interaction.infrastructure;

import com.dianlian.platform.context.api.ContextMessage;
import com.dianlian.platform.context.api.ContextAuthorityPort;
import com.dianlian.platform.context.api.FencedAgentContext;
import com.dianlian.platform.context.api.AgentContextBundle;
import com.dianlian.platform.context.api.ContextEvidence;
import com.dianlian.platform.context.api.ContextSourceResult;
import com.dianlian.platform.context.api.ContextSourceState;
import com.dianlian.platform.context.api.MemoryScopeRef;
import com.dianlian.platform.context.api.MemoryScopeType;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RetrievalTrace;
import com.dianlian.platform.interaction.application.AiInvocationRepository;
import com.dianlian.platform.interaction.application.InvocationContextSnapshot;
import com.dianlian.platform.interaction.application.InvocationContextAuthoritySnapshot;
import com.dianlian.platform.model.api.ModelChatResponse;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.dao.ConcurrencyFailureException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcAiInvocationRepository implements AiInvocationRepository {

    private static final TypeReference<List<UUID>> UUID_LIST = new TypeReference<>() {
    };

    private static final TypeReference<List<ContextAuthorityPort.EvidenceIdentity>> EVIDENCE_LIST =
            new TypeReference<>() {
            };

    private final JdbcClient jdbcClient;
    private final ObjectMapper objectMapper;

    public JdbcAiInvocationRepository(JdbcClient jdbcClient, ObjectMapper objectMapper) {
        this.jdbcClient = jdbcClient;
        this.objectMapper = objectMapper;
    }

    @Override
    public Optional<ClaimedInvocation> claimNext(String workerId, Instant now, Instant leaseUntil) {
        var claimedId = jdbcClient.sql("""
                        WITH candidate AS (
                            SELECT invocation_id
                              FROM dianlian_business.ai_invocation
                             WHERE next_attempt_at <= :now
                               AND (
                                   status = 'QUEUED'
                                   OR (status = 'RUNNING' AND lease_until < :now)
                                   OR (status = 'RESPONSE_RECEIVED' AND (lease_until IS NULL OR lease_until < :now))
                               )
                             ORDER BY CASE status WHEN 'RESPONSE_RECEIVED' THEN 0 ELSE 1 END,
                                      created_at, invocation_id
                             FOR UPDATE SKIP LOCKED
                             LIMIT 1
                        )
                        UPDATE dianlian_business.ai_invocation invocation
                           SET status = CASE
                                   WHEN invocation.status = 'RESPONSE_RECEIVED' THEN 'RESPONSE_RECEIVED'
                                   ELSE 'RUNNING'
                               END,
                               attempt_count = CASE
                                   WHEN invocation.status = 'RESPONSE_RECEIVED' THEN invocation.attempt_count
                                   ELSE invocation.attempt_count + 1
                               END,
                               lease_owner = :workerId,
                               lease_epoch = invocation.lease_epoch + 1,
                               lease_until = :leaseUntil,
                               updated_at = :now
                          FROM candidate
                         WHERE invocation.invocation_id = candidate.invocation_id
                        RETURNING invocation.invocation_id
                        """)
                .param("workerId", workerId)
                .param("now", Timestamp.from(now))
                .param("leaseUntil", Timestamp.from(leaseUntil))
                .query(UUID.class)
                .optional();
        return claimedId.flatMap(invocationId -> loadClaimed(invocationId, now));
    }

    @Override
    public List<ContextMessage> recentMessages(ClaimedInvocation invocation, int limit) {
        return jdbcClient.sql("""
                        SELECT message.sender_type,
                               COALESCE(user_account.display_name, response_invocation.role_name_snapshot,
                                        agent.display_name, '企业数字员工') AS actor_label,
                               message.body_text
                          FROM dianlian_business.conversation_message message
                          LEFT JOIN dianlian_business.user_account user_account
                            ON user_account.user_id = message.sender_user_id
                          LEFT JOIN dianlian_business.ai_invocation response_invocation
                            ON response_invocation.response_message_id = message.message_id
                          LEFT JOIN dianlian_business.enterprise_agent agent
                            ON agent.tenant_id = message.tenant_id
                           AND agent.enterprise_agent_id = message.sender_agent_id
                         WHERE message.tenant_id = :tenantId
                           AND message.conversation_id = :conversationId
                           AND message.sequence_no > :historyFloorSequenceNo
                           AND message.sequence_no < :sourceSequenceNo
                           AND message.sender_type IN ('HUMAN', 'AGENT')
                           AND message.status = 'VISIBLE'
                         ORDER BY message.sequence_no DESC
                         LIMIT :limit
                        """)
                .param("tenantId", invocation.tenantId())
                .param("conversationId", invocation.conversationId())
                .param("historyFloorSequenceNo", invocation.historyFloorSequenceNo())
                .param("sourceSequenceNo", invocation.sourceSequenceNo())
                .param("limit", limit)
                .query((resultSet, rowNumber) -> new ContextMessage(
                        "HUMAN".equals(resultSet.getString("sender_type"))
                                ? ContextMessage.Role.HUMAN : ContextMessage.Role.AGENT,
                        resultSet.getString("actor_label"),
                        resultSet.getString("body_text")
                ))
                .list()
                .reversed();
    }

    @Override
    public UUID saveContext(
            ClaimedInvocation invocation,
            InvocationContextSnapshot snapshot
    ) {
        var context = snapshot.fencedContext().context();
        var now = snapshot.createdAt();
        requireLease(invocation, now);
        UUID snapshotId = UUID.randomUUID();
        int inserted = jdbcClient.sql("""
                        INSERT INTO dianlian_business.ai_context_snapshot
                            (context_snapshot_id, invocation_id, tenant_id, enterprise_agent_id,
                             agent_version_id, configuration_version_id, memory_scopes,
                             knowledge_state, memory_state, context_hash, created_at,
                             schema_version, attempt_no, lease_epoch, access_membership_version,
                             history_floor_sequence_no, authorization_snapshot_hash,
                             retrieval_request_id, retrieval_snapshot_id, retrieval_trace,
                             evidence_refs, knowledge_reason_code, memory_reason_code, fenced_at)
                        VALUES
                            (:snapshotId, :invocationId, :tenantId, :agentId,
                             :agentVersionId, :configurationVersionId, CAST(:memoryScopes AS JSONB),
                             :knowledgeState, :memoryState, :contextHash, :createdAt,
                             'context-retrieval-v1', :attemptNo, :leaseEpoch, :membershipVersion,
                             :historyFloorSequenceNo, :authorizationSnapshotHash,
                             :retrievalRequestId, :retrievalSnapshotId, CAST(:retrievalTrace AS JSONB),
                             CAST(:evidenceRefs AS JSONB), :knowledgeReasonCode, :memoryReasonCode, :fencedAt)
                        ON CONFLICT (invocation_id, attempt_no, lease_epoch) DO NOTHING
                        """)
                .param("snapshotId", snapshotId)
                .param("invocationId", invocation.invocationId())
                .param("tenantId", invocation.tenantId())
                .param("agentId", invocation.enterpriseAgentId())
                .param("agentVersionId", invocation.agentVersionId())
                .param("configurationVersionId", invocation.configurationVersionId())
                .param("memoryScopes", writeJson(context.memoryScopes()))
                .param("knowledgeState", context.knowledge().state().name())
                .param("memoryState", context.memory().state().name())
                .param("contextHash", snapshot.contextHash())
                .param("createdAt", Timestamp.from(now))
                .param("attemptNo", invocation.attemptNo())
                .param("leaseEpoch", invocation.leaseEpoch())
                .param("membershipVersion", invocation.membershipVersion())
                .param("historyFloorSequenceNo", invocation.historyFloorSequenceNo())
                .param("authorizationSnapshotHash", snapshot.fencedContext().authorizationSnapshotHash())
                .param("retrievalRequestId", snapshot.fencedContext().retrievalRequestId())
                .param("retrievalSnapshotId", snapshot.fencedContext().retrievalSnapshotId())
                .param("retrievalTrace", writeJson(snapshot.fencedContext().retrievalTrace()))
                .param("evidenceRefs", writeJson(snapshot.fencedContext().evidence()))
                .param("knowledgeReasonCode", snapshot.fencedContext().knowledgeReasonCode())
                .param("memoryReasonCode", snapshot.fencedContext().memoryReasonCode())
                .param("fencedAt", Timestamp.from(snapshot.fencedContext().fencedAt()))
                .update();
        UUID persistedId = inserted == 1 ? snapshotId : jdbcClient.sql("""
                        SELECT context_snapshot_id
                          FROM dianlian_business.ai_context_snapshot
                         WHERE invocation_id = :invocationId
                           AND attempt_no = :attemptNo
                           AND lease_epoch = :leaseEpoch
                           AND context_hash = :contextHash
                           AND authorization_snapshot_hash = :authorizationSnapshotHash
                        """)
                .param("invocationId", invocation.invocationId())
                .param("attemptNo", invocation.attemptNo())
                .param("leaseEpoch", invocation.leaseEpoch())
                .param("contextHash", snapshot.contextHash())
                .param("authorizationSnapshotHash", snapshot.fencedContext().authorizationSnapshotHash())
                .query(UUID.class)
                .optional()
                .orElseThrow(() -> new ConcurrencyFailureException(
                        "AI context snapshot replay does not match the original authority"));
        int bound = jdbcClient.sql("""
                        UPDATE dianlian_business.ai_invocation
                           SET context_snapshot_id = :snapshotId, updated_at = :now
                         WHERE invocation_id = :invocationId
                           AND status = 'RUNNING'
                           AND lease_owner = :leaseOwner
                           AND lease_epoch = :leaseEpoch
                           AND lease_until > :now
                           AND (context_snapshot_id IS NULL OR context_snapshot_id = :snapshotId)
                        """)
                .param("snapshotId", persistedId)
                .param("now", Timestamp.from(now))
                .param("invocationId", invocation.invocationId())
                .param("leaseOwner", invocation.leaseOwner())
                .param("leaseEpoch", invocation.leaseEpoch())
                .update();
        requireUpdated(bound);
        return persistedId;
    }

    @Override
    public Optional<InvocationContextAuthoritySnapshot> loadContextAuthority(ClaimedInvocation invocation) {
        return jdbcClient.sql("""
                        SELECT snapshot.context_snapshot_id,
                               snapshot.authorization_snapshot_hash,
                               snapshot.context_hash,
                               snapshot.evidence_refs::text AS evidence_refs,
                               snapshot.fenced_at
                          FROM dianlian_business.ai_invocation invocation
                          JOIN dianlian_business.ai_context_snapshot snapshot
                            ON snapshot.context_snapshot_id = invocation.context_snapshot_id
                           AND snapshot.invocation_id = invocation.invocation_id
                           AND snapshot.tenant_id = invocation.tenant_id
                         WHERE invocation.invocation_id = :invocationId
                           AND invocation.lease_owner = :leaseOwner
                           AND invocation.lease_epoch = :leaseEpoch
                        """)
                .param("invocationId", invocation.invocationId())
                .param("leaseOwner", invocation.leaseOwner())
                .param("leaseEpoch", invocation.leaseEpoch())
                .query((resultSet, rowNumber) -> new InvocationContextAuthoritySnapshot(
                        resultSet.getObject("context_snapshot_id", UUID.class),
                        boundary(invocation, resultSet.getTimestamp("fenced_at").toInstant()),
                        resultSet.getString("authorization_snapshot_hash"),
                        resultSet.getString("context_hash"),
                        readEvidence(resultSet.getString("evidence_refs")),
                        resultSet.getTimestamp("fenced_at").toInstant()
                ))
                .optional();
    }

    @Override
    public void scheduleContextRetry(
            ClaimedInvocation invocation,
            String errorCode,
            Instant retryAt,
            Instant now
    ) {
        int updated = jdbcClient.sql("""
                        UPDATE dianlian_business.ai_invocation
                           SET status = 'QUEUED', error_code = :errorCode, next_attempt_at = :retryAt,
                               lease_owner = NULL, lease_until = NULL, updated_at = :now
                         WHERE invocation_id = :invocationId
                           AND status = 'RUNNING'
                           AND lease_owner = :leaseOwner
                           AND lease_epoch = :leaseEpoch
                           AND lease_until > :now
                        """)
                .param("errorCode", abbreviate(errorCode, 128))
                .param("retryAt", Timestamp.from(retryAt))
                .param("now", Timestamp.from(now))
                .param("invocationId", invocation.invocationId())
                .param("leaseOwner", invocation.leaseOwner())
                .param("leaseEpoch", invocation.leaseEpoch())
                .update();
        requireUpdated(updated);
    }

    @Override
    public boolean lockPreModelAccessCurrent(ClaimedInvocation invocation, Instant now) {
        return lockCurrentAccess(invocation, now, "RUNNING");
    }

    @Override
    public ClaimedInvocation recordProviderResponse(
            ClaimedInvocation invocation,
            ModelChatResponse response,
            Instant startedAt,
            Instant completedAt
    ) {
        insertProviderAttempt(
                invocation, "SUCCEEDED", response.providerRequestId(), response.inputTokens(),
                response.outputTokens(), response.usageConfirmed(), null, startedAt, completedAt);
        int updated = jdbcClient.sql("""
                        UPDATE dianlian_business.ai_invocation
                           SET status = CASE WHEN :usageConfirmed THEN 'RESPONSE_RECEIVED' ELSE 'USAGE_PENDING' END,
                               provider_response_text = :responseText,
                               provider_request_id = :providerRequestId,
                               input_tokens = :inputTokens,
                               output_tokens = :outputTokens,
                               usage_status = CASE WHEN :usageConfirmed THEN 'CONFIRMED' ELSE 'PENDING' END,
                               lease_owner = CASE WHEN :usageConfirmed THEN lease_owner ELSE NULL END,
                               lease_until = CASE WHEN :usageConfirmed THEN lease_until ELSE NULL END,
                               updated_at = :completedAt
                         WHERE invocation_id = :invocationId
                           AND status = 'RUNNING'
                           AND lease_owner = :leaseOwner
                           AND lease_epoch = :leaseEpoch
                           AND lease_until > :completedAt
                        """)
                .param("responseText", response.text())
                .param("providerRequestId", response.providerRequestId())
                .param("inputTokens", response.inputTokens())
                .param("outputTokens", response.outputTokens())
                .param("usageConfirmed", response.usageConfirmed())
                .param("completedAt", Timestamp.from(completedAt))
                .param("invocationId", invocation.invocationId())
                .param("leaseOwner", invocation.leaseOwner())
                .param("leaseEpoch", invocation.leaseEpoch())
                .update();
        requireUpdated(updated);
        return copyWithResponse(invocation, response);
    }

    @Override
    public void recordProviderFailure(
            ClaimedInvocation invocation,
            String errorCode,
            Instant startedAt,
            Instant completedAt
    ) {
        insertProviderAttempt(invocation, "FAILED", null, 0, 0, false, errorCode, startedAt, completedAt);
        int updated = jdbcClient.sql("""
                        UPDATE dianlian_business.ai_invocation
                           SET status = 'FAILED_PROVIDER', error_code = :errorCode,
                               lease_owner = NULL, lease_until = NULL,
                               updated_at = :completedAt, completed_at = :completedAt
                         WHERE invocation_id = :invocationId
                           AND status = 'RUNNING'
                           AND lease_owner = :leaseOwner
                           AND lease_epoch = :leaseEpoch
                        """)
                .param("errorCode", errorCode)
                .param("completedAt", Timestamp.from(completedAt))
                .param("invocationId", invocation.invocationId())
                .param("leaseOwner", invocation.leaseOwner())
                .param("leaseEpoch", invocation.leaseEpoch())
                .update();
        requireUpdated(updated);
    }

    @Override
    public void markContextBlocked(ClaimedInvocation invocation, String errorCode, Instant now) {
        int updated = jdbcClient.sql("""
                        UPDATE dianlian_business.ai_invocation
                           SET status = 'BLOCKED_CONTEXT', error_code = :errorCode,
                               lease_owner = NULL, lease_until = NULL,
                               updated_at = :now, completed_at = :now
                         WHERE invocation_id = :invocationId
                           AND status = 'RUNNING'
                           AND lease_owner = :leaseOwner
                           AND lease_epoch = :leaseEpoch
                        """)
                .param("errorCode", abbreviate(errorCode, 128))
                .param("now", Timestamp.from(now))
                .param("invocationId", invocation.invocationId())
                .param("leaseOwner", invocation.leaseOwner())
                .param("leaseEpoch", invocation.leaseEpoch())
                .update();
        requireUpdated(updated);
    }

    @Override
    public boolean lockPublishAccessCurrent(ClaimedInvocation invocation, Instant now) {
        return lockCurrentAccess(invocation, now, "RESPONSE_RECEIVED");
    }

    private boolean lockCurrentAccess(ClaimedInvocation invocation, Instant now, String expectedStatus) {
        boolean coreAccessCurrent = jdbcClient.sql("""
                        SELECT conversation.membership_version = access.membership_version
                               AND conversation.status = 'ACTIVE'
                               AND tenant.status = 'ACTIVE'
                               AND participant.status = 'ACTIVE'
                               AND member.status = 'ACTIVE'
                               AND (member.expires_at IS NULL OR member.expires_at > :now)
                               AND user_account.status = 'ACTIVE'
                               AND binding.status = 'ACTIVE'
                               AND source.status = 'VISIBLE'
                               AND agent.status = 'ACTIVE'
                               AND agent.agent_version_id = invocation.agent_version_id
                               AND version.status = 'PUBLISHED'
                               AND configuration.status = 'ACTIVE'
                               AND agent.active_configuration_version_id = invocation.configuration_version_id
                               AS access_current
                          FROM dianlian_business.ai_invocation invocation
                          JOIN dianlian_business.conversation conversation
                            ON conversation.tenant_id = invocation.tenant_id
                           AND conversation.conversation_id = invocation.conversation_id
                          JOIN dianlian_business.tenant tenant
                            ON tenant.tenant_id = invocation.tenant_id
                          JOIN dianlian_business.message_access_snapshot access
                            ON access.message_id = invocation.source_message_id
                          JOIN dianlian_business.conversation_message source
                            ON source.tenant_id = invocation.tenant_id
                           AND source.conversation_id = invocation.conversation_id
                           AND source.message_id = invocation.source_message_id
                          JOIN dianlian_business.conversation_participant participant
                            ON participant.tenant_id = invocation.tenant_id
                           AND participant.conversation_id = invocation.conversation_id
                           AND participant.user_id = invocation.requested_by
                          JOIN dianlian_business.tenant_member member
                            ON member.tenant_id = invocation.tenant_id
                           AND member.user_id = invocation.requested_by
                          JOIN dianlian_business.user_account user_account
                            ON user_account.user_id = invocation.requested_by
                          JOIN dianlian_business.conversation_agent_binding binding
                            ON binding.tenant_id = invocation.tenant_id
                           AND binding.conversation_id = invocation.conversation_id
                           AND binding.enterprise_agent_id = invocation.enterprise_agent_id
                          JOIN dianlian_business.enterprise_agent agent
                            ON agent.tenant_id = invocation.tenant_id
                           AND agent.enterprise_agent_id = invocation.enterprise_agent_id
                          JOIN dianlian_business.agent_version version
                            ON version.agent_version_id = invocation.agent_version_id
                          JOIN dianlian_business.enterprise_agent_configuration_version configuration
                            ON configuration.tenant_id = invocation.tenant_id
                           AND configuration.enterprise_agent_id = invocation.enterprise_agent_id
                           AND configuration.configuration_version_id = invocation.configuration_version_id
                         WHERE invocation.invocation_id = :invocationId
                           AND invocation.status = :expectedStatus
                           AND invocation.lease_owner = :leaseOwner
                           AND invocation.lease_epoch = :leaseEpoch
                           AND invocation.lease_until > :now
                         FOR UPDATE OF invocation, conversation, tenant, participant, member,
                                       user_account, binding, source, agent, version, configuration
                        """)
                .param("invocationId", invocation.invocationId())
                .param("leaseOwner", invocation.leaseOwner())
                .param("leaseEpoch", invocation.leaseEpoch())
                .param("now", Timestamp.from(now))
                .param("expectedStatus", expectedStatus)
                .query(Boolean.class)
                .optional()
                .orElse(false);
        if (!coreAccessCurrent || invocation.audienceUserIds().isEmpty()) return false;
        var activeAudience = jdbcClient.sql("""
                        SELECT member.user_id
                          FROM dianlian_business.tenant_member member
                          JOIN dianlian_business.user_account user_account
                            ON user_account.user_id = member.user_id
                          JOIN dianlian_business.conversation_participant participant
                            ON participant.tenant_id = member.tenant_id
                           AND participant.user_id = member.user_id
                           AND participant.conversation_id = :conversationId
                         WHERE member.tenant_id = :tenantId
                           AND member.user_id IN (:audienceUserIds)
                           AND member.status = 'ACTIVE'
                           AND (member.expires_at IS NULL OR member.expires_at > :now)
                           AND user_account.status = 'ACTIVE'
                           AND participant.status = 'ACTIVE'
                         FOR UPDATE OF member, user_account, participant
                        """)
                .param("conversationId", invocation.conversationId())
                .param("tenantId", invocation.tenantId())
                .param("audienceUserIds", invocation.audienceUserIds())
                .param("now", Timestamp.from(now))
                .query(UUID.class)
                .list();
        return activeAudience.size() == invocation.audienceUserIds().stream().distinct().count();
    }

    @Override
    public void markAccessBlocked(ClaimedInvocation invocation, String errorCode, Instant now) {
        int updated = jdbcClient.sql("""
                        UPDATE dianlian_business.ai_invocation
                           SET status = 'BLOCKED_ACCESS', error_code = :errorCode,
                               lease_owner = NULL, lease_until = NULL,
                               updated_at = :now, completed_at = :now
                         WHERE invocation_id = :invocationId
                           AND status IN ('RUNNING', 'RESPONSE_RECEIVED')
                           AND lease_owner = :leaseOwner
                           AND lease_epoch = :leaseEpoch
                        """)
                .param("errorCode", abbreviate(errorCode, 128))
                .param("now", Timestamp.from(now))
                .param("invocationId", invocation.invocationId())
                .param("leaseOwner", invocation.leaseOwner())
                .param("leaseEpoch", invocation.leaseEpoch())
                .update();
        requireUpdated(updated);
    }

    @Override
    public void publishResponse(ClaimedInvocation invocation, long capturedMicroCredit, Instant now) {
        requireLease(invocation, now);
        Long sequenceNo = jdbcClient.sql("""
                        UPDATE dianlian_business.conversation
                           SET next_sequence_no = next_sequence_no + 1, updated_at = :now
                         WHERE tenant_id = :tenantId AND conversation_id = :conversationId
                        RETURNING next_sequence_no - 1
                        """)
                .param("now", Timestamp.from(now))
                .param("tenantId", invocation.tenantId())
                .param("conversationId", invocation.conversationId())
                .query(Long.class)
                .single();
        UUID responseMessageId = UUID.randomUUID();
        jdbcClient.sql("""
                        INSERT INTO dianlian_business.conversation_message
                            (message_id, tenant_id, conversation_id, sequence_no, sender_type,
                             sender_agent_id, body_text, status, created_at)
                        VALUES
                            (:messageId, :tenantId, :conversationId, :sequenceNo, 'AGENT',
                             :agentId, :bodyText, 'VISIBLE', :createdAt)
                        """)
                .param("messageId", responseMessageId)
                .param("tenantId", invocation.tenantId())
                .param("conversationId", invocation.conversationId())
                .param("sequenceNo", sequenceNo)
                .param("agentId", invocation.enterpriseAgentId())
                .param("bodyText", invocation.providerResponseText())
                .param("createdAt", Timestamp.from(now))
                .update();
        int updated = jdbcClient.sql("""
                        UPDATE dianlian_business.ai_invocation
                           SET status = 'COMPLETED', response_message_id = :responseMessageId,
                               captured_micro_credit = :capturedMicroCredit,
                               lease_owner = NULL, lease_until = NULL,
                               updated_at = :now, completed_at = :now
                         WHERE invocation_id = :invocationId
                           AND status = 'RESPONSE_RECEIVED'
                           AND lease_owner = :leaseOwner
                           AND lease_epoch = :leaseEpoch
                        """)
                .param("responseMessageId", responseMessageId)
                .param("capturedMicroCredit", capturedMicroCredit)
                .param("now", Timestamp.from(now))
                .param("invocationId", invocation.invocationId())
                .param("leaseOwner", invocation.leaseOwner())
                .param("leaseEpoch", invocation.leaseEpoch())
                .update();
        requireUpdated(updated);
    }

    private Optional<ClaimedInvocation> loadClaimed(UUID invocationId, Instant now) {
        return jdbcClient.sql("""
                        SELECT invocation.*,
                               conversation.conversation_type,
                               conversation.membership_version AS current_membership_version,
                               source.sequence_no AS source_sequence_no,
                               source.body_text AS user_query,
                               source.status AS source_message_status,
                               access.membership_version AS snapshot_membership_version,
                               access.policy_version,
                               access.history_floor_sequence_no,
                               access.audience_user_ids::text AS audience_user_ids,
                               participant.status AS requester_membership_status,
                               member.status AS tenant_membership_status,
                               member.expires_at AS tenant_membership_expires_at,
                               user_account.status AS user_status,
                               tenant.status AS tenant_status,
                               binding.status AS agent_binding_status,
                               agent.status AS agent_status,
                               agent.agent_version_id AS current_agent_version_id,
                               version.status AS agent_version_status,
                               configuration.status AS configuration_status,
                               agent.active_configuration_version_id
                          FROM dianlian_business.ai_invocation invocation
                          JOIN dianlian_business.conversation conversation
                            ON conversation.tenant_id = invocation.tenant_id
                           AND conversation.conversation_id = invocation.conversation_id
                          JOIN dianlian_business.tenant tenant
                            ON tenant.tenant_id = invocation.tenant_id
                          JOIN dianlian_business.conversation_message source
                            ON source.message_id = invocation.source_message_id
                          JOIN dianlian_business.message_access_snapshot access
                            ON access.message_id = invocation.source_message_id
                          LEFT JOIN dianlian_business.conversation_participant participant
                            ON participant.tenant_id = invocation.tenant_id
                           AND participant.conversation_id = invocation.conversation_id
                           AND participant.user_id = invocation.requested_by
                          LEFT JOIN dianlian_business.tenant_member member
                            ON member.tenant_id = invocation.tenant_id
                           AND member.user_id = invocation.requested_by
                          LEFT JOIN dianlian_business.user_account user_account
                            ON user_account.user_id = invocation.requested_by
                          LEFT JOIN dianlian_business.conversation_agent_binding binding
                            ON binding.tenant_id = invocation.tenant_id
                           AND binding.conversation_id = invocation.conversation_id
                           AND binding.enterprise_agent_id = invocation.enterprise_agent_id
                          JOIN dianlian_business.enterprise_agent agent
                            ON agent.tenant_id = invocation.tenant_id
                           AND agent.enterprise_agent_id = invocation.enterprise_agent_id
                          JOIN dianlian_business.agent_version version
                            ON version.agent_version_id = invocation.agent_version_id
                          JOIN dianlian_business.enterprise_agent_configuration_version configuration
                            ON configuration.tenant_id = invocation.tenant_id
                           AND configuration.enterprise_agent_id = invocation.enterprise_agent_id
                           AND configuration.configuration_version_id = invocation.configuration_version_id
                         WHERE invocation.invocation_id = :invocationId
                        """)
                .param("invocationId", invocationId)
                .query((resultSet, rowNumber) -> mapClaimed(resultSet, rowNumber, now))
                .optional();
    }

    private ClaimedInvocation mapClaimed(ResultSet resultSet, int rowNumber, Instant now) throws SQLException {
        boolean accessStillCurrent = resultSet.getLong("current_membership_version")
                == resultSet.getLong("snapshot_membership_version")
                && "ACTIVE".equals(resultSet.getString("tenant_status"))
                && "ACTIVE".equals(resultSet.getString("requester_membership_status"))
                && "ACTIVE".equals(resultSet.getString("tenant_membership_status"))
                && (resultSet.getTimestamp("tenant_membership_expires_at") == null
                        || resultSet.getTimestamp("tenant_membership_expires_at").toInstant().isAfter(now))
                && "ACTIVE".equals(resultSet.getString("user_status"))
                && "ACTIVE".equals(resultSet.getString("agent_binding_status"))
                && "VISIBLE".equals(resultSet.getString("source_message_status"))
                && "ACTIVE".equals(resultSet.getString("agent_status"))
                && resultSet.getObject("agent_version_id", UUID.class)
                        .equals(resultSet.getObject("current_agent_version_id", UUID.class))
                && "PUBLISHED".equals(resultSet.getString("agent_version_status"))
                && "ACTIVE".equals(resultSet.getString("configuration_status"))
                && resultSet.getObject("configuration_version_id", UUID.class)
                        .equals(resultSet.getObject("active_configuration_version_id", UUID.class));
        return new ClaimedInvocation(
                resultSet.getObject("invocation_id", UUID.class),
                resultSet.getObject("tenant_id", UUID.class),
                resultSet.getObject("conversation_id", UUID.class),
                "GROUP".equals(resultSet.getString("conversation_type")),
                resultSet.getObject("source_message_id", UUID.class),
                resultSet.getLong("source_sequence_no"),
                resultSet.getLong("snapshot_membership_version"),
                resultSet.getString("policy_version"),
                resultSet.getLong("history_floor_sequence_no"),
                resultSet.getString("user_query"),
                resultSet.getObject("requested_by", UUID.class),
                resultSet.getObject("enterprise_agent_id", UUID.class),
                resultSet.getObject("agent_version_id", UUID.class),
                resultSet.getObject("configuration_version_id", UUID.class),
                resultSet.getString("role_name_snapshot"),
                resultSet.getString("platform_profile_snapshot"),
                resultSet.getString("enterprise_instructions_snapshot"),
                resultSet.getString("knowledge_scope_mode_snapshot"),
                resultSet.getObject("model_route_binding_id", UUID.class),
                resultSet.getObject("model_definition_id", UUID.class),
                resultSet.getObject("point_reservation_id", UUID.class),
                readUuidList(resultSet.getString("audience_user_ids")),
                accessStillCurrent,
                resultSet.getString("status"),
                resultSet.getInt("attempt_count"),
                resultSet.getLong("lease_epoch"),
                resultSet.getString("lease_owner"),
                resultSet.getString("provider_response_text"),
                resultSet.getInt("input_tokens"),
                resultSet.getInt("output_tokens"),
                "CONFIRMED".equals(resultSet.getString("usage_status")),
                resultSet.getString("provider_request_id")
        );
    }

    private void insertProviderAttempt(
            ClaimedInvocation invocation,
            String status,
            String providerRequestId,
            int inputTokens,
            int outputTokens,
            boolean usageConfirmed,
            String errorCode,
            Instant startedAt,
            Instant completedAt
    ) {
        requireLease(invocation, completedAt);
        jdbcClient.sql("""
                        INSERT INTO dianlian_business.provider_attempt
                            (provider_attempt_id, invocation_id, attempt_no, model_definition_id,
                             status, provider_request_id, input_tokens, output_tokens, error_code,
                             usage_status, started_at, completed_at)
                        VALUES
                            (:attemptId, :invocationId, :attemptNo, :modelDefinitionId,
                             :status, :providerRequestId, :inputTokens, :outputTokens, :errorCode,
                             :usageStatus, :startedAt, :completedAt)
                        """)
                .param("attemptId", UUID.randomUUID())
                .param("invocationId", invocation.invocationId())
                .param("attemptNo", invocation.attemptNo())
                .param("modelDefinitionId", invocation.modelDefinitionId())
                .param("status", status)
                .param("providerRequestId", providerRequestId)
                .param("inputTokens", inputTokens)
                .param("outputTokens", outputTokens)
                .param("errorCode", errorCode)
                .param("usageStatus", usageConfirmed ? "CONFIRMED" : "PENDING")
                .param("startedAt", Timestamp.from(startedAt))
                .param("completedAt", Timestamp.from(completedAt))
                .update();
    }

    private void requireLease(ClaimedInvocation invocation, Instant now) {
        Integer count = jdbcClient.sql("""
                        SELECT COUNT(*)
                          FROM dianlian_business.ai_invocation
                         WHERE invocation_id = :invocationId
                           AND lease_owner = :leaseOwner
                           AND lease_epoch = :leaseEpoch
                           AND lease_until > :now
                           AND status IN ('RUNNING', 'RESPONSE_RECEIVED')
                        """)
                .param("invocationId", invocation.invocationId())
                .param("leaseOwner", invocation.leaseOwner())
                .param("leaseEpoch", invocation.leaseEpoch())
                .param("now", Timestamp.from(now))
                .query(Integer.class)
                .single();
        if (count != 1) throw new ConcurrencyFailureException("AI invocation lease is no longer valid");
    }

    private static void requireUpdated(int updated) {
        if (updated != 1) throw new ConcurrencyFailureException("AI invocation lease fencing rejected the update");
    }

    private ClaimedInvocation copyWithResponse(ClaimedInvocation source, ModelChatResponse response) {
        return new ClaimedInvocation(
                source.invocationId(), source.tenantId(), source.conversationId(), source.groupConversation(),
                source.sourceMessageId(), source.sourceSequenceNo(), source.membershipVersion(),
                source.policyVersion(), source.historyFloorSequenceNo(),
                source.userQuery(), source.requestedBy(),
                source.enterpriseAgentId(), source.agentVersionId(), source.configurationVersionId(),
                source.roleName(), source.platformProfile(), source.enterpriseInstructions(),
                source.knowledgeScopeMode(), source.modelRouteBindingId(), source.modelDefinitionId(),
                source.pointReservationId(), source.audienceUserIds(), source.accessStillCurrent(),
                response.usageConfirmed() ? "RESPONSE_RECEIVED" : "USAGE_PENDING",
                source.attemptNo(), source.leaseEpoch(),
                response.usageConfirmed() ? source.leaseOwner() : null,
                response.text(), response.inputTokens(), response.outputTokens(), response.usageConfirmed(),
                response.providerRequestId()
        );
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("failed to serialize AI context boundary", exception);
        }
    }

    private List<UUID> readUuidList(String value) {
        try {
            return objectMapper.readValue(value, UUID_LIST);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("failed to deserialize message audience", exception);
        }
    }

    private List<ContextAuthorityPort.EvidenceIdentity> readEvidence(String value) {
        try {
            return objectMapper.readValue(value, EVIDENCE_LIST);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("failed to deserialize AI context evidence authority", exception);
        }
    }

    private static ContextAuthorityPort.InvocationBoundary boundary(
            ClaimedInvocation invocation,
            Instant observedAt
    ) {
        return new ContextAuthorityPort.InvocationBoundary(
                invocation.tenantId(), invocation.requestedBy(), invocation.enterpriseAgentId(),
                invocation.agentVersionId(), invocation.configurationVersionId(), invocation.conversationId(),
                invocation.groupConversation(), invocation.sourceMessageId(), invocation.sourceSequenceNo(),
                invocation.membershipVersion(), invocation.policyVersion(), invocation.audienceUserIds(),
                invocation.historyFloorSequenceNo(), observedAt
        );
    }

    private static String abbreviate(String value, int maxLength) {
        if (value == null || value.isBlank()) return "UNKNOWN";
        return value.length() <= maxLength ? value : value.substring(0, maxLength);
    }
}

package com.dianlian.platform.interaction.infrastructure;

import com.dianlian.platform.context.api.ContextSourceState;
import com.dianlian.platform.interaction.api.ConversationAgentView;
import com.dianlian.platform.interaction.api.ConversationMessagePage;
import com.dianlian.platform.interaction.api.ConversationMessageView;
import com.dianlian.platform.interaction.api.ConversationMemberView;
import com.dianlian.platform.interaction.api.ConversationNotDiscoverableException;
import com.dianlian.platform.interaction.api.ConversationStatus;
import com.dianlian.platform.interaction.api.ConversationSummary;
import com.dianlian.platform.interaction.api.ConversationType;
import com.dianlian.platform.interaction.api.MessageSenderType;
import com.dianlian.platform.interaction.application.ConversationRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcConversationRepository implements ConversationRepository {

    private static final TypeReference<List<UUID>> UUID_LIST = new TypeReference<>() {
    };

    private final JdbcClient jdbcClient;
    private final ObjectMapper objectMapper;

    public JdbcConversationRepository(JdbcClient jdbcClient, ObjectMapper objectMapper) {
        this.jdbcClient = jdbcClient;
        this.objectMapper = objectMapper;
    }

    @Override
    public Optional<StoredConversationIntent> findConversationIntent(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        return jdbcClient.sql("""
                        SELECT conversation_id, request_hash
                          FROM dianlian_business.conversation
                         WHERE tenant_id = :tenantId
                           AND created_by = :actorId
                           AND idempotency_key = :idempotencyKey
                        """)
                .param("tenantId", tenantId)
                .param("actorId", actorId)
                .param("idempotencyKey", idempotencyKey)
                .query((resultSet, rowNumber) -> new StoredConversationIntent(
                        requireSummary(tenantId, actorId, resultSet.getObject("conversation_id", UUID.class)),
                        resultSet.getString("request_hash")
                ))
                .optional();
    }

    @Override
    public void requireActiveTenantMembers(UUID tenantId, List<UUID> userIds) {
        if (userIds.isEmpty()) throw new IllegalArgumentException("userIds must not be empty");
        Integer count = jdbcClient.sql("""
                        SELECT COUNT(*)
                          FROM dianlian_business.tenant_member tm
                          JOIN dianlian_business.user_account u ON u.user_id = tm.user_id
                         WHERE tm.tenant_id = :tenantId
                           AND tm.user_id IN (:userIds)
                           AND tm.status = 'ACTIVE'
                           AND (tm.expires_at IS NULL OR tm.expires_at > CURRENT_TIMESTAMP)
                           AND u.status = 'ACTIVE'
                        """)
                .param("tenantId", tenantId)
                .param("userIds", userIds)
                .query(Integer.class)
                .single();
        if (count != userIds.size()) throw new ConversationNotDiscoverableException();
    }

    @Override
    public ConversationSummary createConversation(CreateConversationWrite write) {
        jdbcClient.sql("""
                        INSERT INTO dianlian_business.conversation
                            (conversation_id, tenant_id, conversation_type, title, status,
                             history_policy, membership_version, next_sequence_no,
                             request_hash, idempotency_key, created_by, created_at, updated_at)
                        VALUES
                            (:conversationId, :tenantId, :type, :title, 'ACTIVE',
                             'NO_PREJOIN_HISTORY', 1, 1,
                             :requestHash, :idempotencyKey, :actorId, :createdAt, :createdAt)
                        """)
                .param("conversationId", write.conversationId())
                .param("tenantId", write.tenantId())
                .param("type", write.type().name())
                .param("title", write.title())
                .param("requestHash", write.requestHash())
                .param("idempotencyKey", write.idempotencyKey())
                .param("actorId", write.actorId())
                .param("createdAt", Timestamp.from(write.createdAt()))
                .update();
        for (UUID userId : write.participantUserIds()) {
            jdbcClient.sql("""
                            INSERT INTO dianlian_business.conversation_participant
                                (conversation_id, tenant_id, user_id, participant_role, status,
                                 joined_sequence_no, joined_at)
                            VALUES (:conversationId, :tenantId, :userId, :role, 'ACTIVE', 0, :joinedAt)
                            """)
                    .param("conversationId", write.conversationId())
                    .param("tenantId", write.tenantId())
                    .param("userId", userId)
                    .param("role", userId.equals(write.actorId()) ? "OWNER" : "MEMBER")
                    .param("joinedAt", Timestamp.from(write.createdAt()))
                    .update();
        }
        for (UUID agentId : write.enterpriseAgentIds()) {
            jdbcClient.sql("""
                            INSERT INTO dianlian_business.conversation_agent_binding
                                (conversation_id, tenant_id, enterprise_agent_id, status,
                                 bound_sequence_no, bound_by, bound_at)
                            VALUES (:conversationId, :tenantId, :agentId, 'ACTIVE', 0, :actorId, :boundAt)
                            """)
                    .param("conversationId", write.conversationId())
                    .param("tenantId", write.tenantId())
                    .param("agentId", agentId)
                    .param("actorId", write.actorId())
                    .param("boundAt", Timestamp.from(write.createdAt()))
                    .update();
        }
        return requireSummary(write.tenantId(), write.actorId(), write.conversationId());
    }

    @Override
    public ConversationState lockVisibleConversation(UUID tenantId, UUID actorId, UUID conversationId) {
        var header = jdbcClient.sql("""
                        SELECT c.conversation_id, c.tenant_id, c.conversation_type, c.membership_version,
                               GREATEST(
                                   COALESCE((
                                       SELECT MAX(member.joined_sequence_no)
                                         FROM dianlian_business.conversation_participant member
                                        WHERE member.tenant_id = c.tenant_id
                                          AND member.conversation_id = c.conversation_id
                                          AND member.status = 'ACTIVE'
                                   ), 0),
                                   COALESCE((
                                       SELECT MAX(binding.bound_sequence_no)
                                         FROM dianlian_business.conversation_agent_binding binding
                                        WHERE binding.tenant_id = c.tenant_id
                                          AND binding.conversation_id = c.conversation_id
                                          AND binding.status = 'ACTIVE'
                                   ), 0)
                               ) AS history_floor_sequence_no
                          FROM dianlian_business.conversation c
                          JOIN dianlian_business.conversation_participant p
                            ON p.tenant_id = c.tenant_id
                           AND p.conversation_id = c.conversation_id
                           AND p.user_id = :actorId
                           AND p.status = 'ACTIVE'
                         WHERE c.tenant_id = :tenantId
                           AND c.conversation_id = :conversationId
                           AND c.status = 'ACTIVE'
                         FOR UPDATE OF c
                        """)
                .param("tenantId", tenantId)
                .param("actorId", actorId)
                .param("conversationId", conversationId)
                .query((resultSet, rowNumber) -> new ConversationState(
                        resultSet.getObject("conversation_id", UUID.class),
                        resultSet.getObject("tenant_id", UUID.class),
                        ConversationType.valueOf(resultSet.getString("conversation_type")),
                        resultSet.getLong("membership_version"),
                        resultSet.getLong("history_floor_sequence_no"),
                        activeHumanIds(tenantId, conversationId),
                        activeAgentIds(tenantId, conversationId)
                ))
                .optional();
        return header.orElseThrow(ConversationNotDiscoverableException::new);
    }

    @Override
    public Optional<StoredMessageIntent> findMessageIntent(
            UUID tenantId,
            UUID actorId,
            UUID conversationId,
            String idempotencyKey
    ) {
        return jdbcClient.sql("""
                        SELECT m.*, u.display_name AS sender_display_name, u.avatar_url AS sender_avatar_url,
                               NULL::VARCHAR AS ai_status,
                               NULL::VARCHAR AS knowledge_state,
                               NULL::VARCHAR AS memory_state,
                               0::BIGINT AS charged_micro_credit,
                               '[]'::JSONB::TEXT AS target_agent_ids
                          FROM dianlian_business.conversation_message m
                          JOIN dianlian_business.user_account u ON u.user_id = m.sender_user_id
                         WHERE m.tenant_id = :tenantId
                           AND m.conversation_id = :conversationId
                           AND m.sender_user_id = :actorId
                           AND m.idempotency_key = :idempotencyKey
                        """)
                .param("tenantId", tenantId)
                .param("conversationId", conversationId)
                .param("actorId", actorId)
                .param("idempotencyKey", idempotencyKey)
                .query((resultSet, rowNumber) -> new StoredMessageIntent(
                        mapMessage(resultSet, rowNumber),
                        resultSet.getString("request_hash")
                ))
                .optional();
    }

    @Override
    public void requireReplyMessage(UUID tenantId, UUID conversationId, UUID replyToMessageId) {
        Integer count = jdbcClient.sql("""
                        SELECT COUNT(*)
                          FROM dianlian_business.conversation_message
                         WHERE tenant_id = :tenantId
                           AND conversation_id = :conversationId
                           AND message_id = :messageId
                           AND status = 'VISIBLE'
                        """)
                .param("tenantId", tenantId)
                .param("conversationId", conversationId)
                .param("messageId", replyToMessageId)
                .query(Integer.class)
                .single();
        if (count != 1) throw new ConversationNotDiscoverableException();
    }

    @Override
    public void requireReplyMessageFromAgent(
            UUID tenantId,
            UUID conversationId,
            UUID replyToMessageId,
            UUID enterpriseAgentId
    ) {
        Integer count = jdbcClient.sql("""
                        SELECT COUNT(*)
                          FROM dianlian_business.conversation_message
                         WHERE tenant_id = :tenantId
                           AND conversation_id = :conversationId
                           AND message_id = :messageId
                           AND sender_type = 'AGENT'
                           AND sender_agent_id = :agentId
                           AND status = 'VISIBLE'
                        """)
                .param("tenantId", tenantId)
                .param("conversationId", conversationId)
                .param("messageId", replyToMessageId)
                .param("agentId", enterpriseAgentId)
                .query(Integer.class)
                .single();
        if (count != 1) throw new ConversationNotDiscoverableException();
    }

    @Override
    public ConversationMessageView appendHumanMessage(AppendHumanMessageWrite write) {
        Long sequenceNo = jdbcClient.sql("""
                        UPDATE dianlian_business.conversation
                           SET next_sequence_no = next_sequence_no + 1,
                               updated_at = :updatedAt
                         WHERE tenant_id = :tenantId AND conversation_id = :conversationId
                        RETURNING next_sequence_no - 1
                        """)
                .param("updatedAt", Timestamp.from(write.createdAt()))
                .param("tenantId", write.tenantId())
                .param("conversationId", write.conversationId())
                .query(Long.class)
                .single();
        return jdbcClient.sql("""
                        INSERT INTO dianlian_business.conversation_message
                            (message_id, tenant_id, conversation_id, sequence_no,
                             sender_type, sender_user_id, client_message_id, idempotency_key,
                             request_hash, body_text, reply_to_message_id, collaboration_mode,
                             primary_agent_id, status, created_at)
                        VALUES
                            (:messageId, :tenantId, :conversationId, :sequenceNo,
                             'HUMAN', :actorId, :clientMessageId, :idempotencyKey,
                             :requestHash, :bodyText, :replyToMessageId, :collaborationMode,
                             :primaryAgentId, 'VISIBLE', :createdAt)
                        RETURNING *
                        """)
                .param("messageId", write.messageId())
                .param("tenantId", write.tenantId())
                .param("conversationId", write.conversationId())
                .param("sequenceNo", sequenceNo)
                .param("actorId", write.actorId())
                .param("clientMessageId", write.clientMessageId())
                .param("idempotencyKey", write.idempotencyKey())
                .param("requestHash", write.requestHash())
                .param("bodyText", write.text())
                .param("replyToMessageId", write.replyToMessageId())
                .param("collaborationMode", write.collaborationMode().name())
                .param("primaryAgentId", write.primaryAgentId())
                .param("createdAt", Timestamp.from(write.createdAt()))
                .query((resultSet, rowNumber) -> new ConversationMessageView(
                        resultSet.getObject("message_id", UUID.class),
                        resultSet.getObject("conversation_id", UUID.class),
                        resultSet.getLong("sequence_no"),
                        MessageSenderType.HUMAN,
                        write.actorId(),
                        null,
                        userDisplayName(write.actorId()),
                        userAvatar(write.actorId()),
                        resultSet.getString("body_text"),
                        resultSet.getObject("reply_to_message_id", UUID.class),
                        List.of(),
                        null,
                        null,
                        null,
                        0,
                        resultSet.getTimestamp("created_at").toInstant()
                ))
                .single();
    }

    @Override
    public UUID appendTarget(AppendTargetWrite write) {
        jdbcClient.sql("""
                        INSERT INTO dianlian_business.message_target
                            (message_target_id, tenant_id, conversation_id, message_id,
                             enterprise_agent_id, trigger_type, reply_to_message_id, created_at)
                        VALUES
                            (:targetId, :tenantId, :conversationId, :messageId,
                             :agentId, :triggerType, :replyToMessageId, :createdAt)
                        """)
                .param("targetId", write.targetId())
                .param("tenantId", write.tenantId())
                .param("conversationId", write.conversationId())
                .param("messageId", write.messageId())
                .param("agentId", write.enterpriseAgentId())
                .param("triggerType", write.triggerType().name())
                .param("replyToMessageId", write.replyToMessageId())
                .param("createdAt", Timestamp.from(write.createdAt()))
                .update();
        return write.targetId();
    }

    @Override
    public void appendAccessSnapshot(AppendAccessSnapshotWrite write) {
        jdbcClient.sql("""
                        INSERT INTO dianlian_business.message_access_snapshot
                            (message_id, tenant_id, conversation_id, membership_version,
                             history_floor_sequence_no,
                             audience_user_ids, allowed_agent_ids, knowledge_scope_version,
                             policy_version, created_at)
                        VALUES
                            (:messageId, :tenantId, :conversationId, :membershipVersion,
                             :historyFloorSequenceNo,
                             CAST(:audienceUserIds AS JSONB), CAST(:allowedAgentIds AS JSONB),
                             :knowledgeScopeVersion, :policyVersion, :createdAt)
                        """)
                .param("messageId", write.messageId())
                .param("tenantId", write.tenantId())
                .param("conversationId", write.conversationId())
                .param("membershipVersion", write.membershipVersion())
                .param("historyFloorSequenceNo", write.historyFloorSequenceNo())
                .param("audienceUserIds", writeJson(write.audienceUserIds()))
                .param("allowedAgentIds", writeJson(write.allowedAgentIds()))
                .param("knowledgeScopeVersion", write.knowledgeScopeVersion())
                .param("policyVersion", write.policyVersion())
                .param("createdAt", Timestamp.from(write.createdAt()))
                .update();
    }

    @Override
    public void appendInvocation(AppendInvocationWrite write) {
        jdbcClient.sql("""
                        INSERT INTO dianlian_business.ai_invocation
                            (invocation_id, tenant_id, conversation_id, source_message_id,
                             message_target_id, requested_by, enterprise_agent_id,
                             agent_version_id, configuration_version_id, role_name_snapshot,
                             platform_profile_snapshot, enterprise_instructions_snapshot,
                             knowledge_scope_mode_snapshot, model_route_binding_id,
                             model_route_state_version, model_definition_id, point_reservation_id,
                             status, attempt_count, next_attempt_at, created_at, updated_at)
                        VALUES
                            (:invocationId, :tenantId, :conversationId, :sourceMessageId,
                             :messageTargetId, :requestedBy, :agentId,
                             :agentVersionId, :configurationVersionId, :roleName,
                             :platformProfile, :enterpriseInstructions,
                             :knowledgeScopeMode, :routeBindingId,
                             :routeStateVersion, :modelDefinitionId, :reservationId,
                             'QUEUED', 0, :createdAt, :createdAt, :createdAt)
                        """)
                .param("invocationId", write.invocationId())
                .param("tenantId", write.tenantId())
                .param("conversationId", write.conversationId())
                .param("sourceMessageId", write.sourceMessageId())
                .param("messageTargetId", write.messageTargetId())
                .param("requestedBy", write.requestedBy())
                .param("agentId", write.enterpriseAgentId())
                .param("agentVersionId", write.agentVersionId())
                .param("configurationVersionId", write.configurationVersionId())
                .param("roleName", write.roleName())
                .param("platformProfile", write.platformProfile())
                .param("enterpriseInstructions", write.enterpriseInstructions())
                .param("knowledgeScopeMode", write.knowledgeScopeMode())
                .param("routeBindingId", write.route().routeBindingId())
                .param("routeStateVersion", write.route().routeStateVersion())
                .param("modelDefinitionId", write.route().model().modelDefinitionId())
                .param("reservationId", write.pointReservationId())
                .param("createdAt", Timestamp.from(write.createdAt()))
                .update();
    }

    @Override
    public List<UUID> listInvocationIds(UUID tenantId, UUID sourceMessageId) {
        return jdbcClient.sql("""
                        SELECT invocation_id
                          FROM dianlian_business.ai_invocation
                         WHERE tenant_id = :tenantId AND source_message_id = :sourceMessageId
                         ORDER BY created_at, invocation_id
                        """)
                .param("tenantId", tenantId)
                .param("sourceMessageId", sourceMessageId)
                .query(UUID.class)
                .list();
    }

    @Override
    public List<ConversationSummary> listVisible(UUID tenantId, UUID actorId, int limit) {
        return jdbcClient.sql("""
                        SELECT c.conversation_id
                          FROM dianlian_business.conversation c
                          JOIN dianlian_business.conversation_participant p
                            ON p.tenant_id = c.tenant_id
                           AND p.conversation_id = c.conversation_id
                           AND p.user_id = :actorId
                           AND p.status = 'ACTIVE'
                         WHERE c.tenant_id = :tenantId AND c.status = 'ACTIVE'
                         ORDER BY c.updated_at DESC, c.conversation_id
                         LIMIT :limit
                        """)
                .param("tenantId", tenantId)
                .param("actorId", actorId)
                .param("limit", limit)
                .query(UUID.class)
                .list()
                .stream()
                .map(conversationId -> requireSummary(tenantId, actorId, conversationId))
                .toList();
    }

    @Override
    public ConversationMessagePage listMessages(
            UUID tenantId,
            UUID actorId,
            UUID conversationId,
            long afterSequenceNo,
            int limit
    ) {
        var state = readVisibleState(tenantId, actorId, conversationId)
                .orElseThrow(ConversationNotDiscoverableException::new);
        var messages = jdbcClient.sql("""
                        SELECT m.*,
                               COALESCE(u.display_name, c.display_name_snapshot, '系统') AS sender_display_name,
                               u.avatar_url AS sender_avatar_url,
                               COALESCE(response_invocation.status, source_invocation.status) AS ai_status,
                               context.knowledge_state,
                               context.memory_state,
                               COALESCE(response_invocation.captured_micro_credit,
                                        source_invocation.total_captured_micro_credit, 0) AS charged_micro_credit,
                               COALESCE((
                                   SELECT JSONB_AGG(target.enterprise_agent_id ORDER BY target.enterprise_agent_id)
                                     FROM dianlian_business.message_target target
                                    WHERE target.message_id = m.message_id
                               ), '[]'::JSONB)::text AS target_agent_ids
                          FROM dianlian_business.conversation_message m
                          LEFT JOIN dianlian_business.user_account u ON u.user_id = m.sender_user_id
                          LEFT JOIN dianlian_business.enterprise_agent_configuration_version c
                            ON c.tenant_id = m.tenant_id
                           AND c.enterprise_agent_id = m.sender_agent_id
                           AND c.status = 'ACTIVE'
                          LEFT JOIN dianlian_business.ai_invocation response_invocation
                            ON response_invocation.response_message_id = m.message_id
                          LEFT JOIN LATERAL (
                              SELECT candidate.invocation_id,
                                     candidate.context_snapshot_id,
                                     candidate.status,
                                     candidate.total_captured_micro_credit
                                FROM (
                                    SELECT source.invocation_id,
                                           source.context_snapshot_id,
                                           source.status,
                                           SUM(source.captured_micro_credit) OVER ()
                                               AS total_captured_micro_credit,
                                           CASE source.status
                                               WHEN 'USAGE_PENDING' THEN 0
                                               WHEN 'RUNNING' THEN 1
                                               WHEN 'RESPONSE_RECEIVED' THEN 2
                                               WHEN 'QUEUED' THEN 3
                                               WHEN 'BLOCKED_ACCESS' THEN 4
                                               WHEN 'BLOCKED_CONTEXT' THEN 5
                                               WHEN 'FAILED_BILLING' THEN 6
                                               WHEN 'FAILED_PROVIDER' THEN 7
                                               ELSE 8
                                           END AS status_priority
                                      FROM dianlian_business.ai_invocation source
                                     WHERE source.tenant_id = m.tenant_id
                                       AND source.conversation_id = m.conversation_id
                                       AND source.source_message_id = m.message_id
                                ) candidate
                               ORDER BY candidate.status_priority, candidate.invocation_id
                               LIMIT 1
                          ) source_invocation ON m.sender_type = 'HUMAN'
                          LEFT JOIN dianlian_business.ai_context_snapshot context
                            ON context.context_snapshot_id = COALESCE(
                                response_invocation.context_snapshot_id,
                                source_invocation.context_snapshot_id
                            )
                         WHERE m.tenant_id = :tenantId
                           AND m.conversation_id = :conversationId
                           AND m.sequence_no > :afterSequenceNo
                           AND m.sequence_no > :joinedSequenceNo
                           AND m.status = 'VISIBLE'
                         ORDER BY m.sequence_no
                         LIMIT :fetchLimit
                        """)
                .param("tenantId", tenantId)
                .param("conversationId", conversationId)
                .param("afterSequenceNo", afterSequenceNo)
                .param("joinedSequenceNo", state.joinedSequenceNo())
                .param("fetchLimit", limit + 1)
                .query(this::mapMessage)
                .list();
        boolean hasMore = messages.size() > limit;
        var items = hasMore ? messages.subList(0, limit) : messages;
        return new ConversationMessagePage(
                items,
                state.upToSequenceNo(),
                hasMore,
                state.membershipVersion()
        );
    }

    private ConversationSummary requireSummary(UUID tenantId, UUID actorId, UUID conversationId) {
        return jdbcClient.sql("""
                        SELECT c.conversation_id, c.conversation_type, c.title, c.status,
                               c.membership_version,
                               last_message.body_text AS last_message_preview,
                               last_message.created_at AS last_message_at
                          FROM dianlian_business.conversation c
                          JOIN dianlian_business.conversation_participant p
                            ON p.tenant_id = c.tenant_id
                           AND p.conversation_id = c.conversation_id
                           AND p.user_id = :actorId
                           AND p.status = 'ACTIVE'
                          LEFT JOIN LATERAL (
                              SELECT body_text, created_at
                                FROM dianlian_business.conversation_message m
                               WHERE m.tenant_id = c.tenant_id
                                 AND m.conversation_id = c.conversation_id
                                 AND m.sequence_no > p.joined_sequence_no
                                 AND m.status = 'VISIBLE'
                               ORDER BY m.sequence_no DESC
                               LIMIT 1
                          ) last_message ON TRUE
                         WHERE c.tenant_id = :tenantId AND c.conversation_id = :conversationId
                        """)
                .param("tenantId", tenantId)
                .param("actorId", actorId)
                .param("conversationId", conversationId)
                .query((resultSet, rowNumber) -> new ConversationSummary(
                        resultSet.getObject("conversation_id", UUID.class),
                        ConversationType.valueOf(resultSet.getString("conversation_type")),
                        resultSet.getString("title"),
                        ConversationStatus.valueOf(resultSet.getString("status")),
                        resultSet.getLong("membership_version"),
                        humanMembers(tenantId, conversationId),
                        agents(tenantId, conversationId),
                        resultSet.getString("last_message_preview"),
                        nullableInstant(resultSet, "last_message_at"),
                        0,
                        List.of("VIEW", "SEND")
                ))
                .optional()
                .orElseThrow(ConversationNotDiscoverableException::new);
    }

    private List<ConversationMemberView> humanMembers(UUID tenantId, UUID conversationId) {
        return jdbcClient.sql("""
                        SELECT p.user_id, u.display_name, u.avatar_url, p.participant_role
                          FROM dianlian_business.conversation_participant p
                          JOIN dianlian_business.user_account u ON u.user_id = p.user_id
                         WHERE p.tenant_id = :tenantId
                           AND p.conversation_id = :conversationId
                           AND p.status = 'ACTIVE'
                         ORDER BY CASE p.participant_role WHEN 'OWNER' THEN 0 ELSE 1 END, u.display_name
                        """)
                .param("tenantId", tenantId)
                .param("conversationId", conversationId)
                .query((rs, row) -> new ConversationMemberView(
                        rs.getObject("user_id", UUID.class), rs.getString("display_name"),
                        rs.getString("avatar_url"), rs.getString("participant_role")
                ))
                .list();
    }

    private List<ConversationAgentView> agents(UUID tenantId, UUID conversationId) {
        return jdbcClient.sql("""
                        SELECT binding.enterprise_agent_id,
                               configuration.display_name_snapshot,
                               version.template_name
                          FROM dianlian_business.conversation_agent_binding binding
                          JOIN dianlian_business.enterprise_agent agent
                            ON agent.tenant_id = binding.tenant_id
                           AND agent.enterprise_agent_id = binding.enterprise_agent_id
                           AND agent.status = 'ACTIVE'
                          JOIN dianlian_business.agent_version version
                            ON version.agent_version_id = agent.agent_version_id
                           AND version.status = 'PUBLISHED'
                          JOIN dianlian_business.enterprise_agent_configuration_version configuration
                            ON configuration.tenant_id = agent.tenant_id
                           AND configuration.configuration_version_id = agent.active_configuration_version_id
                           AND configuration.status = 'ACTIVE'
                         WHERE binding.tenant_id = :tenantId
                           AND binding.conversation_id = :conversationId
                           AND binding.status = 'ACTIVE'
                         ORDER BY configuration.display_name_snapshot
                        """)
                .param("tenantId", tenantId)
                .param("conversationId", conversationId)
                .query((rs, row) -> new ConversationAgentView(
                        rs.getObject("enterprise_agent_id", UUID.class),
                        rs.getString("display_name_snapshot"),
                        rs.getString("template_name"),
                        null
                ))
                .list();
    }

    private List<UUID> activeHumanIds(UUID tenantId, UUID conversationId) {
        return jdbcClient.sql("""
                        SELECT user_id
                          FROM dianlian_business.conversation_participant
                         WHERE tenant_id = :tenantId AND conversation_id = :conversationId AND status = 'ACTIVE'
                         ORDER BY user_id
                        """)
                .param("tenantId", tenantId)
                .param("conversationId", conversationId)
                .query(UUID.class)
                .list();
    }

    private List<UUID> activeAgentIds(UUID tenantId, UUID conversationId) {
        return jdbcClient.sql("""
                        SELECT enterprise_agent_id
                          FROM dianlian_business.conversation_agent_binding
                         WHERE tenant_id = :tenantId AND conversation_id = :conversationId AND status = 'ACTIVE'
                         ORDER BY enterprise_agent_id
                        """)
                .param("tenantId", tenantId)
                .param("conversationId", conversationId)
                .query(UUID.class)
                .list();
    }

    private Optional<VisibleState> readVisibleState(UUID tenantId, UUID actorId, UUID conversationId) {
        return jdbcClient.sql("""
                        SELECT c.membership_version, c.next_sequence_no - 1 AS up_to_sequence_no,
                               p.joined_sequence_no
                          FROM dianlian_business.conversation c
                          JOIN dianlian_business.conversation_participant p
                            ON p.tenant_id = c.tenant_id
                           AND p.conversation_id = c.conversation_id
                           AND p.user_id = :actorId
                           AND p.status = 'ACTIVE'
                         WHERE c.tenant_id = :tenantId
                           AND c.conversation_id = :conversationId
                           AND c.status = 'ACTIVE'
                        """)
                .param("tenantId", tenantId)
                .param("actorId", actorId)
                .param("conversationId", conversationId)
                .query((rs, row) -> new VisibleState(
                        rs.getLong("membership_version"),
                        rs.getLong("up_to_sequence_no"),
                        rs.getLong("joined_sequence_no")
                ))
                .optional();
    }

    private ConversationMessageView mapMessage(ResultSet resultSet, int rowNumber) throws SQLException {
        String knowledgeState = nullableString(resultSet, "knowledge_state");
        String memoryState = nullableString(resultSet, "memory_state");
        return new ConversationMessageView(
                resultSet.getObject("message_id", UUID.class),
                resultSet.getObject("conversation_id", UUID.class),
                resultSet.getLong("sequence_no"),
                MessageSenderType.valueOf(resultSet.getString("sender_type")),
                resultSet.getObject("sender_user_id", UUID.class),
                resultSet.getObject("sender_agent_id", UUID.class),
                resultSet.getString("sender_display_name"),
                resultSet.getString("sender_avatar_url"),
                resultSet.getString("body_text"),
                resultSet.getObject("reply_to_message_id", UUID.class),
                readUuidList(resultSet.getString("target_agent_ids")),
                nullableString(resultSet, "ai_status"),
                knowledgeState == null ? null : ContextSourceState.valueOf(knowledgeState),
                memoryState == null ? null : ContextSourceState.valueOf(memoryState),
                resultSet.getLong("charged_micro_credit"),
                resultSet.getTimestamp("created_at").toInstant()
        );
    }

    private String userDisplayName(UUID userId) {
        return jdbcClient.sql("SELECT display_name FROM dianlian_business.user_account WHERE user_id = :userId")
                .param("userId", userId).query(String.class).single();
    }

    private String userAvatar(UUID userId) {
        return jdbcClient.sql("SELECT avatar_url FROM dianlian_business.user_account WHERE user_id = :userId")
                .param("userId", userId).query(String.class).optional().orElse(null);
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("failed to serialize conversation snapshot", exception);
        }
    }

    private List<UUID> readUuidList(String value) {
        if (value == null) return List.of();
        try {
            return objectMapper.readValue(value, UUID_LIST);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("failed to deserialize conversation target ids", exception);
        }
    }

    private static String nullableString(ResultSet resultSet, String column) throws SQLException {
        try {
            return resultSet.getString(column);
        } catch (SQLException ignored) {
            return null;
        }
    }

    private static java.time.Instant nullableInstant(ResultSet resultSet, String column) throws SQLException {
        var value = resultSet.getTimestamp(column);
        return value == null ? null : value.toInstant();
    }

    private record VisibleState(long membershipVersion, long upToSequenceNo, long joinedSequenceNo) {
    }
}

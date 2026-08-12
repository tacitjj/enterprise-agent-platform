package com.dianlian.platform.interaction.infrastructure;

import com.dianlian.platform.memory.api.GroupMembershipVerifier;
import java.util.Objects;
import java.util.UUID;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcOperations;
import org.springframework.stereotype.Component;

@Component
public final class JdbcGroupMembershipVerifier implements GroupMembershipVerifier {

    static final String ACTIVE_GROUP_MEMBERSHIP_SQL = """
            SELECT EXISTS (
                SELECT 1
                  FROM dianlian_business.conversation c
                  JOIN dianlian_business.conversation_participant p
                    ON p.tenant_id = c.tenant_id
                   AND p.conversation_id = c.conversation_id
                  JOIN dianlian_business.tenant_member tm
                    ON tm.tenant_id = p.tenant_id
                   AND tm.user_id = p.user_id
                  JOIN dianlian_business.user_account u
                    ON u.user_id = tm.user_id
                  JOIN dianlian_business.tenant t
                    ON t.tenant_id = c.tenant_id
                 WHERE c.tenant_id = ?
                   AND c.conversation_id = ?
                   AND c.conversation_type = 'GROUP'
                   AND c.status = 'ACTIVE'
                   AND p.user_id = ?
                   AND p.status = 'ACTIVE'
                   AND p.ended_at IS NULL
                   AND p.joined_at <= CURRENT_TIMESTAMP
                   AND tm.status = 'ACTIVE'
                   AND tm.ended_at IS NULL
                   AND tm.joined_at <= CURRENT_TIMESTAMP
                   AND (tm.expires_at IS NULL OR tm.expires_at > CURRENT_TIMESTAMP)
                   AND u.status = 'ACTIVE'
                   AND t.status = 'ACTIVE'
            )
            """;

    private final JdbcOperations jdbcOperations;

    public JdbcGroupMembershipVerifier(JdbcOperations jdbcOperations) {
        this.jdbcOperations = Objects.requireNonNull(jdbcOperations, "jdbcOperations must not be null");
    }

    @Override
    public boolean isActiveMember(UUID tenantId, UUID groupConversationId, UUID userId) {
        Objects.requireNonNull(tenantId, "tenantId must not be null");
        Objects.requireNonNull(groupConversationId, "groupConversationId must not be null");
        Objects.requireNonNull(userId, "userId must not be null");
        try {
            Boolean active = jdbcOperations.queryForObject(
                    ACTIVE_GROUP_MEMBERSHIP_SQL,
                    Boolean.class,
                    tenantId,
                    groupConversationId,
                    userId
            );
            return Boolean.TRUE.equals(active);
        } catch (DataAccessException exception) {
            return false;
        }
    }
}

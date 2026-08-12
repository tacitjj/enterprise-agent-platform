package com.dianlian.platform.interaction.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;

class JdbcGroupMembershipVerifierTests {

    private static final UUID TENANT_ID = UUID.fromString("10000000-0000-0000-0000-000000000001");
    private static final UUID GROUP_ID = UUID.fromString("20000000-0000-0000-0000-000000000001");
    private static final UUID USER_ID = UUID.fromString("30000000-0000-0000-0000-000000000001");

    @Test
    void allowsOnlyTheTenantScopedActiveUnexpiredGroupMembershipShape() {
        var jdbcOperations = new RecordingJdbcTemplate(true);
        var verifier = new JdbcGroupMembershipVerifier(jdbcOperations);

        assertThat(verifier.isActiveMember(TENANT_ID, GROUP_ID, USER_ID)).isTrue();
        assertThat(jdbcOperations.sql).isEqualTo(JdbcGroupMembershipVerifier.ACTIVE_GROUP_MEMBERSHIP_SQL);
        assertThat(jdbcOperations.arguments).containsExactly(TENANT_ID, GROUP_ID, USER_ID);
        assertThat(jdbcOperations.sql)
                .contains("c.tenant_id = ?")
                .contains("c.conversation_type = 'GROUP'")
                .contains("p.status = 'ACTIVE'")
                .contains("p.ended_at IS NULL")
                .contains("tm.status = 'ACTIVE'")
                .contains("tm.ended_at IS NULL")
                .contains("tm.expires_at IS NULL OR tm.expires_at > CURRENT_TIMESTAMP")
                .contains("u.status = 'ACTIVE'")
                .contains("t.status = 'ACTIVE'");
    }

    @Test
    void failsClosedForMissingMembershipAndDatabaseFailure() {
        var missing = new JdbcGroupMembershipVerifier(new RecordingJdbcTemplate(false));
        assertThat(missing.isActiveMember(TENANT_ID, GROUP_ID, USER_ID)).isFalse();

        var failed = new JdbcGroupMembershipVerifier(new RecordingJdbcTemplate(
                new DataAccessResourceFailureException("database unavailable")
        ));
        assertThat(failed.isActiveMember(TENANT_ID, GROUP_ID, USER_ID)).isFalse();
    }

    private static final class RecordingJdbcTemplate extends JdbcTemplate {

        private final Boolean result;
        private final DataAccessException failure;
        private String sql;
        private Object[] arguments;

        private RecordingJdbcTemplate(Boolean result) {
            this.result = result;
            this.failure = null;
        }

        private RecordingJdbcTemplate(DataAccessException failure) {
            this.result = null;
            this.failure = failure;
        }

        @Override
        public <T> T queryForObject(String sql, Class<T> requiredType, Object... args) {
            this.sql = sql;
            this.arguments = args.clone();
            if (failure != null) {
                throw failure;
            }
            return requiredType.cast(result);
        }
    }
}

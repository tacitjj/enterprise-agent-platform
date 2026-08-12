package com.dianlian.platform.identity.infrastructure;

import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.TenantId;
import com.dianlian.platform.identity.application.PasswordCredentialStore;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcPasswordCredentialStore implements PasswordCredentialStore {

    private static final int MAX_FAILED_ATTEMPTS = 5;
    private static final String DUMMY_BCRYPT_HASH =
            "$2a$10$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy";

    static final String CREDENTIAL_SQL = """
            SELECT ua.user_id,
                   ua.status AS account_status,
                   pc.password_hash,
                   pc.failed_attempt_count,
                   pc.locked_until
              FROM dianlian_business.user_login_identifier li
              JOIN dianlian_business.user_account ua
                ON ua.user_id = li.user_id
              JOIN dianlian_business.password_credential pc
                ON pc.user_id = ua.user_id
             WHERE li.identifier_type = 'USERNAME'
               AND li.normalized_identifier = :normalized_identifier
               AND li.status = 'ACTIVE'
             FOR UPDATE OF pc
            """;

    static final String ACTIVE_MEMBERSHIP_SQL = """
            SELECT tm.member_id, tm.tenant_id
              FROM dianlian_business.tenant_member tm
              JOIN dianlian_business.tenant t
                ON t.tenant_id = tm.tenant_id
             WHERE tm.user_id = :user_id
               AND tm.status = 'ACTIVE'
               AND t.status = 'ACTIVE'
               AND (tm.expires_at IS NULL OR tm.expires_at > :observed_at)
             ORDER BY tm.joined_at, tm.tenant_id
             LIMIT 1
            """;

    private final JdbcClient jdbcClient;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder(12);

    public JdbcPasswordCredentialStore(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    @Override
    public Optional<LoginIdentity> authenticate(String normalizedUsername, String rawPassword, Instant observedAt) {
        var observedAtUtc = observedAt.atOffset(ZoneOffset.UTC);
        var credential = jdbcClient.sql(CREDENTIAL_SQL)
                .param("normalized_identifier", normalizedUsername)
                .query((resultSet, rowNumber) -> new CredentialRow(
                        resultSet.getObject("user_id", UUID.class),
                        resultSet.getString("account_status"),
                        resultSet.getString("password_hash"),
                        resultSet.getInt("failed_attempt_count"),
                        resultSet.getObject("locked_until", OffsetDateTime.class)
                ))
                .optional();

        if (credential.isEmpty()) {
            passwordEncoder.matches(rawPassword, DUMMY_BCRYPT_HASH);
            return Optional.empty();
        }

        var row = credential.orElseThrow();
        var passwordMatches = passwordEncoder.matches(rawPassword, row.passwordHash());
        if (!"ACTIVE".equals(row.accountStatus())
                || (row.lockedUntil() != null && row.lockedUntil().toInstant().isAfter(observedAt))
                || !passwordMatches) {
            recordFailedAttempt(row.userId(), row.failedAttemptCount(), observedAtUtc);
            return Optional.empty();
        }

        jdbcClient.sql("""
                UPDATE dianlian_business.password_credential
                   SET failed_attempt_count = 0,
                       locked_until = NULL,
                       last_authenticated_at = :observed_at,
                       updated_at = :observed_at
                 WHERE user_id = :user_id
                """)
                .param("user_id", row.userId())
                .param("observed_at", observedAtUtc)
                .update();

        var membership = jdbcClient.sql(ACTIVE_MEMBERSHIP_SQL)
                .param("user_id", row.userId())
                .param("observed_at", observedAtUtc)
                .query((resultSet, rowNumber) -> new MembershipRow(
                        resultSet.getObject("member_id", UUID.class),
                        resultSet.getObject("tenant_id", UUID.class)
                ))
                .optional();
        return Optional.of(new LoginIdentity(
                new ActorId(row.userId()),
                membership.map(value -> new TenantId(value.tenantId())).orElse(null),
                membership.map(MembershipRow::memberId).orElse(null)
        ));
    }

    private void recordFailedAttempt(UUID userId, int previousFailures, OffsetDateTime observedAt) {
        var failures = previousFailures + 1;
        var lockedUntil = failures >= MAX_FAILED_ATTEMPTS ? observedAt.plusMinutes(15) : null;
        jdbcClient.sql("""
                UPDATE dianlian_business.password_credential
                   SET failed_attempt_count = :failed_attempt_count,
                       locked_until = :locked_until,
                       updated_at = :observed_at
                 WHERE user_id = :user_id
                """)
                .param("user_id", userId)
                .param("failed_attempt_count", failures)
                .param("locked_until", lockedUntil, java.sql.Types.TIMESTAMP_WITH_TIMEZONE)
                .param("observed_at", observedAt)
                .update();
    }

    private record CredentialRow(
            UUID userId,
            String accountStatus,
            String passwordHash,
            int failedAttemptCount,
            OffsetDateTime lockedUntil
    ) {
    }

    private record MembershipRow(UUID memberId, UUID tenantId) {
    }
}

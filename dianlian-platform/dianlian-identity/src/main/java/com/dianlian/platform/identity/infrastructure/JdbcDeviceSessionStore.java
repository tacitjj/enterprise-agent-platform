package com.dianlian.platform.identity.infrastructure;

import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.ClientType;
import com.dianlian.platform.identity.application.DeviceSessionStore;
import java.sql.Types;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcDeviceSessionStore implements DeviceSessionStore {

    static final String REFRESH_SQL = """
            SELECT rt.refresh_token_id,
                   rt.session_id,
                   ws.user_id,
                   ws.client_type,
                   ws.expires_at AS session_expires_at,
                   rt.expires_at AS token_expires_at,
                   rt.consumed_at,
                   COALESCE(rt.revoked_at, ws.revoked_at) AS effective_revoked_at
              FROM dianlian_business.refresh_token rt
              JOIN dianlian_business.web_session ws
                ON ws.session_id = rt.session_id
              JOIN dianlian_business.user_account ua
                ON ua.user_id = ws.user_id
             WHERE rt.token_digest = :token_digest
               AND ua.status = 'ACTIVE'
             FOR UPDATE OF rt, ws
            """;

    private final JdbcClient jdbcClient;

    public JdbcDeviceSessionStore(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    @Override
    public void create(CreateSession session) {
        jdbcClient.sql("""
                INSERT INTO dianlian_business.web_session (
                    session_id, user_id, active_tenant_id, active_member_id,
                    issued_at, expires_at, last_seen_at, client_type, device_id, device_name
                ) VALUES (
                    :session_id, :user_id, :active_tenant_id, :active_member_id,
                    :issued_at, :expires_at, :issued_at, :client_type, :device_id, :device_name
                )
                """)
                .param("session_id", session.sessionId())
                .param("user_id", session.actorId().value())
                .param("active_tenant_id", value(session.activeTenantId()), Types.OTHER)
                .param("active_member_id", session.activeMemberId(), Types.OTHER)
                .param("issued_at", utc(session.issuedAt()))
                .param("expires_at", utc(session.sessionExpiresAt()))
                .param("client_type", session.clientType().name())
                .param("device_id", session.deviceId(), Types.VARCHAR)
                .param("device_name", session.deviceName(), Types.VARCHAR)
                .update();
        jdbcClient.sql("""
                INSERT INTO dianlian_business.refresh_token (
                    refresh_token_id, session_id, token_digest, issued_at, expires_at
                ) VALUES (
                    :token_id, :session_id, :token_digest, :issued_at, :expires_at
                )
                """)
                .param("token_id", session.refreshTokenId())
                .param("session_id", session.sessionId())
                .param("token_digest", session.refreshTokenDigest())
                .param("issued_at", utc(session.issuedAt()))
                .param("expires_at", utc(session.refreshExpiresAt()))
                .update();
    }

    @Override
    public Optional<RefreshSession> lockRefreshToken(String tokenDigest, Instant observedAt) {
        return jdbcClient.sql(REFRESH_SQL)
                .param("token_digest", tokenDigest)
                .query((resultSet, rowNumber) -> new RefreshSession(
                        resultSet.getObject("refresh_token_id", UUID.class),
                        resultSet.getObject("session_id", UUID.class),
                        new ActorId(resultSet.getObject("user_id", UUID.class)),
                        ClientType.valueOf(resultSet.getString("client_type")),
                        resultSet.getObject("session_expires_at", OffsetDateTime.class).toInstant(),
                        resultSet.getObject("token_expires_at", OffsetDateTime.class).toInstant(),
                        resultSet.getObject("consumed_at") != null,
                        resultSet.getObject("effective_revoked_at") != null
                ))
                .optional();
    }

    @Override
    public boolean rotateRefreshToken(UUID tokenId, RotateRefreshToken replacement, Instant observedAt) {
        var updated = jdbcClient.sql("""
                UPDATE dianlian_business.refresh_token
                   SET consumed_at = :observed_at,
                       replaced_by_token_id = :replacement_id
                 WHERE refresh_token_id = :token_id
                   AND consumed_at IS NULL
                   AND revoked_at IS NULL
                   AND expires_at > :observed_at
                """)
                .param("token_id", tokenId)
                .param("replacement_id", replacement.tokenId())
                .param("observed_at", utc(observedAt))
                .update();
        if (updated != 1) {
            return false;
        }
        jdbcClient.sql("""
                INSERT INTO dianlian_business.refresh_token (
                    refresh_token_id, session_id, token_digest, issued_at, expires_at
                ) VALUES (
                    :replacement_id, :session_id, :token_digest, :issued_at, :expires_at
                )
                """)
                .param("replacement_id", replacement.tokenId())
                .param("session_id", replacement.sessionId())
                .param("token_digest", replacement.tokenDigest())
                .param("issued_at", utc(replacement.issuedAt()))
                .param("expires_at", utc(replacement.expiresAt()))
                .update();
        jdbcClient.sql("""
                UPDATE dianlian_business.web_session
                   SET last_seen_at = :observed_at
                 WHERE session_id = :session_id
                   AND revoked_at IS NULL
                """)
                .param("session_id", replacement.sessionId())
                .param("observed_at", utc(observedAt))
                .update();
        return true;
    }

    @Override
    public void revoke(UUID sessionId, Instant observedAt) {
        var observedAtUtc = utc(observedAt);
        jdbcClient.sql("""
                UPDATE dianlian_business.web_session
                   SET revoked_at = COALESCE(revoked_at, :observed_at)
                 WHERE session_id = :session_id
                """)
                .param("session_id", sessionId)
                .param("observed_at", observedAtUtc)
                .update();
        jdbcClient.sql("""
                UPDATE dianlian_business.refresh_token
                   SET revoked_at = COALESCE(revoked_at, :observed_at)
                 WHERE session_id = :session_id
                   AND consumed_at IS NULL
                """)
                .param("session_id", sessionId)
                .param("observed_at", observedAtUtc)
                .update();
    }

    private static UUID value(com.dianlian.platform.identity.api.TenantId tenantId) {
        return tenantId == null ? null : tenantId.value();
    }

    private static OffsetDateTime utc(Instant instant) {
        return instant.atOffset(ZoneOffset.UTC);
    }
}

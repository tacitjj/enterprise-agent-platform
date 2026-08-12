package com.dianlian.platform.identity.infrastructure;

import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.TenantId;
import com.dianlian.platform.identity.application.SessionLookup;
import com.dianlian.platform.identity.domain.PermissionVersion;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

@Repository
public class JdbcSessionLookup implements SessionLookup {

    static final String SESSION_SQL = """
            SELECT ws.session_id,
                   ws.user_id,
                   ws.active_tenant_id,
                   ws.issued_at,
                   ws.expires_at,
                   ua.display_name AS user_display_name,
                   ua.avatar_url,
                   ua.status AS account_status,
                   ua.permission_version AS user_permission_version,
                   t.display_name AS tenant_display_name,
                   t.status AS tenant_status,
                   t.permission_version AS tenant_permission_version,
                   tm.status AS membership_status,
                   tm.permission_version AS membership_permission_version
              FROM dianlian_business.web_session ws
              JOIN dianlian_business.user_account ua
                ON ua.user_id = ws.user_id
              LEFT JOIN dianlian_business.tenant t
                ON t.tenant_id = ws.active_tenant_id
              LEFT JOIN dianlian_business.tenant_member tm
                ON tm.member_id = ws.active_member_id
               AND tm.tenant_id = ws.active_tenant_id
               AND tm.user_id = ws.user_id
             WHERE ws.session_id = :session_id
               AND ws.revoked_at IS NULL
               AND ws.expires_at > :observed_at
               AND ua.status = 'ACTIVE'
               AND (
                    ws.active_tenant_id IS NULL
                    OR (
                        t.status = 'ACTIVE'
                        AND tm.status = 'ACTIVE'
                        AND (tm.expires_at IS NULL OR tm.expires_at > :observed_at)
                    )
               )
            """;

    static final String ROLE_GRANTS_SQL = """
            SELECT DISTINCT r.role_code, rg.scope_type, rg.scope_id
              FROM dianlian_business.role_grant rg
              JOIN dianlian_business.iam_role r
                ON r.role_code = rg.role_code
               AND r.status = 'ACTIVE'
             WHERE rg.subject_user_id = :user_id
               AND (
                    (:platform_session = TRUE AND rg.tenant_id IS NULL)
                    OR
                    (:platform_session = FALSE AND rg.tenant_id = :tenant_id)
               )
               AND rg.revoked_at IS NULL
               AND (rg.expires_at IS NULL OR rg.expires_at > :observed_at)
             ORDER BY r.role_code, rg.scope_type, rg.scope_id
            """;

    static final String PERMISSIONS_SQL = """
            SELECT DISTINCT p.permission_code
              FROM dianlian_business.role_grant rg
              JOIN dianlian_business.iam_role r
                ON r.role_code = rg.role_code
               AND r.status = 'ACTIVE'
              JOIN dianlian_business.role_permission rp
                ON rp.role_code = r.role_code
              JOIN dianlian_business.iam_permission p
                ON p.permission_code = rp.permission_code
               AND p.status = 'ACTIVE'
             WHERE rg.subject_user_id = :user_id
               AND (
                    (:platform_session = TRUE
                        AND rg.tenant_id IS NULL
                        AND rg.scope_type = 'PLATFORM')
                    OR
                    (:platform_session = FALSE
                        AND rg.tenant_id = :tenant_id
                        AND rg.scope_type = 'TENANT'
                        AND rg.scope_id = :tenant_id)
               )
               AND rg.revoked_at IS NULL
               AND (rg.expires_at IS NULL OR rg.expires_at > :observed_at)
             ORDER BY p.permission_code
            """;

    private final JdbcClient jdbcClient;

    public JdbcSessionLookup(JdbcClient jdbcClient) {
        this.jdbcClient = jdbcClient;
    }

    @Override
    @Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
    public Optional<AuthenticatedPrincipal> findActiveBySessionId(UUID sessionId, Instant observedAt) {
        var observedAtUtc = observedAt.atOffset(ZoneOffset.UTC);
        var session = jdbcClient.sql(SESSION_SQL)
                .param("session_id", sessionId)
                .param("observed_at", observedAtUtc)
                .query(JdbcSessionLookup::mapSession)
                .optional();
        if (session.isEmpty()) {
            return Optional.empty();
        }

        var row = session.orElseThrow();
        var platformSession = row.activeTenantId() == null;
        var roleGrants = roleGrants(row.userId(), row.activeTenantId(), platformSession, observedAtUtc);
        var permissions = permissions(row.userId(), row.activeTenantId(), platformSession, observedAtUtc);
        return Optional.of(row.toPrincipal(roleGrants, permissions));
    }

    private List<SessionView.RoleGrant> roleGrants(
            UUID userId,
            UUID tenantId,
            boolean platformSession,
            OffsetDateTime observedAt
    ) {
        return jdbcClient.sql(ROLE_GRANTS_SQL)
                .param("user_id", userId)
                .param("tenant_id", tenantId, Types.OTHER)
                .param("platform_session", platformSession)
                .param("observed_at", observedAt)
                .query((resultSet, rowNumber) -> new SessionView.RoleGrant(
                        resultSet.getString("role_code"),
                        SessionView.DataScopeType.valueOf(resultSet.getString("scope_type")),
                        resultSet.getObject("scope_id", UUID.class)
                ))
                .list();
    }

    private Set<String> permissions(
            UUID userId,
            UUID tenantId,
            boolean platformSession,
            OffsetDateTime observedAt
    ) {
        var permissionCodes = jdbcClient.sql(PERMISSIONS_SQL)
                .param("user_id", userId)
                .param("tenant_id", tenantId, Types.OTHER)
                .param("platform_session", platformSession)
                .param("observed_at", observedAt)
                .query(String.class)
                .list();
        return Set.copyOf(permissionCodes);
    }

    private static SessionRow mapSession(ResultSet resultSet, int rowNumber) throws SQLException {
        return new SessionRow(
                resultSet.getObject("session_id", UUID.class),
                resultSet.getObject("user_id", UUID.class),
                resultSet.getObject("active_tenant_id", UUID.class),
                resultSet.getString("user_display_name"),
                resultSet.getString("avatar_url"),
                SessionView.AccountStatus.valueOf(resultSet.getString("account_status")),
                resultSet.getString("tenant_display_name"),
                enumOrNull(SessionView.TenantStatus.class, resultSet.getString("tenant_status")),
                enumOrNull(SessionView.MembershipStatus.class, resultSet.getString("membership_status")),
                resultSet.getLong("user_permission_version"),
                nullableLong(resultSet, "tenant_permission_version"),
                nullableLong(resultSet, "membership_permission_version"),
                resultSet.getObject("issued_at", OffsetDateTime.class).toInstant(),
                resultSet.getObject("expires_at", OffsetDateTime.class).toInstant()
        );
    }

    private static Long nullableLong(ResultSet resultSet, String column) throws SQLException {
        var value = resultSet.getLong(column);
        return resultSet.wasNull() ? null : value;
    }

    private static <E extends Enum<E>> E enumOrNull(Class<E> enumType, String value) {
        return value == null ? null : Enum.valueOf(enumType, value);
    }

    private record SessionRow(
            UUID sessionId,
            UUID userId,
            UUID activeTenantId,
            String userDisplayName,
            String avatarUrl,
            SessionView.AccountStatus accountStatus,
            String tenantDisplayName,
            SessionView.TenantStatus tenantStatus,
            SessionView.MembershipStatus membershipStatus,
            long userPermissionVersion,
            Long tenantPermissionVersion,
            Long membershipPermissionVersion,
            Instant issuedAt,
            Instant expiresAt
    ) {

        private AuthenticatedPrincipal toPrincipal(
                List<SessionView.RoleGrant> roleGrants,
                Set<String> permissions
        ) {
            var tenant = activeTenantId == null
                    ? null
                    : new SessionView.Tenant(
                            new TenantId(activeTenantId),
                            tenantDisplayName,
                            tenantStatus,
                            membershipStatus
                    );
            var permissionVersion = PermissionVersion.fingerprint(
                    userPermissionVersion,
                    tenantPermissionVersion,
                    membershipPermissionVersion,
                    roleGrants,
                    permissions
            );
            return new AuthenticatedPrincipal(
                    sessionId,
                    new ActorId(userId),
                    userDisplayName,
                    avatarUrl,
                    accountStatus,
                    tenant,
                    roleGrants,
                    permissions,
                    permissionVersion,
                    issuedAt,
                    expiresAt
            );
        }
    }
}

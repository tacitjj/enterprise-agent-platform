package com.dianlian.platform.identity.infrastructure;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class JdbcSessionLookupSqlShapeTests {

    @Test
    void sessionLookupUsesJwtSessionIdAndServerSideMembershipState() {
        var sql = normalize(JdbcSessionLookup.SESSION_SQL);

        assertTrue(sql.contains("ws.session_id = :session_id"));
        assertTrue(sql.contains("tm.member_id = ws.active_member_id"));
        assertTrue(sql.contains("tm.tenant_id = ws.active_tenant_id"));
        assertTrue(sql.contains("tm.user_id = ws.user_id"));
        assertTrue(sql.contains("ua.status = 'active'"));
        assertTrue(sql.contains("t.status = 'active'"));
        assertTrue(sql.contains("tm.status = 'active'"));
        assertFalse(sql.contains("raw_session_token"));
    }

    @Test
    void roleAndPermissionQueriesResolveGrantsFromServerTables() {
        var rolesSql = normalize(JdbcSessionLookup.ROLE_GRANTS_SQL);
        var permissionsSql = normalize(JdbcSessionLookup.PERMISSIONS_SQL);

        assertTrue(rolesSql.contains("rg.subject_user_id = :user_id"));
        assertTrue(rolesSql.contains("rg.tenant_id = :tenant_id"));
        assertTrue(rolesSql.contains("rg.revoked_at is null"));
        assertTrue(permissionsSql.contains("join dianlian_business.role_permission"));
        assertTrue(permissionsSql.contains("p.permission_code = rp.permission_code"));
        assertTrue(permissionsSql.contains("rg.scope_type = 'platform'"));
        assertTrue(permissionsSql.contains("rg.scope_type = 'tenant'"));
        assertTrue(permissionsSql.contains("rg.scope_id = :tenant_id"));
        assertFalse(permissionsSql.contains(":role_code"));
        assertFalse(permissionsSql.contains(":permission_code"));
    }

    private static String normalize(String sql) {
        return sql.toLowerCase().replaceAll("\\s+", " ").trim();
    }
}

package com.dianlian.platform.bootstrap.infrastructure.security;

import static org.assertj.core.api.Assertions.assertThat;

import cn.dev33.satoken.stp.StpLogic;
import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.SessionAuthenticationPort;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.TenantId;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class SaTokenAuthenticationInterceptorTests {

    private static final UUID SESSION_ID = UUID.fromString("10000000-0000-4000-8000-000000000040");

    @Test
    void authenticatedJwtSessionPopulatesAndClearsActorContext() throws Exception {
        var logic = new TestStpLogic(SESSION_ID, false);
        var context = new DianlianPrincipalContext();
        var interceptor = interceptor(logic, (sessionId, observedAt) -> Optional.of(principal()), context);
        var request = new MockHttpServletRequest("GET", "/api/v1/session");
        var response = new MockHttpServletResponse();

        assertThat(interceptor.preHandle(request, response, new Object())).isTrue();
        assertThat(context.current()).contains(principal());

        interceptor.afterCompletion(request, response, new Object(), null);
        assertThat(context.current()).isEmpty();
    }

    @Test
    void missingOrInvalidJwtIsRejectedBeforeBusinessCode() throws Exception {
        var logic = new TestStpLogic(SESSION_ID, true);
        var context = new DianlianPrincipalContext();
        var interceptor = interceptor(logic, (sessionId, observedAt) -> {
            throw new AssertionError("session lookup must not run for an invalid JWT");
        }, context);
        var response = new MockHttpServletResponse();

        assertThat(interceptor.preHandle(
                new MockHttpServletRequest("GET", "/api/v1/session"),
                response,
                new Object()
        )).isFalse();
        assertThat(response.getStatus()).isEqualTo(401);
        assertThat(response.getContentAsString()).contains("AUTHENTICATION_REQUIRED");
        assertThat(context.current()).isEmpty();
    }

    @Test
    void revokedDatabaseSessionInvalidatesOtherwiseValidJwt() throws Exception {
        var logic = new TestStpLogic(SESSION_ID, false);
        var context = new DianlianPrincipalContext();
        var interceptor = interceptor(logic, (sessionId, observedAt) -> Optional.empty(), context);
        var response = new MockHttpServletResponse();

        assertThat(interceptor.preHandle(
                new MockHttpServletRequest("GET", "/api/v1/session"),
                response,
                new Object()
        )).isFalse();
        assertThat(response.getStatus()).isEqualTo(401);
        assertThat(logic.loggedOutToken).isEqualTo("jwt-token");
    }

    private static SaTokenAuthenticationInterceptor interceptor(
            StpLogic logic,
            SessionAuthenticationPort authenticationPort,
            DianlianPrincipalContext context
    ) {
        return new SaTokenAuthenticationInterceptor(
                logic,
                authenticationPort,
                context,
                new ApiSecurityProblemWriter(new ObjectMapper())
        );
    }

    private static AuthenticatedPrincipal principal() {
        var tenantId = UUID.fromString("10000000-0000-4000-8000-000000000001");
        return new AuthenticatedPrincipal(
                SESSION_ID,
                new ActorId(UUID.fromString("10000000-0000-4000-8000-000000000011")),
                "点联测试用户",
                null,
                SessionView.AccountStatus.ACTIVE,
                new SessionView.Tenant(
                        new TenantId(tenantId),
                        "点联测试企业",
                        SessionView.TenantStatus.ACTIVE,
                        SessionView.MembershipStatus.ACTIVE
                ),
                List.of(new SessionView.RoleGrant("ENTERPRISE_USER", SessionView.DataScopeType.TENANT, tenantId)),
                Set.of("task.create"),
                "permission-v1",
                Instant.parse("2026-08-11T00:00:00Z"),
                Instant.parse("2026-08-11T01:00:00Z")
        );
    }

    private static final class TestStpLogic extends StpLogic {

        private final UUID sessionId;
        private final boolean rejectLogin;
        private String loggedOutToken;

        private TestStpLogic(UUID sessionId, boolean rejectLogin) {
            super("login");
            this.sessionId = sessionId;
            this.rejectLogin = rejectLogin;
        }

        @Override
        public void checkLogin() {
            if (rejectLogin) throw new IllegalStateException("invalid JWT");
        }

        @Override
        public Object getExtra(String key) {
            return SaTokenAuthenticationInterceptor.SESSION_ID_CLAIM.equals(key) ? sessionId.toString() : null;
        }

        @Override
        public String getTokenValue() {
            return "jwt-token";
        }

        @Override
        public String getLoginIdAsString() {
            return "10000000-0000-4000-8000-000000000011";
        }

        @Override
        public void logoutByTokenValue(String tokenValue) {
            loggedOutToken = tokenValue;
        }
    }
}

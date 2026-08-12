package com.dianlian.platform.bootstrap.infrastructure.web;

import static org.assertj.core.api.Assertions.assertThat;

import cn.dev33.satoken.config.SaTokenConfig;
import cn.dev33.satoken.jwt.StpLogicJwtForSimple;
import com.dianlian.platform.bootstrap.infrastructure.config.AuthenticationTokenProperties;
import com.dianlian.platform.bootstrap.infrastructure.security.SaTokenAccessTokenIssuer;
import com.dianlian.platform.identity.api.ActorContextPort;
import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticationApplicationApi;
import com.dianlian.platform.identity.api.ClientType;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockCookie;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class AuthenticationControllerTests {

    private static final UUID SESSION_ID = UUID.fromString("10000000-0000-4000-8000-000000000040");
    private static final ActorId ACTOR_ID = new ActorId(
            UUID.fromString("10000000-0000-4000-8000-000000000011")
    );

    @Test
    void webLoginReturnsAccessTokenAndKeepsRefreshTokenInHttpOnlyCookie() {
        var api = new StubAuthenticationApi(ClientType.WEB);
        var controller = controller(api, true, "__Host-DIANLIAN-REFRESH");
        var response = new MockHttpServletResponse();

        var result = controller.login(
                new AuthenticationController.LoginRequest("alice", "secret", ClientType.WEB, null, "Chrome"),
                response
        );

        assertThat(result.getBody()).isNotNull();
        assertThat(result.getBody().accessToken()).hasSizeGreaterThan(20);
        assertThat(result.getBody().refreshToken()).isNull();
        assertThat(response.getHeader("Set-Cookie"))
                .contains("__Host-DIANLIAN-REFRESH=refresh-test")
                .contains("Path=/api/v1/auth")
                .contains("Secure")
                .contains("HttpOnly")
                .contains("SameSite=Strict");
    }

    @Test
    void nativeLoginReturnsRefreshTokenWithoutCreatingBrowserCookie() {
        var api = new StubAuthenticationApi(ClientType.APP);
        var controller = controller(api, false, "DIANLIAN-REFRESH");
        var response = new MockHttpServletResponse();

        var result = controller.login(
                new AuthenticationController.LoginRequest("alice", "secret", ClientType.APP, "phone-1", "iPhone"),
                response
        );

        assertThat(result.getBody()).isNotNull();
        assertThat(result.getBody().refreshToken()).isEqualTo("refresh-test");
        assertThat(response.getHeader("Set-Cookie")).isNull();
    }

    @Test
    void webRefreshReadsOnlyTheDedicatedRefreshCookie() {
        var api = new StubAuthenticationApi(ClientType.WEB);
        var controller = controller(api, false, "DIANLIAN-REFRESH");
        var request = new MockHttpServletRequest();
        request.setCookies(new MockCookie("DIANLIAN-REFRESH", "refresh-from-cookie"));

        controller.refresh(null, request, new MockHttpServletResponse());

        assertThat(api.refreshToken).isEqualTo("refresh-from-cookie");
    }

    private static AuthenticationController controller(
            AuthenticationApplicationApi authenticationApi,
            boolean secureCookie,
            String cookieName
    ) {
        var logic = new StpLogicJwtForSimple("dianlian-auth-controller-test");
        logic.setConfig(new SaTokenConfig()
                .setTokenName("Authorization")
                .setJwtSecretKey("dianlian-controller-test-signing-key-not-for-production")
                .setTimeout(900)
                .setIsShare(false));
        var properties = new AuthenticationTokenProperties(cookieName, secureCookie, "Strict");
        ActorContextPort emptyActorContext = Optional::empty;
        return new AuthenticationController(
                authenticationApi,
                emptyActorContext,
                new SaTokenAccessTokenIssuer(logic),
                properties
        );
    }

    private static final class StubAuthenticationApi implements AuthenticationApplicationApi {
        private final ClientType clientType;
        private String refreshToken;

        private StubAuthenticationApi(ClientType clientType) {
            this.clientType = clientType;
        }

        @Override
        public LoginSession login(PasswordLoginCommand command) {
            return session();
        }

        @Override
        public LoginSession refresh(RefreshSessionCommand command) {
            refreshToken = command.refreshToken();
            return session();
        }

        @Override
        public void logout(UUID sessionId, Instant observedAt) {
        }

        private LoginSession session() {
            var now = Instant.now();
            return new LoginSession(
                    SESSION_ID,
                    ACTOR_ID,
                    clientType,
                    "refresh-test",
                    now.plusSeconds(900),
                    now.plusSeconds(2_592_000)
            );
        }
    }
}

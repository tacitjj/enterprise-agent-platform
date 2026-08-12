package com.dianlian.platform.bootstrap.infrastructure.security;

import static org.assertj.core.api.Assertions.assertThat;

import cn.dev33.satoken.config.SaTokenConfig;
import cn.dev33.satoken.jwt.StpLogicJwtForSimple;
import cn.dev33.satoken.stp.parameter.SaLoginParameter;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class SaTokenJwtModeTests {

    @Test
    void simpleModeIssuesStatefulJwtWithBoundSessionClaim() {
        var actorId = UUID.fromString("10000000-0000-4000-8000-000000000011");
        var sessionId = UUID.fromString("10000000-0000-4000-8000-000000000040");
        var logic = new StpLogicJwtForSimple("dianlian-jwt-test");
        logic.setConfig(new SaTokenConfig()
                .setTokenName("Authorization")
                .setJwtSecretKey("dianlian-test-signing-key-must-never-be-used-in-production")
                .setTimeout(900)
                .setIsShare(false));

        var token = logic.createLoginSession(
                actorId.toString(),
                SaLoginParameter.create()
                        .setTimeout(900)
                        .setDeviceType("WEB")
                        .setExtra(SaTokenAuthenticationInterceptor.SESSION_ID_CLAIM, sessionId.toString())
        );

        assertThat(token.split("\\.")).hasSize(3);
        assertThat(logic.getLoginIdByToken(token)).isEqualTo(actorId.toString());
        assertThat(logic.getExtra(token, SaTokenAuthenticationInterceptor.SESSION_ID_CLAIM))
                .isEqualTo(sessionId.toString());
        assertThat(logic.isValidToken(token.substring(0, token.length() - 1) + "x")).isFalse();
    }
}

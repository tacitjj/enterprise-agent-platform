package com.dianlian.platform.bootstrap.infrastructure.security;

import cn.dev33.satoken.stp.StpLogic;
import cn.dev33.satoken.stp.parameter.SaLoginParameter;
import com.dianlian.platform.identity.api.AuthenticationApplicationApi.LoginSession;
import java.time.Duration;
import java.util.Objects;
import org.springframework.stereotype.Component;

@Component
public final class SaTokenAccessTokenIssuer {

    private final StpLogic stpLogic;

    public SaTokenAccessTokenIssuer(StpLogic stpLogic) {
        this.stpLogic = Objects.requireNonNull(stpLogic, "stpLogic must not be null");
    }

    public IssuedAccessToken issue(LoginSession session) {
        var expiresIn = Math.min(
                3600,
                Math.max(1, Duration.between(java.time.Instant.now(), session.accessExpiresAt()).toSeconds())
        );
        var token = stpLogic.createLoginSession(
                session.actorId().value().toString(),
                SaLoginParameter.create()
                        .setTimeout(expiresIn)
                        .setDeviceType(session.clientType().name())
                        .setExtra(SaTokenAuthenticationInterceptor.SESSION_ID_CLAIM, session.sessionId().toString())
        );
        return new IssuedAccessToken(token, expiresIn);
    }

    public void revokeCurrentToken() {
        var tokenValue = stpLogic.getTokenValue();
        if (tokenValue != null && !tokenValue.isBlank()) {
            stpLogic.logoutByTokenValue(tokenValue);
        }
    }

    public record IssuedAccessToken(String value, long expiresIn) {
    }
}

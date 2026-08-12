package com.dianlian.platform.bootstrap.infrastructure.security;

import cn.dev33.satoken.stp.StpLogic;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.SessionAuthenticationPort;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

@Component
public final class SaTokenAuthenticationInterceptor implements HandlerInterceptor {

    static final String SESSION_ID_CLAIM = "sid";

    private final StpLogic stpLogic;
    private final SessionAuthenticationPort sessionAuthenticationPort;
    private final DianlianPrincipalContext principalContext;
    private final ApiSecurityProblemWriter problemWriter;

    public SaTokenAuthenticationInterceptor(
            StpLogic stpLogic,
            SessionAuthenticationPort sessionAuthenticationPort,
            DianlianPrincipalContext principalContext,
            ApiSecurityProblemWriter problemWriter
    ) {
        this.stpLogic = Objects.requireNonNull(stpLogic, "stpLogic must not be null");
        this.sessionAuthenticationPort = Objects.requireNonNull(
                sessionAuthenticationPort,
                "sessionAuthenticationPort must not be null"
        );
        this.principalContext = Objects.requireNonNull(principalContext, "principalContext must not be null");
        this.problemWriter = Objects.requireNonNull(problemWriter, "problemWriter must not be null");
    }

    @Override
    public boolean preHandle(
            HttpServletRequest request,
            HttpServletResponse response,
            Object handler
    ) throws Exception {
        try {
            stpLogic.checkLogin();
            var sessionId = UUID.fromString(String.valueOf(stpLogic.getExtra(SESSION_ID_CLAIM)));
            var principal = sessionAuthenticationPort.authenticate(sessionId, Instant.now());
            if (principal.isEmpty() || !sameActor(principal.orElseThrow())) {
                stpLogic.logoutByTokenValue(stpLogic.getTokenValue());
                return reject(request, response);
            }
            principalContext.set(principal.orElseThrow());
            return true;
        } catch (RuntimeException exception) {
            return reject(request, response);
        }
    }

    private boolean sameActor(AuthenticatedPrincipal principal) {
        return principal.actorId().value().toString().equals(stpLogic.getLoginIdAsString());
    }

    @Override
    public void afterCompletion(
            HttpServletRequest request,
            HttpServletResponse response,
            Object handler,
            Exception exception
    ) {
        principalContext.clear();
    }

    private boolean reject(HttpServletRequest request, HttpServletResponse response) throws Exception {
        principalContext.clear();
        problemWriter.write(
                request,
                response,
                401,
                "AUTHENTICATION_REQUIRED",
                "登录状态已失效",
                "请重新登录后继续。",
                false,
                "REAUTHENTICATE"
        );
        return false;
    }
}

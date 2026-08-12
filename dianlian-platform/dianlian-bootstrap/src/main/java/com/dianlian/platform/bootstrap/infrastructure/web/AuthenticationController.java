package com.dianlian.platform.bootstrap.infrastructure.web;

import com.dianlian.platform.bootstrap.infrastructure.config.AuthenticationTokenProperties;
import com.dianlian.platform.bootstrap.infrastructure.security.SaTokenAccessTokenIssuer;
import com.dianlian.platform.identity.api.ActorContextPort;
import com.dianlian.platform.identity.api.AuthenticationApplicationApi;
import com.dianlian.platform.identity.api.ClientType;
import com.dianlian.platform.identity.api.InvalidRefreshTokenException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.time.Duration;
import java.time.Instant;
import java.util.Arrays;
import java.util.Objects;
import java.util.UUID;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth")
public final class AuthenticationController {

    private static final String REFRESH_COOKIE_PATH = "/api/v1/auth";

    private final AuthenticationApplicationApi authenticationApi;
    private final ActorContextPort actorContextPort;
    private final SaTokenAccessTokenIssuer accessTokenIssuer;
    private final AuthenticationTokenProperties properties;

    public AuthenticationController(
            AuthenticationApplicationApi authenticationApi,
            ActorContextPort actorContextPort,
            SaTokenAccessTokenIssuer accessTokenIssuer,
            AuthenticationTokenProperties properties
    ) {
        this.authenticationApi = Objects.requireNonNull(authenticationApi, "authenticationApi must not be null");
        this.actorContextPort = Objects.requireNonNull(actorContextPort, "actorContextPort must not be null");
        this.accessTokenIssuer = Objects.requireNonNull(accessTokenIssuer, "accessTokenIssuer must not be null");
        this.properties = Objects.requireNonNull(properties, "properties must not be null");
    }

    @PostMapping("/login")
    public ResponseEntity<TokenResponse> login(
            @Valid @RequestBody LoginRequest request,
            HttpServletResponse response
    ) {
        var session = authenticationApi.login(new AuthenticationApplicationApi.PasswordLoginCommand(
                request.username(),
                request.password(),
                request.clientType(),
                request.deviceId(),
                request.deviceName(),
                Instant.now()
        ));
        return tokenResponse(session, response);
    }

    @PostMapping("/refresh")
    public ResponseEntity<TokenResponse> refresh(
            @RequestBody(required = false) RefreshRequest request,
            HttpServletRequest servletRequest,
            HttpServletResponse servletResponse
    ) {
        var requestToken = request == null ? null : request.refreshToken();
        var refreshToken = hasText(requestToken) ? requestToken : refreshCookie(servletRequest);
        if (!hasText(refreshToken)) throw new InvalidRefreshTokenException();
        var session = authenticationApi.refresh(new AuthenticationApplicationApi.RefreshSessionCommand(
                refreshToken,
                Instant.now()
        ));
        return tokenResponse(session, servletResponse);
    }

    @PostMapping("/logout")
    public ResponseEntity<Void> logout(HttpServletResponse response) {
        var principal = actorContextPort.requireCurrent();
        authenticationApi.logout(principal.sessionId(), Instant.now());
        accessTokenIssuer.revokeCurrentToken();
        clearRefreshCookie(response);
        return ResponseEntity.noContent().cacheControl(CacheControl.noStore()).build();
    }

    private ResponseEntity<TokenResponse> tokenResponse(
            AuthenticationApplicationApi.LoginSession session,
            HttpServletResponse response
    ) {
        SaTokenAccessTokenIssuer.IssuedAccessToken accessToken;
        try {
            accessToken = accessTokenIssuer.issue(session);
        } catch (RuntimeException issueFailure) {
            authenticationApi.logout(session.sessionId(), Instant.now());
            throw issueFailure;
        }
        var webClient = session.clientType() == ClientType.WEB;
        if (webClient) setRefreshCookie(response, session.refreshToken(), session.refreshExpiresAt());
        var body = new TokenResponse(
                "Bearer",
                accessToken.value(),
                accessToken.expiresIn(),
                webClient ? null : session.refreshToken(),
                Math.max(1, Duration.between(Instant.now(), session.refreshExpiresAt()).toSeconds()),
                session.sessionId(),
                session.clientType()
        );
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(body);
    }

    private String refreshCookie(HttpServletRequest request) {
        return Arrays.stream(Objects.requireNonNullElse(request.getCookies(), new Cookie[0]))
                .filter(cookie -> properties.refreshCookieName().equals(cookie.getName()))
                .map(Cookie::getValue)
                .filter(AuthenticationController::hasText)
                .findFirst()
                .orElse(null);
    }

    private void setRefreshCookie(HttpServletResponse response, String value, Instant expiresAt) {
        var cookie = ResponseCookie.from(properties.refreshCookieName(), value)
                .httpOnly(true)
                .secure(properties.refreshCookieSecure())
                .sameSite(properties.refreshCookieSameSite())
                .path(REFRESH_COOKIE_PATH)
                .maxAge(Duration.between(Instant.now(), expiresAt))
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    private void clearRefreshCookie(HttpServletResponse response) {
        var cookie = ResponseCookie.from(properties.refreshCookieName(), "")
                .httpOnly(true)
                .secure(properties.refreshCookieSecure())
                .sameSite(properties.refreshCookieSameSite())
                .path(REFRESH_COOKIE_PATH)
                .maxAge(Duration.ZERO)
                .build();
        response.addHeader(HttpHeaders.SET_COOKIE, cookie.toString());
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    public record LoginRequest(
            @NotBlank @Size(max = 200) String username,
            @NotBlank @Size(max = 200) String password,
            @NotNull ClientType clientType,
            @Size(max = 128) String deviceId,
            @Size(max = 100) String deviceName
    ) {
    }

    public record RefreshRequest(@Size(max = 1024) String refreshToken) {
    }

    public record TokenResponse(
            String tokenType,
            String accessToken,
            long expiresIn,
            String refreshToken,
            long refreshExpiresIn,
            UUID sessionId,
            ClientType clientType
    ) {
    }
}

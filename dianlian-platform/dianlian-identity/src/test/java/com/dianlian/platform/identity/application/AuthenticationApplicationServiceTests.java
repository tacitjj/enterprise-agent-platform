package com.dianlian.platform.identity.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticationApplicationApi.PasswordLoginCommand;
import com.dianlian.platform.identity.api.AuthenticationApplicationApi.RefreshSessionCommand;
import com.dianlian.platform.identity.api.ClientType;
import com.dianlian.platform.identity.api.InvalidCredentialsException;
import com.dianlian.platform.identity.api.InvalidRefreshTokenException;
import com.dianlian.platform.identity.api.TenantId;
import java.time.Instant;
import java.time.Duration;
import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class AuthenticationApplicationServiceTests {

    private static final Instant NOW = Instant.parse("2026-08-11T00:00:00Z");
    private static final ActorId ACTOR = new ActorId(UUID.fromString("10000000-0000-4000-8000-000000000011"));
    private static final TenantId TENANT = new TenantId(UUID.fromString("10000000-0000-4000-8000-000000000001"));
    private static final UUID MEMBER = UUID.fromString("10000000-0000-4000-8000-000000000021");

    @Test
    void passwordLoginCreatesOneDeviceSessionWithoutPersistingRawRefreshToken() {
        var credentials = new StubCredentials(true);
        var sessions = new InMemorySessions();
        var tokens = new DeterministicTokens("refresh-one");
        var service = service(credentials, sessions, tokens);

        var result = service.login(new PasswordLoginCommand(
                " Alice ", "correct-password", ClientType.WEB, "browser-1", "Mac Chrome", NOW
        ));

        assertThat(credentials.normalizedUsername).isEqualTo("alice");
        assertThat(result.actorId()).isEqualTo(ACTOR);
        assertThat(result.clientType()).isEqualTo(ClientType.WEB);
        assertThat(result.refreshToken()).isEqualTo("refresh-one");
        assertThat(sessions.created.refreshTokenDigest()).isEqualTo(tokens.digest("refresh-one"));
        assertThat(sessions.created.refreshTokenDigest()).doesNotContain(result.refreshToken());
    }

    @Test
    void invalidPasswordCreatesNoSession() {
        var sessions = new InMemorySessions();
        var service = service(new StubCredentials(false), sessions, new DeterministicTokens("unused"));

        assertThatThrownBy(() -> service.login(new PasswordLoginCommand(
                "alice", "wrong-password", ClientType.APP, null, null, NOW
        ))).isInstanceOf(InvalidCredentialsException.class);
        assertThat(sessions.created).isNull();
    }

    @Test
    void refreshTokenIsSingleUseAndRotated() {
        var sessions = new InMemorySessions();
        var tokens = new DeterministicTokens("refresh-one", "refresh-two");
        var service = service(new StubCredentials(true), sessions, tokens);
        var login = service.login(new PasswordLoginCommand(
                "alice", "correct-password", ClientType.DESKTOP, null, "Mac Desktop", NOW
        ));

        var refreshed = service.refresh(new RefreshSessionCommand("refresh-one", NOW.plusSeconds(30)));

        assertThat(refreshed.sessionId()).isEqualTo(login.sessionId());
        assertThat(refreshed.refreshToken()).isEqualTo("refresh-two");
        assertThat(sessions.tokens.get(tokens.digest("refresh-one")).consumed()).isTrue();
        assertThat(sessions.tokens.get(tokens.digest("refresh-two")).consumed()).isFalse();
    }

    @Test
    void replayingConsumedRefreshTokenRevokesTheWholeDeviceSession() {
        var sessions = new InMemorySessions();
        var service = service(
                new StubCredentials(true), sessions, new DeterministicTokens("refresh-one", "refresh-two")
        );
        var login = service.login(new PasswordLoginCommand(
                "alice", "correct-password", ClientType.APP, null, null, NOW
        ));
        service.refresh(new RefreshSessionCommand("refresh-one", NOW.plusSeconds(10)));

        assertThatThrownBy(() -> service.refresh(new RefreshSessionCommand("refresh-one", NOW.plusSeconds(20))))
                .isInstanceOf(InvalidRefreshTokenException.class);
        assertThat(sessions.revokedSession).isEqualTo(login.sessionId());
    }

    private static AuthenticationApplicationService service(
            PasswordCredentialStore credentials,
            DeviceSessionStore sessions,
            RefreshTokenFactory tokens
    ) {
        AuthenticationLifetimePolicy lifetimePolicy = new AuthenticationLifetimePolicy() {
            @Override
            public Duration accessTokenLifetime() {
                return Duration.ofMinutes(15);
            }

            @Override
            public Duration refreshTokenLifetime() {
                return Duration.ofDays(30);
            }
        };
        return new AuthenticationApplicationService(credentials, sessions, tokens, lifetimePolicy);
    }

    private static final class StubCredentials implements PasswordCredentialStore {
        private final boolean accept;
        private String normalizedUsername;

        private StubCredentials(boolean accept) {
            this.accept = accept;
        }

        @Override
        public Optional<LoginIdentity> authenticate(String normalizedUsername, String rawPassword, Instant observedAt) {
            this.normalizedUsername = normalizedUsername;
            return accept ? Optional.of(new LoginIdentity(ACTOR, TENANT, MEMBER)) : Optional.empty();
        }
    }

    private static final class DeterministicTokens implements RefreshTokenFactory {
        private final ArrayDeque<String> tokens = new ArrayDeque<>();

        private DeterministicTokens(String... tokens) {
            this.tokens.addAll(java.util.List.of(tokens));
        }

        @Override
        public String create() {
            return tokens.removeFirst();
        }

        @Override
        public String digest(String rawToken) {
            return "test-digest-" + Integer.toUnsignedString(rawToken.hashCode(), 16);
        }
    }

    private static final class InMemorySessions implements DeviceSessionStore {
        private final Map<String, TokenState> tokens = new HashMap<>();
        private CreateSession created;
        private UUID revokedSession;

        @Override
        public void create(CreateSession session) {
            created = session;
            tokens.put(session.refreshTokenDigest(), new TokenState(
                    session.refreshTokenId(), session.sessionId(), session.actorId(), session.clientType(),
                    session.sessionExpiresAt(), session.refreshExpiresAt(), false, false
            ));
        }

        @Override
        public Optional<RefreshSession> lockRefreshToken(String tokenDigest, Instant observedAt) {
            var state = tokens.get(tokenDigest);
            return state == null ? Optional.empty() : Optional.of(state.asRefreshSession());
        }

        @Override
        public boolean rotateRefreshToken(UUID tokenId, RotateRefreshToken replacement, Instant observedAt) {
            var current = tokens.values().stream().filter(value -> value.id().equals(tokenId)).findFirst().orElseThrow();
            tokens.replaceAll((digest, value) -> value.id().equals(tokenId) ? value.consume() : value);
            tokens.put(replacement.tokenDigest(), new TokenState(
                    replacement.tokenId(), replacement.sessionId(), current.actorId(), current.clientType(),
                    current.sessionExpiresAt(), replacement.expiresAt(), false, false
            ));
            return true;
        }

        @Override
        public void revoke(UUID sessionId, Instant observedAt) {
            revokedSession = sessionId;
        }
    }

    private record TokenState(
            UUID id,
            UUID sessionId,
            ActorId actorId,
            ClientType clientType,
            Instant sessionExpiresAt,
            Instant tokenExpiresAt,
            boolean consumed,
            boolean revoked
    ) {
        DeviceSessionStore.RefreshSession asRefreshSession() {
            return new DeviceSessionStore.RefreshSession(
                    id, sessionId, actorId, clientType, sessionExpiresAt, tokenExpiresAt, consumed, revoked
            );
        }

        TokenState consume() {
            return new TokenState(
                    id, sessionId, actorId, clientType, sessionExpiresAt, tokenExpiresAt, true, revoked
            );
        }
    }
}

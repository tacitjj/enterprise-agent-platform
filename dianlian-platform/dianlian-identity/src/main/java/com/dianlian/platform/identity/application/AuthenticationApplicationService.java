package com.dianlian.platform.identity.application;

import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticationApplicationApi;
import com.dianlian.platform.identity.api.InvalidCredentialsException;
import com.dianlian.platform.identity.api.InvalidRefreshTokenException;
import java.time.Instant;
import java.util.Locale;
import java.util.Objects;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuthenticationApplicationService implements AuthenticationApplicationApi {

    private final PasswordCredentialStore credentialStore;
    private final DeviceSessionStore sessionStore;
    private final RefreshTokenFactory tokenFactory;
    private final AuthenticationLifetimePolicy lifetimePolicy;

    public AuthenticationApplicationService(
            PasswordCredentialStore credentialStore,
            DeviceSessionStore sessionStore,
            RefreshTokenFactory tokenFactory,
            AuthenticationLifetimePolicy lifetimePolicy
    ) {
        this.credentialStore = Objects.requireNonNull(credentialStore, "credentialStore must not be null");
        this.sessionStore = Objects.requireNonNull(sessionStore, "sessionStore must not be null");
        this.tokenFactory = Objects.requireNonNull(tokenFactory, "tokenFactory must not be null");
        this.lifetimePolicy = Objects.requireNonNull(lifetimePolicy, "lifetimePolicy must not be null");
    }

    @Override
    @Transactional(noRollbackFor = InvalidCredentialsException.class)
    public LoginSession login(PasswordLoginCommand command) {
        Objects.requireNonNull(command, "command must not be null");
        var identity = credentialStore.authenticate(
                command.username().toLowerCase(Locale.ROOT),
                command.password(),
                command.observedAt()
        ).orElseThrow(InvalidCredentialsException::new);

        var sessionId = UUID.randomUUID();
        var refreshTokenId = UUID.randomUUID();
        var refreshToken = tokenFactory.create();
        var accessExpiresAt = command.observedAt().plus(lifetimePolicy.accessTokenLifetime());
        var refreshExpiresAt = command.observedAt().plus(lifetimePolicy.refreshTokenLifetime());
        sessionStore.create(new DeviceSessionStore.CreateSession(
                sessionId,
                identity.actorId(),
                identity.activeTenantId(),
                identity.activeMemberId(),
                command.clientType(),
                command.deviceId(),
                command.deviceName(),
                command.observedAt(),
                refreshExpiresAt,
                refreshTokenId,
                tokenFactory.digest(refreshToken),
                refreshExpiresAt
        ));
        return new LoginSession(
                sessionId,
                identity.actorId(),
                command.clientType(),
                refreshToken,
                accessExpiresAt,
                refreshExpiresAt
        );
    }

    @Override
    @Transactional(noRollbackFor = InvalidRefreshTokenException.class)
    public LoginSession refresh(RefreshSessionCommand command) {
        Objects.requireNonNull(command, "command must not be null");
        var current = sessionStore.lockRefreshToken(tokenFactory.digest(command.refreshToken()), command.observedAt())
                .orElseThrow(InvalidRefreshTokenException::new);
        if (!current.isUsableAt(command.observedAt())) {
            sessionStore.revoke(current.sessionId(), command.observedAt());
            throw new InvalidRefreshTokenException();
        }

        var replacementToken = tokenFactory.create();
        var replacementId = UUID.randomUUID();
        var replacement = new DeviceSessionStore.RotateRefreshToken(
                replacementId,
                current.sessionId(),
                tokenFactory.digest(replacementToken),
                command.observedAt(),
                current.sessionExpiresAt()
        );
        if (!sessionStore.rotateRefreshToken(current.tokenId(), replacement, command.observedAt())) {
            sessionStore.revoke(current.sessionId(), command.observedAt());
            throw new InvalidRefreshTokenException();
        }
        return new LoginSession(
                current.sessionId(),
                current.actorId(),
                current.clientType(),
                replacementToken,
                command.observedAt().plus(lifetimePolicy.accessTokenLifetime()),
                current.sessionExpiresAt()
        );
    }

    @Override
    @Transactional
    public void logout(UUID sessionId, Instant observedAt) {
        Objects.requireNonNull(sessionId, "sessionId must not be null");
        Objects.requireNonNull(observedAt, "observedAt must not be null");
        sessionStore.revoke(sessionId, observedAt);
    }
}

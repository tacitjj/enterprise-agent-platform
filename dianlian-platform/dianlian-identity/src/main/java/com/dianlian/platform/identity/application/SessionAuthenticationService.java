package com.dianlian.platform.identity.application;

import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.SessionAuthenticationPort;
import java.time.Instant;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;
import org.springframework.stereotype.Service;

@Service
public final class SessionAuthenticationService implements SessionAuthenticationPort {

    private final SessionLookup sessionLookup;
    public SessionAuthenticationService(SessionLookup sessionLookup) {
        this.sessionLookup = Objects.requireNonNull(sessionLookup, "sessionLookup must not be null");
    }

    @Override
    public Optional<AuthenticatedPrincipal> authenticate(UUID sessionId, Instant observedAt) {
        Objects.requireNonNull(sessionId, "sessionId must not be null");
        Objects.requireNonNull(observedAt, "observedAt must not be null");
        return sessionLookup.findActiveBySessionId(sessionId, observedAt);
    }
}

package com.dianlian.platform.identity.application;

import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

public interface SessionLookup {

    Optional<AuthenticatedPrincipal> findActiveBySessionId(UUID sessionId, Instant observedAt);
}

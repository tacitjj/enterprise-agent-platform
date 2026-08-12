package com.dianlian.platform.identity.api;

import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

public interface SessionAuthenticationPort {

    Optional<AuthenticatedPrincipal> authenticate(UUID sessionId, Instant observedAt);
}

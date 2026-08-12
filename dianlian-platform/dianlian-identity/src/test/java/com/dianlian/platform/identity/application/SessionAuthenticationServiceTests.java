package com.dianlian.platform.identity.application;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class SessionAuthenticationServiceTests {

    @Test
    void repositoryReceivesJwtSessionIdAndServerObservationTime() {
        var lookup = new CapturingLookup();
        var service = new SessionAuthenticationService(lookup);
        var sessionId = UUID.fromString("10000000-0000-4000-8000-000000000040");
        var observedAt = Instant.parse("2026-08-11T00:00:00Z");

        assertTrue(service.authenticate(sessionId, observedAt).isEmpty());
        assertEquals(sessionId, lookup.sessionId);
        assertEquals(observedAt, lookup.observedAt);
    }

    private static final class CapturingLookup implements SessionLookup {

        private int calls;
        private UUID sessionId;
        private Instant observedAt;

        @Override
        public Optional<AuthenticatedPrincipal> findActiveBySessionId(UUID sessionId, Instant observedAt) {
            calls++;
            this.sessionId = sessionId;
            this.observedAt = observedAt;
            return Optional.empty();
        }
    }
}

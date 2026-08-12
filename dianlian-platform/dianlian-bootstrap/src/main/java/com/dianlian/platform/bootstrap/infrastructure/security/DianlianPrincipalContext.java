package com.dianlian.platform.bootstrap.infrastructure.security;

import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import java.util.Optional;
import org.springframework.stereotype.Component;

@Component
public final class DianlianPrincipalContext {

    private final ThreadLocal<AuthenticatedPrincipal> current = new ThreadLocal<>();

    public Optional<AuthenticatedPrincipal> current() {
        return Optional.ofNullable(current.get());
    }

    void set(AuthenticatedPrincipal principal) {
        current.set(principal);
    }

    void clear() {
        current.remove();
    }
}

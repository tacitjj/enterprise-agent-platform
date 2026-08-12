package com.dianlian.platform.bootstrap.infrastructure.security;

import com.dianlian.platform.identity.api.ActorContextPort;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import java.util.Objects;
import java.util.Optional;
import org.springframework.stereotype.Component;

@Component
public final class SaTokenActorContextAdapter implements ActorContextPort {

    private final DianlianPrincipalContext principalContext;

    public SaTokenActorContextAdapter(DianlianPrincipalContext principalContext) {
        this.principalContext = Objects.requireNonNull(principalContext, "principalContext must not be null");
    }

    @Override
    public Optional<AuthenticatedPrincipal> current() {
        return principalContext.current();
    }
}

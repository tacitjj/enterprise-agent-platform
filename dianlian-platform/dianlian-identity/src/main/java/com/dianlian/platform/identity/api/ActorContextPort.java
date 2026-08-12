package com.dianlian.platform.identity.api;

import java.util.Optional;

public interface ActorContextPort {

    Optional<AuthenticatedPrincipal> current();

    default AuthenticatedPrincipal requireCurrent() {
        return current().orElseThrow(AuthenticationRequiredException::new);
    }
}

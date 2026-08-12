package com.dianlian.platform.identity.infrastructure;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.AccessContextPort;
import com.dianlian.platform.identity.api.ActorContextPort;
import java.util.Objects;
import org.springframework.stereotype.Component;

@Component
public final class PrincipalAccessContextAdapter implements AccessContextPort {

    private final ActorContextPort actorContextPort;

    public PrincipalAccessContextAdapter(ActorContextPort actorContextPort) {
        this.actorContextPort = Objects.requireNonNull(actorContextPort, "actorContextPort must not be null");
    }

    @Override
    public AccessContext requireCurrent() {
        return AccessContext.fromAuthenticatedPrincipal(actorContextPort.requireCurrent());
    }
}

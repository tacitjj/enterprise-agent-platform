package com.dianlian.platform.identity.application;

import com.dianlian.platform.identity.api.ActorContextPort;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.SessionViewApplicationApi;
import java.time.Instant;
import java.util.Objects;
import org.springframework.stereotype.Service;

@Service
public final class CurrentSessionApplicationService implements SessionViewApplicationApi {

    private final ActorContextPort actorContextPort;

    public CurrentSessionApplicationService(ActorContextPort actorContextPort) {
        this.actorContextPort = Objects.requireNonNull(actorContextPort, "actorContextPort must not be null");
    }

    @Override
    public SessionView currentSession() {
        return toView(actorContextPort.requireCurrent(), Instant.now());
    }

    static SessionView toView(AuthenticatedPrincipal principal, Instant serverTime) {
        Objects.requireNonNull(principal, "principal must not be null");
        return new SessionView(
                principal.sessionId(),
                new SessionView.User(
                        principal.actorId(),
                        principal.displayName(),
                        principal.avatarUrl(),
                        principal.accountStatus()
                ),
                principal.activeTenant(),
                principal.roleGrants(),
                principal.permissions(),
                principal.permissionVersion(),
                serverTime
        );
    }
}

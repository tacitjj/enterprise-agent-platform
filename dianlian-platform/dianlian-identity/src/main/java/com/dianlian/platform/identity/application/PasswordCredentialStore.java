package com.dianlian.platform.identity.application;

import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.TenantId;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;

public interface PasswordCredentialStore {

    Optional<LoginIdentity> authenticate(String normalizedUsername, String rawPassword, Instant observedAt);

    record LoginIdentity(ActorId actorId, TenantId activeTenantId, UUID activeMemberId) {
    }
}

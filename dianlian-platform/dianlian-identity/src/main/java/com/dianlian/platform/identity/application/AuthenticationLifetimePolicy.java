package com.dianlian.platform.identity.application;

import java.time.Duration;

public interface AuthenticationLifetimePolicy {

    Duration accessTokenLifetime();

    Duration refreshTokenLifetime();
}

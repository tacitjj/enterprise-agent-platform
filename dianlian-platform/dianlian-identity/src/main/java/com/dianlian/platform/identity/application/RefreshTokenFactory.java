package com.dianlian.platform.identity.application;

public interface RefreshTokenFactory {

    String create();

    String digest(String rawToken);
}

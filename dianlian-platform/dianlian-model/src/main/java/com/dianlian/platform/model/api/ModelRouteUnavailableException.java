package com.dianlian.platform.model.api;

public class ModelRouteUnavailableException extends RuntimeException {
    public ModelRouteUnavailableException() {
        super("No active model route is available");
    }
}

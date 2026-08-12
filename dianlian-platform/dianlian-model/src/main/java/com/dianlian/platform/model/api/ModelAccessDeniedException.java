package com.dianlian.platform.model.api;

public class ModelAccessDeniedException extends RuntimeException {
    public ModelAccessDeniedException(String permission) {
        super("Missing model permission: " + permission);
    }
}

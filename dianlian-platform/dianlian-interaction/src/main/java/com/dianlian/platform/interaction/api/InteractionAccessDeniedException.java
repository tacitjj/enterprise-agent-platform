package com.dianlian.platform.interaction.api;

public class InteractionAccessDeniedException extends RuntimeException {
    public InteractionAccessDeniedException(String permission) {
        super("Missing interaction permission: " + permission);
    }
}

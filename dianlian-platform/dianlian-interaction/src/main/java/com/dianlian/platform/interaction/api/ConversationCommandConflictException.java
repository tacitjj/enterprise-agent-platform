package com.dianlian.platform.interaction.api;

public class ConversationCommandConflictException extends RuntimeException {
    private final String code;

    public ConversationCommandConflictException(String code, String message) {
        super(message);
        this.code = code;
    }

    public String code() {
        return code;
    }
}

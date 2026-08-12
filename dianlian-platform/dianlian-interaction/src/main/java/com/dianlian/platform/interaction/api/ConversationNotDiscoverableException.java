package com.dianlian.platform.interaction.api;

public class ConversationNotDiscoverableException extends RuntimeException {
    public ConversationNotDiscoverableException() {
        super("Conversation does not exist or is not visible");
    }
}

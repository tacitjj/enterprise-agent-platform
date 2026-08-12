package com.dianlian.platform.interaction.api;

import com.dianlian.platform.identity.api.AccessContext;

public interface ConversationCommands {
    ConversationCommandOutcome<ConversationSummary> create(
            CreateConversationCommand command,
            AccessContext accessContext
    );

    ConversationCommandOutcome<ConversationMessageView> send(
            SendConversationMessageCommand command,
            AccessContext accessContext
    );
}

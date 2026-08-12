package com.dianlian.platform.interaction.api;

import com.dianlian.platform.identity.api.AccessContext;
import java.util.List;
import java.util.UUID;

public interface ConversationQuery {
    List<ConversationSummary> list(AccessContext accessContext);

    ConversationMessagePage messages(
            UUID conversationId,
            long afterSequenceNo,
            int limit,
            AccessContext accessContext
    );
}

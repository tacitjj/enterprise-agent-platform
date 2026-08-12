package com.dianlian.platform.interaction.api;

import java.util.List;
import java.util.Objects;

public record ConversationMessagePage(
        List<ConversationMessageView> items,
        long upToSequenceNo,
        boolean hasMore,
        long membershipVersion
) {
    public ConversationMessagePage {
        items = List.copyOf(Objects.requireNonNull(items, "items must not be null"));
        if (upToSequenceNo < 0 || membershipVersion < 1) throw new IllegalArgumentException("page counters are invalid");
    }
}

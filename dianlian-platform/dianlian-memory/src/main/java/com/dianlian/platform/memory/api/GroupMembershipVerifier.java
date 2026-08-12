package com.dianlian.platform.memory.api;

import java.util.UUID;

@FunctionalInterface
public interface GroupMembershipVerifier {

    boolean isActiveMember(UUID tenantId, UUID groupConversationId, UUID userId);
}

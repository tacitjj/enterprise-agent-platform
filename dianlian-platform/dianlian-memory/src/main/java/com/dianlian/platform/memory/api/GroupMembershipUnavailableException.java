package com.dianlian.platform.memory.api;

public final class GroupMembershipUnavailableException extends RuntimeException {

    public GroupMembershipUnavailableException() {
        super("exactly one active group membership verifier is required");
    }
}

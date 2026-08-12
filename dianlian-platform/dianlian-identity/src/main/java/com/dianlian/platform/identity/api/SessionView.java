package com.dianlian.platform.identity.api;

import java.time.Instant;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

public record SessionView(
        UUID sessionId,
        User user,
        Tenant activeTenant,
        List<RoleGrant> roleGrants,
        Set<String> permissions,
        String permissionVersion,
        Instant serverTime
) {

    public SessionView {
        Objects.requireNonNull(sessionId, "sessionId must not be null");
        Objects.requireNonNull(user, "user must not be null");
        roleGrants = List.copyOf(Objects.requireNonNull(roleGrants, "roleGrants must not be null"));
        permissions = Set.copyOf(Objects.requireNonNull(permissions, "permissions must not be null"));
        permissionVersion = requireText(permissionVersion, "permissionVersion");
        Objects.requireNonNull(serverTime, "serverTime must not be null");
    }

    public record User(
            ActorId id,
            String displayName,
            String avatarUrl,
            AccountStatus accountStatus
    ) {
        public User {
            Objects.requireNonNull(id, "id must not be null");
            displayName = requireText(displayName, "displayName");
            Objects.requireNonNull(accountStatus, "accountStatus must not be null");
        }
    }

    public record Tenant(
            TenantId id,
            String displayName,
            TenantStatus tenantStatus,
            MembershipStatus membershipStatus
    ) {
        public Tenant {
            Objects.requireNonNull(id, "id must not be null");
            displayName = requireText(displayName, "displayName");
            Objects.requireNonNull(tenantStatus, "tenantStatus must not be null");
            Objects.requireNonNull(membershipStatus, "membershipStatus must not be null");
        }
    }

    public record RoleGrant(
            String roleCode,
            DataScopeType scopeType,
            UUID scopeId
    ) {
        private static final Pattern ROLE_CODE = Pattern.compile("^[A-Z][A-Z0-9_]{1,63}$");

        public RoleGrant {
            roleCode = requireText(roleCode, "roleCode");
            if (!ROLE_CODE.matcher(roleCode).matches()) {
                throw new IllegalArgumentException("Invalid role code");
            }
            Objects.requireNonNull(scopeType, "scopeType must not be null");
            Objects.requireNonNull(scopeId, "scopeId must not be null");
        }
    }

    public enum AccountStatus {
        ACTIVE,
        SUSPENDED
    }

    public enum TenantStatus {
        ACTIVE,
        SUSPENDED,
        CLOSED
    }

    public enum MembershipStatus {
        ACTIVE,
        SUSPENDED,
        LEFT,
        REMOVED,
        EXPIRED
    }

    public enum DataScopeType {
        PLATFORM,
        TENANT,
        DEPARTMENT,
        PROJECT,
        CONVERSATION,
        USER_AGENT,
        GROUP_AGENT,
        AGENT,
        OBJECT_GRANT,
        SUPPORT_SESSION
    }

    private static String requireText(String value, String fieldName) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(fieldName + " must not be blank");
        }
        return value;
    }
}

package com.dianlian.platform.identity.api;

import java.time.Instant;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.TreeSet;
import java.util.UUID;
import java.util.regex.Pattern;

public record AuthenticatedPrincipal(
        UUID sessionId,
        ActorId actorId,
        String displayName,
        String avatarUrl,
        SessionView.AccountStatus accountStatus,
        SessionView.Tenant activeTenant,
        List<SessionView.RoleGrant> roleGrants,
        Set<String> permissions,
        String permissionVersion,
        Instant authenticatedAt,
        Instant expiresAt
) {

    private static final Pattern PERMISSION_CODE = Pattern.compile("^[a-z][a-z0-9_.:-]{1,127}$");

    public AuthenticatedPrincipal {
        Objects.requireNonNull(sessionId, "sessionId must not be null");
        Objects.requireNonNull(actorId, "actorId must not be null");
        displayName = requireText(displayName, "displayName");
        Objects.requireNonNull(accountStatus, "accountStatus must not be null");
        Objects.requireNonNull(roleGrants, "roleGrants must not be null");
        Objects.requireNonNull(permissions, "permissions must not be null");
        permissionVersion = requireText(permissionVersion, "permissionVersion");
        Objects.requireNonNull(authenticatedAt, "authenticatedAt must not be null");
        Objects.requireNonNull(expiresAt, "expiresAt must not be null");
        if (!expiresAt.isAfter(authenticatedAt)) {
            throw new IllegalArgumentException("expiresAt must be after authenticatedAt");
        }

        roleGrants = roleGrants.stream()
                .map(roleGrant -> Objects.requireNonNull(roleGrant, "roleGrant must not be null"))
                .distinct()
                .sorted(Comparator
                        .comparing(SessionView.RoleGrant::roleCode)
                        .thenComparing(grant -> grant.scopeType().name())
                .thenComparing(grant -> grant.scopeId().toString()))
                .toList();
        if (roleGrants.size() > 100) {
            throw new IllegalArgumentException("roleGrants must contain at most 100 entries");
        }

        var sortedPermissions = new TreeSet<String>();
        for (var permission : permissions) {
            var normalized = requireText(permission, "permission");
            if (!PERMISSION_CODE.matcher(normalized).matches()) {
                throw new IllegalArgumentException("Invalid permission code");
            }
            sortedPermissions.add(normalized);
        }
        if (sortedPermissions.size() > 500) {
            throw new IllegalArgumentException("permissions must contain at most 500 entries");
        }
        permissions = Collections.unmodifiableSortedSet(sortedPermissions);
    }

    public TenantId requireActiveTenantId() {
        if (activeTenant == null) {
            throw new ActiveTenantRequiredException();
        }
        return activeTenant.id();
    }

    private static String requireText(String value, String fieldName) {
        Objects.requireNonNull(value, fieldName + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(fieldName + " must not be blank");
        }
        return value;
    }
}

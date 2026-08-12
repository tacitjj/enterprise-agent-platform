package com.dianlian.platform.identity.domain;

import com.dianlian.platform.identity.api.SessionView;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Comparator;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.Set;

public final class PermissionVersion {

    private PermissionVersion() {
    }

    public static String fingerprint(
            long userVersion,
            Long tenantVersion,
            Long membershipVersion,
            List<SessionView.RoleGrant> roleGrants,
            Set<String> permissions
    ) {
        Objects.requireNonNull(roleGrants, "roleGrants must not be null");
        Objects.requireNonNull(permissions, "permissions must not be null");
        var canonical = new StringBuilder("v1\n")
                .append(userVersion).append('\n')
                .append(tenantVersion == null ? "-" : tenantVersion).append('\n')
                .append(membershipVersion == null ? "-" : membershipVersion).append('\n');

        roleGrants.stream()
                .sorted(Comparator
                        .comparing(SessionView.RoleGrant::roleCode)
                        .thenComparing(grant -> grant.scopeType().name())
                        .thenComparing(grant -> grant.scopeId().toString()))
                .forEach(grant -> canonical
                        .append("r:")
                        .append(grant.roleCode()).append(':')
                        .append(grant.scopeType()).append(':')
                        .append(grant.scopeId()).append('\n'));
        permissions.stream()
                .sorted()
                .forEach(permission -> canonical.append("p:").append(permission).append('\n'));

        try {
            var sha256 = MessageDigest.getInstance("SHA-256");
            var digest = sha256.digest(canonical.toString().getBytes(StandardCharsets.UTF_8));
            return "v1-" + HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is not available", exception);
        }
    }
}

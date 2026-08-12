package com.dianlian.platform.bootstrap.infrastructure.web;

import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.SessionViewApplicationApi;
import com.dianlian.platform.identity.api.TenantId;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/session")
public final class SessionController {

    private final SessionViewApplicationApi sessionApi;

    public SessionController(SessionViewApplicationApi sessionApi) {
        this.sessionApi = sessionApi;
    }

    @GetMapping
    public ResponseEntity<SessionResponse> currentSession() {
        var view = sessionApi.currentSession();
        return ResponseEntity.ok()
                .cacheControl(CacheControl.noStore())
                .body(SessionResponse.from(view));
    }

    public record SessionResponse(
            UUID sessionId,
            UserResponse user,
            TenantResponse activeTenant,
            List<RoleGrantResponse> roleGrants,
            Set<String> permissions,
            String permissionVersion,
            Instant serverTime
    ) {
        static SessionResponse from(SessionView view) {
            return new SessionResponse(
                    view.sessionId(),
                    UserResponse.from(view.user()),
                    view.activeTenant() == null ? null : TenantResponse.from(view.activeTenant()),
                    view.roleGrants().stream().map(RoleGrantResponse::from).toList(),
                    view.permissions(),
                    view.permissionVersion(),
                    view.serverTime()
            );
        }
    }

    public record UserResponse(
            UUID id,
            String displayName,
            String avatarUrl,
            SessionView.AccountStatus accountStatus
    ) {
        static UserResponse from(SessionView.User user) {
            return new UserResponse(user.id().value(), user.displayName(), user.avatarUrl(), user.accountStatus());
        }
    }

    public record TenantResponse(
            UUID id,
            String displayName,
            SessionView.TenantStatus tenantStatus,
            SessionView.MembershipStatus membershipStatus
    ) {
        static TenantResponse from(SessionView.Tenant tenant) {
            return new TenantResponse(
                    tenant.id().value(),
                    tenant.displayName(),
                    tenant.tenantStatus(),
                    tenant.membershipStatus()
            );
        }
    }

    public record RoleGrantResponse(
            String roleCode,
            SessionView.DataScopeType scopeType,
            UUID scopeId
    ) {
        static RoleGrantResponse from(SessionView.RoleGrant grant) {
            return new RoleGrantResponse(grant.roleCode(), grant.scopeType(), grant.scopeId());
        }
    }
}

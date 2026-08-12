package com.dianlian.platform.task.infrastructure.web;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorId;
import com.dianlian.platform.identity.api.AuthenticatedPrincipal;
import com.dianlian.platform.identity.api.AuthenticationRequiredException;
import com.dianlian.platform.identity.api.SessionView;
import com.dianlian.platform.identity.api.TenantId;
import com.dianlian.platform.task.api.TaskEventBatch;
import com.dianlian.platform.task.api.TaskEventStreamQuery;
import com.dianlian.platform.task.api.TaskPermissions;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

class PersistentTaskEventSsePublisherTests {

    private static final UUID SESSION_ID = UUID.fromString("10000000-0000-0000-0000-000000000001");
    private static final UUID ACTOR_ID = UUID.fromString("20000000-0000-0000-0000-000000000001");
    private static final UUID TENANT_ID = UUID.fromString("30000000-0000-0000-0000-000000000001");
    private static final UUID TASK_ID = UUID.fromString("40000000-0000-0000-0000-000000000001");
    private static final Instant NOW = Instant.parse("2026-08-11T03:00:00Z");

    @Test
    void refusesToOpenWhenTheExactSessionCanNoLongerBeAuthenticated() {
        var query = new RecordingQuery();
        var publisher = publisher(query, (sessionId, observedAt) -> Optional.empty());
        try {
            assertThatThrownBy(() -> publisher.open(TASK_ID, null, SESSION_ID, access()))
                    .isInstanceOf(AuthenticationRequiredException.class);
            assertThat(query.calls.get()).isZero();
        } finally {
            publisher.stop();
        }
    }

    @Test
    void reauthenticatesBeforeTheNextPayloadBatchAndClosesAfterSessionRevocation() throws Exception {
        var query = new RecordingQuery();
        var authenticationCalls = new AtomicInteger();
        var rejected = new CountDownLatch(1);
        var publisher = publisher(query, (sessionId, observedAt) -> {
            if (authenticationCalls.incrementAndGet() == 1) {
                return Optional.of(principal());
            }
            rejected.countDown();
            return Optional.empty();
        });
        try {
            publisher.open(TASK_ID, null, SESSION_ID, access());

            assertThat(rejected.await(1, TimeUnit.SECONDS)).isTrue();
            assertThat(authenticationCalls.get()).isGreaterThanOrEqualTo(2);
            assertThat(query.calls.get()).as("no second payload query may run after revocation").isEqualTo(1);
        } finally {
            publisher.stop();
        }
    }

    private static PersistentTaskEventSsePublisher publisher(
            RecordingQuery query,
            com.dianlian.platform.identity.api.SessionAuthenticationPort authenticationPort
    ) {
        return new PersistentTaskEventSsePublisher(
                query,
                authenticationPort,
                Clock.fixed(NOW, ZoneOffset.UTC),
                Duration.ofSeconds(1),
                Duration.ofMillis(5),
                Duration.ofMillis(10)
        );
    }

    private static AccessContext access() {
        return AccessContext.fromAuthenticatedPrincipal(principal());
    }

    private static AuthenticatedPrincipal principal() {
        return new AuthenticatedPrincipal(
                SESSION_ID,
                new ActorId(ACTOR_ID),
                "测试用户",
                null,
                SessionView.AccountStatus.ACTIVE,
                new SessionView.Tenant(
                        new TenantId(TENANT_ID),
                        "测试企业",
                        SessionView.TenantStatus.ACTIVE,
                        SessionView.MembershipStatus.ACTIVE
                ),
                List.of(new SessionView.RoleGrant(
                        "TENANT_MEMBER",
                        SessionView.DataScopeType.TENANT,
                        TENANT_ID
                )),
                Set.of(TaskPermissions.READ),
                "test-permissions-v1",
                NOW.minusSeconds(60),
                NOW.plusSeconds(3600)
        );
    }

    private static final class RecordingQuery implements TaskEventStreamQuery {
        private final AtomicInteger calls = new AtomicInteger();

        @Override
        public TaskEventBatch read(
                UUID taskId,
                String afterEventId,
                int limit,
                AccessContext accessContext
        ) {
            calls.incrementAndGet();
            return new TaskEventBatch(List.of(), false);
        }
    }
}

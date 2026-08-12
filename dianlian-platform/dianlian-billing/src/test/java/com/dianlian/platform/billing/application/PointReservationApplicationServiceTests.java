package com.dianlian.platform.billing.application;

import static com.dianlian.platform.identity.api.AccessContextFixtures.ACTOR_ID;
import static com.dianlian.platform.identity.api.AccessContextFixtures.TENANT_ID;
import static com.dianlian.platform.identity.api.AccessContextFixtures.authenticated;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.billing.api.PointReservationResult;
import com.dianlian.platform.billing.api.PointSettlementResult;
import com.dianlian.platform.billing.api.ReservePointsCommand;
import java.lang.reflect.Method;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

class PointReservationApplicationServiceTests {

    private static final Instant NOW = Instant.parse("2026-01-02T03:04:05Z");

    @Test
    void derivesTenantAndActorOnlyFromTheAuthenticatedContext() {
        var repository = new RecordingRepository();
        var service = new PointReservationApplicationService(
                repository,
                Clock.fixed(NOW, ZoneOffset.UTC)
        );
        var command = new ReservePointsCommand(
                "TASK",
                UUID.fromString("10000000-0000-0000-0000-000000000001"),
                "TENANT",
                TENANT_ID,
                50,
                "task-create:reservation-test-0001"
        );

        service.reserve(command, authenticated());

        assertThat(repository.request.tenantId()).isEqualTo(TENANT_ID);
        assertThat(repository.request.actorId()).isEqualTo(ACTOR_ID);
        assertThat(repository.request.command()).isSameAs(command);
        assertThat(repository.request.occurredAt()).isEqualTo(NOW);
    }

    @Test
    void reserveRequiresTheCallingTaskTransaction() throws NoSuchMethodException {
        Method method = PointReservationApplicationService.class.getMethod(
                "reserve",
                ReservePointsCommand.class,
                com.dianlian.platform.identity.api.AccessContext.class
        );

        assertThat(method.getAnnotation(Transactional.class).propagation())
                .isEqualTo(Propagation.MANDATORY);
    }

    @Test
    void rejectsAZeroPointReservation() {
        assertThatThrownBy(() -> new ReservePointsCommand(
                "TASK",
                UUID.randomUUID(),
                "TENANT",
                TENANT_ID,
                0,
                "task-create:reservation-test-0002"
        )).isInstanceOf(IllegalArgumentException.class);
    }

    private static final class RecordingRepository implements PointReservationRepository {

        private ReservePointsRequest request;

        @Override
        public PointReservationResult reserve(ReservePointsRequest request) {
            this.request = request;
            return new PointReservationResult(
                    UUID.fromString("20000000-0000-0000-0000-000000000001"),
                    UUID.fromString("30000000-0000-0000-0000-000000000001"),
                    request.command().amount(),
                    "ACTIVE",
                    request.occurredAt(),
                    false
            );
        }

        @Override
        public PointSettlementResult settle(SettlePointsRequest request) {
            throw new UnsupportedOperationException("not used by reservation tests");
        }
    }
}

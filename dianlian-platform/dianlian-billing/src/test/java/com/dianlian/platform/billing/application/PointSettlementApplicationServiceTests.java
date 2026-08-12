package com.dianlian.platform.billing.application;

import static org.assertj.core.api.Assertions.assertThat;

import com.dianlian.platform.billing.api.PointReservationResult;
import com.dianlian.platform.billing.api.PointSettlementResult;
import com.dianlian.platform.billing.api.SettlePointsCommand;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class PointSettlementApplicationServiceTests {

    private static final Instant NOW = Instant.parse("2026-08-11T08:00:00Z");

    @Test
    void forwardsTheFrozenSettlementIntentToTheRepository() {
        var repository = new RecordingRepository();
        var service = new PointSettlementApplicationService(
                repository,
                Clock.fixed(NOW, ZoneOffset.UTC)
        );
        var command = new SettlePointsCommand(
                UUID.randomUUID(),
                UUID.randomUUID(),
                UUID.randomUUID(),
                320,
                "chat-invocation:settle-0001",
                "sha256:settlement-0001",
                "MODEL_USAGE"
        );

        var result = service.settle(command);

        assertThat(repository.request.command()).isSameAs(command);
        assertThat(repository.request.occurredAt()).isEqualTo(NOW);
        assertThat(result.capturedAmount()).isEqualTo(320);
    }

    private static final class RecordingRepository implements PointReservationRepository {
        private SettlePointsRequest request;

        @Override
        public PointReservationResult reserve(ReservePointsRequest request) {
            throw new UnsupportedOperationException("not used by settlement tests");
        }

        @Override
        public PointSettlementResult settle(SettlePointsRequest request) {
            this.request = request;
            return new PointSettlementResult(
                    UUID.randomUUID(),
                    request.command().reservationId(),
                    request.command().capturedAmount(),
                    0,
                    "CAPTURED",
                    request.occurredAt(),
                    false
            );
        }
    }
}

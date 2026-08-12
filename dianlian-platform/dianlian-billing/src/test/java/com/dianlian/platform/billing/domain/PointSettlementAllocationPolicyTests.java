package com.dianlian.platform.billing.domain;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class PointSettlementAllocationPolicyTests {

    private static final Instant NOW = Instant.parse("2026-08-11T08:00:00Z");

    @Test
    void expiresReleasedAndPreviouslyAvailableAmountsWithoutRestoringThemToAvailable() {
        var expiredLotId = UUID.randomUUID();
        var validLotId = UUID.randomUUID();

        var plan = PointSettlementAllocationPolicy.plan(
                List.of(
                        new PointSettlementAllocationPolicy.LotAllocation(
                                validLotId,
                                20,
                                20,
                                NOW.plus(1, ChronoUnit.DAYS),
                                20,
                                PointLotStatus.ACTIVE
                        ),
                        new PointSettlementAllocationPolicy.LotAllocation(
                                expiredLotId,
                                80,
                                10,
                                NOW.minusSeconds(1),
                                10,
                                PointLotStatus.ACTIVE
                        )
                ),
                50,
                NOW
        );

        assertThat(plan.reservedAmount()).isEqualTo(100);
        assertThat(plan.capturedAmount()).isEqualTo(50);
        assertThat(plan.releasedToAvailableAmount()).isEqualTo(20);
        assertThat(plan.releasedToExpirationAmount()).isEqualTo(30);
        assertThat(plan.existingAvailableExpiredAmount()).isEqualTo(10);
        assertThat(plan.totalExpiredAmount()).isEqualTo(40);
        assertThat(plan.allocations()).first().satisfies(allocation -> {
            assertThat(allocation.lotId()).isEqualTo(expiredLotId);
            assertThat(allocation.expired()).isTrue();
            assertThat(allocation.capturedAmount()).isEqualTo(50);
            assertThat(allocation.releasedToExpirationAmount()).isEqualTo(30);
            assertThat(allocation.existingAvailableExpiredAmount()).isEqualTo(10);
        });
        assertThat(plan.allocations()).last().satisfies(allocation -> {
            assertThat(allocation.lotId()).isEqualTo(validLotId);
            assertThat(allocation.expired()).isFalse();
            assertThat(allocation.releasedToAvailableAmount()).isEqualTo(20);
        });
    }

    @Test
    void treatsTheExpiryInstantAndAnAlreadyExpiredStatusAsExpired() {
        var expiresNow = PointSettlementAllocationPolicy.plan(
                List.of(new PointSettlementAllocationPolicy.LotAllocation(
                        UUID.randomUUID(),
                        10,
                        0,
                        NOW,
                        10,
                        PointLotStatus.ACTIVE
                )),
                0,
                NOW
        );
        var statusExpired = PointSettlementAllocationPolicy.plan(
                List.of(new PointSettlementAllocationPolicy.LotAllocation(
                        UUID.randomUUID(),
                        10,
                        0,
                        NOW.plus(1, ChronoUnit.DAYS),
                        10,
                        PointLotStatus.EXPIRED
                )),
                0,
                NOW
        );

        assertThat(expiresNow.allocations().getFirst().expired()).isTrue();
        assertThat(statusExpired.allocations().getFirst().expired()).isTrue();
        assertThat(expiresNow.releasedToAvailableAmount()).isZero();
        assertThat(statusExpired.releasedToAvailableAmount()).isZero();
    }
}

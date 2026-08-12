package com.dianlian.platform.billing.domain;

import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

public final class PointSettlementAllocationPolicy {

    private PointSettlementAllocationPolicy() {
    }

    public static SettlementPlan plan(
            List<LotAllocation> allocations,
            long capturedAmount,
            Instant occurredAt
    ) {
        Objects.requireNonNull(allocations, "allocations must not be null");
        Objects.requireNonNull(occurredAt, "occurredAt must not be null");
        if (capturedAmount < 0) {
            throw new IllegalArgumentException("capturedAmount cannot be negative");
        }

        var ordered = allocations.stream()
                .sorted(Comparator
                        .comparing((LotAllocation allocation) -> !allocation.expiredAt(occurredAt))
                        .thenComparing(
                                LotAllocation::expiresAt,
                                Comparator.nullsLast(Comparator.naturalOrder())
                        )
                        .thenComparingInt(LotAllocation::priority)
                        .thenComparing(LotAllocation::lotId))
                .toList();
        long reservedAmount = ordered.stream().mapToLong(LotAllocation::amount).sum();
        if (capturedAmount > reservedAmount) {
            throw new IllegalArgumentException("capturedAmount exceeds allocated reservation amount");
        }

        long remainingCapture = capturedAmount;
        var settlements = new ArrayList<AllocationSettlement>(ordered.size());
        for (var allocation : ordered) {
            long lotCaptured = Math.min(remainingCapture, allocation.amount());
            long lotReleased = allocation.amount() - lotCaptured;
            boolean expired = allocation.expiredAt(occurredAt);
            settlements.add(new AllocationSettlement(
                    allocation.lotId(),
                    allocation.amount(),
                    allocation.availableAmount(),
                    lotCaptured,
                    expired ? 0 : lotReleased,
                    expired ? lotReleased : 0,
                    expired ? allocation.availableAmount() : 0,
                    expired
            ));
            remainingCapture -= lotCaptured;
        }
        if (remainingCapture != 0) {
            throw new IllegalStateException("Unable to allocate captured point amount");
        }
        return new SettlementPlan(List.copyOf(settlements));
    }

    public record LotAllocation(
            UUID lotId,
            long amount,
            long availableAmount,
            Instant expiresAt,
            int priority,
            PointLotStatus status
    ) {
        public LotAllocation {
            Objects.requireNonNull(lotId, "lotId must not be null");
            Objects.requireNonNull(status, "status must not be null");
            if (amount <= 0 || availableAmount < 0) {
                throw new IllegalArgumentException("lot allocation amounts are invalid");
            }
        }

        boolean expiredAt(Instant occurredAt) {
            return status == PointLotStatus.EXPIRED
                    || (expiresAt != null && !expiresAt.isAfter(occurredAt));
        }
    }

    public record AllocationSettlement(
            UUID lotId,
            long reservedAmount,
            long availableAmountBeforeSettlement,
            long capturedAmount,
            long releasedToAvailableAmount,
            long releasedToExpirationAmount,
            long existingAvailableExpiredAmount,
            boolean expired
    ) {
        public AllocationSettlement {
            Objects.requireNonNull(lotId, "lotId must not be null");
        }
    }

    public record SettlementPlan(List<AllocationSettlement> allocations) {
        public SettlementPlan {
            allocations = List.copyOf(Objects.requireNonNull(allocations, "allocations must not be null"));
        }

        public long reservedAmount() {
            return allocations.stream().mapToLong(AllocationSettlement::reservedAmount).sum();
        }

        public long capturedAmount() {
            return allocations.stream().mapToLong(AllocationSettlement::capturedAmount).sum();
        }

        public long releasedToAvailableAmount() {
            return allocations.stream().mapToLong(AllocationSettlement::releasedToAvailableAmount).sum();
        }

        public long releasedToExpirationAmount() {
            return allocations.stream().mapToLong(AllocationSettlement::releasedToExpirationAmount).sum();
        }

        public long existingAvailableExpiredAmount() {
            return allocations.stream().mapToLong(AllocationSettlement::existingAvailableExpiredAmount).sum();
        }

        public long totalExpiredAmount() {
            return releasedToExpirationAmount() + existingAvailableExpiredAmount();
        }
    }
}

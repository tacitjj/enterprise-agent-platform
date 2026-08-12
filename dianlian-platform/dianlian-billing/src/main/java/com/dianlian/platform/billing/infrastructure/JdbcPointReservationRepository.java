package com.dianlian.platform.billing.infrastructure;

import com.dianlian.platform.billing.api.InsufficientPointsException;
import com.dianlian.platform.billing.api.PointAccountUnavailableException;
import com.dianlian.platform.billing.api.PointReservationConflictException;
import com.dianlian.platform.billing.api.PointReservationResult;
import com.dianlian.platform.billing.api.PointSettlementResult;
import com.dianlian.platform.billing.application.PointReservationRepository;
import com.dianlian.platform.billing.application.ReservePointsRequest;
import com.dianlian.platform.billing.application.SettlePointsRequest;
import com.dianlian.platform.billing.domain.LedgerDirection;
import com.dianlian.platform.billing.domain.LedgerEntry;
import com.dianlian.platform.billing.domain.PointAccount;
import com.dianlian.platform.billing.domain.PointAccountStatus;
import com.dianlian.platform.billing.domain.PointLot;
import com.dianlian.platform.billing.domain.PointLotStatus;
import com.dianlian.platform.billing.domain.PointSettlementAllocationPolicy;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcPointReservationRepository implements PointReservationRepository {

    private static final String UNIT_CODE = "POINT";
    private static final String ACCOUNT_TYPE = "MAIN";

    private final JdbcTemplate jdbcTemplate;

    public JdbcPointReservationRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @Override
    public PointReservationResult reserve(ReservePointsRequest request) {
        var replay = findExisting(request);
        if (replay != null) {
            return replay;
        }

        var account = lockAccount(request.tenantId());
        replay = findExisting(request);
        if (replay != null) {
            return replay;
        }
        if (account.status() != PointAccountStatus.ACTIVE) {
            throw new PointAccountUnavailableException("Point account is not active");
        }
        if (account.availableAmount() < request.command().amount()) {
            throw new InsufficientPointsException(account.availableAmount(), request.command().amount());
        }

        var lots = lockAvailableLots(account.id(), request.occurredAt());
        var allocations = allocate(lots, request.command().amount());
        var reservationId = UUID.randomUUID();
        var ledgerTransactionId = UUID.randomUUID();

        insertReservation(request, account, reservationId, ledgerTransactionId);
        updateAccount(account, request.command().amount(), request.occurredAt());

        var availableLedgerAccountId = ensureLedgerAccount(account, "AVAILABLE", request.occurredAt());
        var reservedLedgerAccountId = ensureLedgerAccount(account, "RESERVED", request.occurredAt());
        insertLedgerTransaction(request, account, ledgerTransactionId);

        var entries = new ArrayList<LedgerEntry>();
        var entrySequence = 1;
        for (var allocation : allocations) {
            updateLot(allocation, request.occurredAt());
            insertAllocation(request.tenantId(), reservationId, allocation);
            entries.add(new LedgerEntry(
                    availableLedgerAccountId,
                    allocation.lot().id(),
                    LedgerDirection.CREDIT,
                    allocation.amount(),
                    entrySequence++
            ));
            entries.add(new LedgerEntry(
                    reservedLedgerAccountId,
                    allocation.lot().id(),
                    LedgerDirection.DEBIT,
                    allocation.amount(),
                    entrySequence++
            ));
        }
        insertLedgerEntries(request.tenantId(), account.ledgerScopeId(), ledgerTransactionId, entries, request.occurredAt());

        return new PointReservationResult(
                reservationId,
                account.id(),
                request.command().amount(),
                "ACTIVE",
                request.occurredAt(),
                false
        );
    }

    @Override
    public PointSettlementResult settle(SettlePointsRequest request) {
        var replay = findExistingSettlement(request);
        if (replay != null) {
            return replay;
        }

        var reservation = lockReservation(request);
        replay = findExistingSettlement(request);
        if (replay != null) {
            return replay;
        }
        if (!"ACTIVE".equals(reservation.status())) {
            throw new PointReservationConflictException("Point reservation is already settled");
        }
        if (request.command().capturedAmount() > reservation.amount()) {
            throw new PointReservationConflictException("Captured amount exceeds reservation");
        }

        var settlementId = UUID.randomUUID();
        var capturedAmount = request.command().capturedAmount();
        var releasedAmount = reservation.amount() - capturedAmount;
        var reservationStatus = capturedAmount == 0 ? "RELEASED" : "CAPTURED";
        insertSettlement(request, settlementId, capturedAmount, releasedAmount);

        var account = lockAccount(request.command().tenantId());
        if (!account.id().equals(reservation.accountId())) {
            throw new DataIntegrityViolationException("Point reservation account does not match tenant account");
        }
        var allocations = lockSettlementAllocations(request.command().tenantId(), reservation.reservationId());
        var allocatedTotal = allocations.stream().mapToLong(SettlementAllocation::amount).sum();
        if (allocatedTotal != reservation.amount()) {
            throw new DataIntegrityViolationException("Point reservation allocation does not match reservation amount");
        }

        var settlementPlan = PointSettlementAllocationPolicy.plan(
                allocations.stream()
                        .map(allocation -> new PointSettlementAllocationPolicy.LotAllocation(
                                allocation.lotId(),
                                allocation.amount(),
                                allocation.availableAmount(),
                                allocation.expiresAt(),
                                allocation.priority(),
                                allocation.status()
                        ))
                        .toList(),
                capturedAmount,
                request.occurredAt()
        );
        updateAccountForSettlement(account, settlementPlan, request.occurredAt());
        var reservedLedgerAccountId = ensureLedgerAccount(account, "RESERVED", request.occurredAt());
        var consumedLedgerAccountId = capturedAmount == 0
                ? null
                : ensureLedgerAccount(account, "CONSUMED", request.occurredAt());
        var availableLedgerAccountId = settlementPlan.releasedToAvailableAmount() == 0
                        && settlementPlan.existingAvailableExpiredAmount() == 0
                ? null
                : ensureLedgerAccount(account, "AVAILABLE", request.occurredAt());
        var expirationLedgerAccountId = settlementPlan.totalExpiredAmount() == 0
                ? null
                : ensureLedgerAccount(account, "EXPIRATION", request.occurredAt());

        UUID captureTransactionId = capturedAmount == 0 ? null : UUID.randomUUID();
        UUID releaseTransactionId = settlementPlan.releasedToAvailableAmount() == 0 ? null : UUID.randomUUID();
        UUID expirationTransactionId = settlementPlan.totalExpiredAmount() == 0 ? null : UUID.randomUUID();
        if (captureTransactionId != null) {
            insertSettlementLedgerTransaction(
                    request,
                    account,
                    reservation,
                    captureTransactionId,
                    "CAPTURE",
                    request.command().idempotencyKey() + ":capture"
            );
        }
        if (releaseTransactionId != null) {
            insertSettlementLedgerTransaction(
                    request,
                    account,
                    reservation,
                    releaseTransactionId,
                    "RELEASE",
                    request.command().idempotencyKey() + ":release"
            );
        }
        if (expirationTransactionId != null) {
            insertSettlementLedgerTransaction(
                    request,
                    account,
                    reservation,
                    expirationTransactionId,
                    "EXPIRE",
                    request.command().idempotencyKey() + ":expire"
            );
        }

        int captureSequence = 1;
        int releaseSequence = 1;
        int expirationSequence = 1;
        for (var allocation : settlementPlan.allocations()) {
            updateLotForSettlement(allocation, request.occurredAt());
            if (allocation.capturedAmount() > 0) {
                insertLedgerEntries(
                        request.command().tenantId(),
                        account.ledgerScopeId(),
                        captureTransactionId,
                        List.of(
                                new LedgerEntry(
                                        reservedLedgerAccountId,
                                        allocation.lotId(),
                                        LedgerDirection.CREDIT,
                                        allocation.capturedAmount(),
                                        captureSequence++
                                ),
                                new LedgerEntry(
                                        consumedLedgerAccountId,
                                        allocation.lotId(),
                                        LedgerDirection.DEBIT,
                                        allocation.capturedAmount(),
                                        captureSequence++
                                )
                        ),
                        request.occurredAt()
                );
            }
            if (allocation.releasedToAvailableAmount() > 0) {
                insertLedgerEntries(
                        request.command().tenantId(),
                        account.ledgerScopeId(),
                        releaseTransactionId,
                        List.of(
                                new LedgerEntry(
                                        reservedLedgerAccountId,
                                        allocation.lotId(),
                                        LedgerDirection.CREDIT,
                                        allocation.releasedToAvailableAmount(),
                                        releaseSequence++
                                ),
                                new LedgerEntry(
                                        availableLedgerAccountId,
                                        allocation.lotId(),
                                        LedgerDirection.DEBIT,
                                        allocation.releasedToAvailableAmount(),
                                        releaseSequence++
                                )
                        ),
                        request.occurredAt()
                );
            }
            if (allocation.existingAvailableExpiredAmount() > 0) {
                insertLedgerEntries(
                        request.command().tenantId(),
                        account.ledgerScopeId(),
                        expirationTransactionId,
                        List.of(
                                new LedgerEntry(
                                        availableLedgerAccountId,
                                        allocation.lotId(),
                                        LedgerDirection.CREDIT,
                                        allocation.existingAvailableExpiredAmount(),
                                        expirationSequence++
                                ),
                                new LedgerEntry(
                                        expirationLedgerAccountId,
                                        allocation.lotId(),
                                        LedgerDirection.DEBIT,
                                        allocation.existingAvailableExpiredAmount(),
                                        expirationSequence++
                                )
                        ),
                        request.occurredAt()
                );
            }
            if (allocation.releasedToExpirationAmount() > 0) {
                insertLedgerEntries(
                        request.command().tenantId(),
                        account.ledgerScopeId(),
                        expirationTransactionId,
                        List.of(
                                new LedgerEntry(
                                        reservedLedgerAccountId,
                                        allocation.lotId(),
                                        LedgerDirection.CREDIT,
                                        allocation.releasedToExpirationAmount(),
                                        expirationSequence++
                                ),
                                new LedgerEntry(
                                        expirationLedgerAccountId,
                                        allocation.lotId(),
                                        LedgerDirection.DEBIT,
                                        allocation.releasedToExpirationAmount(),
                                        expirationSequence++
                                )
                        ),
                        request.occurredAt()
                );
            }
        }
        updateReservationForSettlement(
                reservation.reservationId(),
                capturedAmount,
                releasedAmount,
                reservationStatus,
                request.occurredAt()
        );
        return new PointSettlementResult(
                settlementId,
                reservation.reservationId(),
                capturedAmount,
                releasedAmount,
                reservationStatus,
                request.occurredAt(),
                false
        );
    }

    private PointSettlementResult findExistingSettlement(SettlePointsRequest request) {
        var rows = jdbcTemplate.query(
                """
                SELECT settlement_id, reservation_id, captured_amount, released_amount,
                       reservation_status, request_hash, settled_at
                  FROM dianlian_business.point_reservation_settlement
                 WHERE tenant_id = ? AND idempotency_key = ?
                """,
                (resultSet, rowNumber) -> new ExistingSettlement(
                        resultSet.getObject("settlement_id", UUID.class),
                        resultSet.getObject("reservation_id", UUID.class),
                        resultSet.getLong("captured_amount"),
                        resultSet.getLong("released_amount"),
                        resultSet.getString("reservation_status"),
                        resultSet.getString("request_hash"),
                        resultSet.getTimestamp("settled_at").toInstant()
                ),
                request.command().tenantId(),
                request.command().idempotencyKey()
        );
        if (rows.isEmpty()) return null;
        var row = rows.getFirst();
        if (!row.reservationId().equals(request.command().reservationId())
                || row.capturedAmount() != request.command().capturedAmount()
                || !row.requestHash().equals(request.command().requestHash())) {
            throw new PointReservationConflictException(
                    "The settlement idempotency key was already used for another intent"
            );
        }
        return new PointSettlementResult(
                row.settlementId(),
                row.reservationId(),
                row.capturedAmount(),
                row.releasedAmount(),
                row.reservationStatus(),
                row.settledAt(),
                true
        );
    }

    private SettlementReservation lockReservation(SettlePointsRequest request) {
        var rows = jdbcTemplate.query(
                """
                SELECT reservation_id, account_id, amount, status, business_type, business_id
                  FROM dianlian_business.point_reservation
                 WHERE tenant_id = ? AND reservation_id = ?
                 FOR UPDATE
                """,
                (resultSet, rowNumber) -> new SettlementReservation(
                        resultSet.getObject("reservation_id", UUID.class),
                        resultSet.getObject("account_id", UUID.class),
                        resultSet.getLong("amount"),
                        resultSet.getString("status"),
                        resultSet.getString("business_type"),
                        resultSet.getObject("business_id", UUID.class)
                ),
                request.command().tenantId(),
                request.command().reservationId()
        );
        if (rows.isEmpty()) throw new PointReservationConflictException("Point reservation was not found");
        return rows.getFirst();
    }

    private List<SettlementAllocation> lockSettlementAllocations(UUID tenantId, UUID reservationId) {
        return jdbcTemplate.query(
                """
                SELECT allocation.lot_id, allocation.amount,
                       lot.available_amount_snapshot, lot.reserved_amount_snapshot,
                       lot.expires_at, lot.priority, lot.status
                  FROM dianlian_business.point_reservation_allocation allocation
                  JOIN dianlian_business.point_lot lot
                    ON lot.tenant_id = allocation.tenant_id AND lot.lot_id = allocation.lot_id
                 WHERE allocation.tenant_id = ? AND allocation.reservation_id = ?
                 ORDER BY lot.expires_at ASC NULLS LAST, lot.priority ASC, allocation.lot_id ASC
                 FOR UPDATE OF lot
                """,
                (resultSet, rowNumber) -> {
                    var expiresAt = resultSet.getTimestamp("expires_at");
                    return new SettlementAllocation(
                            resultSet.getObject("lot_id", UUID.class),
                            resultSet.getLong("amount"),
                            resultSet.getLong("available_amount_snapshot"),
                            resultSet.getLong("reserved_amount_snapshot"),
                            expiresAt == null ? null : expiresAt.toInstant(),
                            resultSet.getInt("priority"),
                            PointLotStatus.valueOf(resultSet.getString("status"))
                    );
                },
                tenantId,
                reservationId
        );
    }

    private void insertSettlement(
            SettlePointsRequest request,
            UUID settlementId,
            long capturedAmount,
            long releasedAmount
    ) {
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.point_reservation_settlement
                    (settlement_id, tenant_id, reservation_id, captured_amount, released_amount,
                     reservation_status, idempotency_key, request_hash, reason_code,
                     settled_by, settled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                settlementId,
                request.command().tenantId(),
                request.command().reservationId(),
                capturedAmount,
                releasedAmount,
                capturedAmount == 0 ? "RELEASED" : "CAPTURED",
                request.command().idempotencyKey(),
                request.command().requestHash(),
                request.command().reasonCode(),
                request.command().actorId(),
                Timestamp.from(request.occurredAt())
        );
    }

    private void updateAccountForSettlement(
            PointAccount account,
            PointSettlementAllocationPolicy.SettlementPlan settlementPlan,
            Instant occurredAt
    ) {
        var changed = jdbcTemplate.update(
                """
                UPDATE dianlian_business.point_account
                   SET available_amount_snapshot = available_amount_snapshot - ? + ?,
                       reserved_amount_snapshot = reserved_amount_snapshot - ?,
                       gross_captured_amount_snapshot = gross_captured_amount_snapshot + ?,
                       net_consumed_amount_snapshot = net_consumed_amount_snapshot + ?,
                       version = version + 1,
                       updated_at = ?
                 WHERE account_id = ? AND version = ?
                   AND available_amount_snapshot >= ?
                   AND reserved_amount_snapshot >= ?
                """,
                settlementPlan.existingAvailableExpiredAmount(),
                settlementPlan.releasedToAvailableAmount(),
                settlementPlan.reservedAmount(),
                settlementPlan.capturedAmount(),
                settlementPlan.capturedAmount(),
                Timestamp.from(occurredAt),
                account.id(),
                account.version(),
                settlementPlan.existingAvailableExpiredAmount(),
                settlementPlan.reservedAmount()
        );
        if (changed != 1) throw new DataIntegrityViolationException("Point account settlement failed");
    }

    private void updateLotForSettlement(
            PointSettlementAllocationPolicy.AllocationSettlement allocation,
            Instant occurredAt
    ) {
        int changed;
        if (allocation.expired()) {
            changed = jdbcTemplate.update(
                    """
                    UPDATE dianlian_business.point_lot
                       SET available_amount_snapshot = 0,
                           reserved_amount_snapshot = reserved_amount_snapshot - ?,
                           status = 'EXPIRED',
                           updated_at = ?
                     WHERE lot_id = ?
                       AND available_amount_snapshot = ?
                       AND reserved_amount_snapshot >= ?
                    """,
                    allocation.reservedAmount(),
                    Timestamp.from(occurredAt),
                    allocation.lotId(),
                    allocation.availableAmountBeforeSettlement(),
                    allocation.reservedAmount()
            );
        } else {
            changed = jdbcTemplate.update(
                    """
                    UPDATE dianlian_business.point_lot
                       SET available_amount_snapshot = available_amount_snapshot + ?,
                           reserved_amount_snapshot = reserved_amount_snapshot - ?,
                           status = CASE
                               WHEN available_amount_snapshot + ? > 0 THEN 'ACTIVE'
                               ELSE 'EXHAUSTED'
                           END,
                           updated_at = ?
                     WHERE lot_id = ?
                       AND available_amount_snapshot = ?
                       AND reserved_amount_snapshot >= ?
                    """,
                    allocation.releasedToAvailableAmount(),
                    allocation.reservedAmount(),
                    allocation.releasedToAvailableAmount(),
                    Timestamp.from(occurredAt),
                    allocation.lotId(),
                    allocation.availableAmountBeforeSettlement(),
                    allocation.reservedAmount()
            );
        }
        if (changed != 1) throw new DataIntegrityViolationException("Point lot settlement failed");
    }

    private void insertSettlementLedgerTransaction(
            SettlePointsRequest request,
            PointAccount account,
            SettlementReservation reservation,
            UUID transactionId,
            String transactionType,
            String idempotencyKey
    ) {
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.point_ledger_transaction
                    (transaction_id, tenant_id, ledger_scope_id, transaction_type,
                     idempotency_key, business_type, business_id, reason_code,
                     operator_id, status, created_at, posted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'POSTED', ?, ?)
                """,
                transactionId,
                request.command().tenantId(),
                account.ledgerScopeId(),
                transactionType,
                idempotencyKey,
                reservation.businessType(),
                reservation.businessId(),
                request.command().reasonCode(),
                request.command().actorId(),
                Timestamp.from(request.occurredAt()),
                Timestamp.from(request.occurredAt())
        );
    }

    private void updateReservationForSettlement(
            UUID reservationId,
            long capturedAmount,
            long releasedAmount,
            String status,
            Instant occurredAt
    ) {
        var changed = jdbcTemplate.update(
                """
                UPDATE dianlian_business.point_reservation
                   SET captured_amount = ?, released_amount = ?, status = ?, updated_at = ?
                 WHERE reservation_id = ? AND status = 'ACTIVE'
                """,
                capturedAmount,
                releasedAmount,
                status,
                Timestamp.from(occurredAt),
                reservationId
        );
        if (changed != 1) throw new PointReservationConflictException("Point reservation changed during settlement");
    }

    private PointReservationResult findExisting(ReservePointsRequest request) {
        var records = jdbcTemplate.query(
                """
                SELECT reservation_id, account_id, amount, status, business_type, business_id,
                       billing_scope_type, billing_scope_id, created_at
                  FROM dianlian_business.point_reservation
                 WHERE tenant_id = ? AND idempotency_key = ?
                """,
                (resultSet, rowNum) -> new ExistingReservation(
                        resultSet.getObject("reservation_id", UUID.class),
                        resultSet.getObject("account_id", UUID.class),
                        resultSet.getLong("amount"),
                        resultSet.getString("status"),
                        resultSet.getString("business_type"),
                        resultSet.getObject("business_id", UUID.class),
                        resultSet.getString("billing_scope_type"),
                        resultSet.getObject("billing_scope_id", UUID.class),
                        resultSet.getTimestamp("created_at").toInstant()
                ),
                request.tenantId(),
                request.command().idempotencyKey()
        );
        if (records.isEmpty()) {
            return null;
        }
        var record = records.getFirst();
        if (!record.matches(request)) {
            throw new PointReservationConflictException(
                    "The point reservation idempotency key was already used for another intent"
            );
        }
        return new PointReservationResult(
                record.reservationId(),
                record.accountId(),
                record.amount(),
                record.status(),
                record.createdAt(),
                true
        );
    }

    private PointAccount lockAccount(UUID tenantId) {
        var accounts = jdbcTemplate.query(
                """
                SELECT account_id, tenant_id, ledger_scope_id, status,
                       available_amount_snapshot, reserved_amount_snapshot, version
                  FROM dianlian_business.point_account
                 WHERE tenant_id = ? AND account_type = ?
                 FOR UPDATE
                """,
                this::mapAccount,
                tenantId,
                ACCOUNT_TYPE
        );
        if (accounts.isEmpty()) {
            throw new PointAccountUnavailableException("No point account exists for the current tenant");
        }
        return accounts.getFirst();
    }

    private List<PointLot> lockAvailableLots(UUID accountId, Instant occurredAt) {
        return jdbcTemplate.query(
                """
                SELECT lot_id, account_id, available_amount_snapshot, reserved_amount_snapshot,
                       expires_at, priority, status
                  FROM dianlian_business.point_lot
                 WHERE account_id = ?
                   AND status = 'ACTIVE'
                   AND available_amount_snapshot > 0
                   AND (expires_at IS NULL OR expires_at > ?)
                 ORDER BY expires_at ASC NULLS LAST, priority ASC, lot_id ASC
                 FOR UPDATE
                """,
                this::mapLot,
                accountId,
                Timestamp.from(occurredAt)
        );
    }

    private List<LotAllocation> allocate(List<PointLot> lots, long requestedAmount) {
        var remaining = requestedAmount;
        var allocations = new ArrayList<LotAllocation>();
        for (var lot : lots) {
            if (remaining == 0) {
                break;
            }
            var amount = Math.min(remaining, lot.availableAmount());
            allocations.add(new LotAllocation(lot, amount));
            remaining -= amount;
        }
        if (remaining != 0) {
            throw new DataIntegrityViolationException(
                    "Point account snapshot does not match the sum of active point lots"
            );
        }
        return List.copyOf(allocations);
    }

    private void insertReservation(
            ReservePointsRequest request,
            PointAccount account,
            UUID reservationId,
            UUID ledgerTransactionId
    ) {
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.point_reservation
                    (reservation_id, tenant_id, account_id, business_type, business_id,
                     billing_scope_type, billing_scope_id, amount, status, idempotency_key,
                     reserve_ledger_transaction_id, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?)
                """,
                reservationId,
                request.tenantId(),
                account.id(),
                request.command().businessType(),
                request.command().businessId(),
                request.command().billingScopeType(),
                request.command().billingScopeId(),
                request.command().amount(),
                request.command().idempotencyKey(),
                ledgerTransactionId,
                request.actorId(),
                Timestamp.from(request.occurredAt()),
                Timestamp.from(request.occurredAt())
        );
    }

    private void updateAccount(PointAccount account, long amount, Instant occurredAt) {
        var changed = jdbcTemplate.update(
                """
                UPDATE dianlian_business.point_account
                   SET available_amount_snapshot = available_amount_snapshot - ?,
                       reserved_amount_snapshot = reserved_amount_snapshot + ?,
                       version = version + 1,
                       updated_at = ?
                 WHERE account_id = ? AND version = ? AND available_amount_snapshot >= ?
                """,
                amount,
                amount,
                Timestamp.from(occurredAt),
                account.id(),
                account.version(),
                amount
        );
        if (changed != 1) {
            throw new DataIntegrityViolationException("Point account changed while it was locked");
        }
    }

    private void updateLot(LotAllocation allocation, Instant occurredAt) {
        var changed = jdbcTemplate.update(
                """
                UPDATE dianlian_business.point_lot
                   SET available_amount_snapshot = available_amount_snapshot - ?,
                       reserved_amount_snapshot = reserved_amount_snapshot + ?,
                       status = CASE WHEN available_amount_snapshot - ? = 0 THEN 'EXHAUSTED' ELSE status END,
                       updated_at = ?
                 WHERE lot_id = ? AND available_amount_snapshot >= ?
                """,
                allocation.amount(),
                allocation.amount(),
                allocation.amount(),
                Timestamp.from(occurredAt),
                allocation.lot().id(),
                allocation.amount()
        );
        if (changed != 1) {
            throw new DataIntegrityViolationException("Point lot changed while it was locked");
        }
    }

    private void insertAllocation(UUID tenantId, UUID reservationId, LotAllocation allocation) {
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.point_reservation_allocation
                    (tenant_id, reservation_id, lot_id, amount)
                VALUES (?, ?, ?, ?)
                """,
                tenantId,
                reservationId,
                allocation.lot().id(),
                allocation.amount()
        );
    }

    private UUID ensureLedgerAccount(PointAccount account, String bucketCode, Instant occurredAt) {
        var ledgerAccountId = UUID.randomUUID();
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.point_ledger_account
                    (ledger_account_id, tenant_id, ledger_scope_id, owner_type, owner_id,
                     bucket_code, unit_code, status, created_at)
                VALUES (?, ?, ?, 'TENANT', ?, ?, ?, 'ACTIVE', ?)
                ON CONFLICT (tenant_id, ledger_scope_id, bucket_code) DO NOTHING
                """,
                ledgerAccountId,
                account.tenantId(),
                account.ledgerScopeId(),
                account.tenantId(),
                bucketCode,
                UNIT_CODE,
                Timestamp.from(occurredAt)
        );
        return jdbcTemplate.queryForObject(
                """
                SELECT ledger_account_id
                  FROM dianlian_business.point_ledger_account
                 WHERE tenant_id = ? AND ledger_scope_id = ? AND bucket_code = ?
                """,
                UUID.class,
                account.tenantId(),
                account.ledgerScopeId(),
                bucketCode
        );
    }

    private void insertLedgerTransaction(
            ReservePointsRequest request,
            PointAccount account,
            UUID transactionId
    ) {
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.point_ledger_transaction
                    (transaction_id, tenant_id, ledger_scope_id, transaction_type,
                     idempotency_key, business_type, business_id, reason_code,
                     operator_id, status, created_at, posted_at)
                VALUES (?, ?, ?, 'RESERVE', ?, ?, ?, 'RESERVATION_ADMISSION', ?, 'POSTED', ?, ?)
                """,
                transactionId,
                request.tenantId(),
                account.ledgerScopeId(),
                request.command().idempotencyKey(),
                request.command().businessType(),
                request.command().businessId(),
                request.actorId(),
                Timestamp.from(request.occurredAt()),
                Timestamp.from(request.occurredAt())
        );
    }

    private void insertLedgerEntries(
            UUID tenantId,
            UUID ledgerScopeId,
            UUID transactionId,
            List<LedgerEntry> entries,
            Instant occurredAt
    ) {
        for (var entry : entries) {
            jdbcTemplate.update(
                    """
                    INSERT INTO dianlian_business.point_ledger_entry
                        (entry_id, tenant_id, ledger_scope_id, transaction_id, ledger_account_id,
                         unit_code, direction, amount, point_lot_id, sequence_no, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    UUID.randomUUID(),
                    tenantId,
                    ledgerScopeId,
                    transactionId,
                    entry.ledgerAccountId(),
                    UNIT_CODE,
                    entry.direction().name(),
                    entry.amount(),
                    entry.pointLotId(),
                    entry.sequence(),
                    Timestamp.from(occurredAt)
            );
        }
    }

    private PointAccount mapAccount(ResultSet resultSet, int rowNum) throws SQLException {
        return new PointAccount(
                resultSet.getObject("account_id", UUID.class),
                resultSet.getObject("tenant_id", UUID.class),
                resultSet.getObject("ledger_scope_id", UUID.class),
                PointAccountStatus.valueOf(resultSet.getString("status")),
                resultSet.getLong("available_amount_snapshot"),
                resultSet.getLong("reserved_amount_snapshot"),
                resultSet.getLong("version")
        );
    }

    private PointLot mapLot(ResultSet resultSet, int rowNum) throws SQLException {
        var expiresAt = resultSet.getTimestamp("expires_at");
        return new PointLot(
                resultSet.getObject("lot_id", UUID.class),
                resultSet.getObject("account_id", UUID.class),
                resultSet.getLong("available_amount_snapshot"),
                resultSet.getLong("reserved_amount_snapshot"),
                expiresAt == null ? null : expiresAt.toInstant(),
                resultSet.getInt("priority"),
                PointLotStatus.valueOf(resultSet.getString("status"))
        );
    }

    private record LotAllocation(PointLot lot, long amount) {
    }

    private record ExistingReservation(
            UUID reservationId,
            UUID accountId,
            long amount,
            String status,
            String businessType,
            UUID businessId,
            String billingScopeType,
            UUID billingScopeId,
            Instant createdAt
    ) {

        boolean matches(ReservePointsRequest request) {
            return amount == request.command().amount()
                    && businessType.equals(request.command().businessType())
                    && businessId.equals(request.command().businessId())
                    && billingScopeType.equals(request.command().billingScopeType())
                    && billingScopeId.equals(request.command().billingScopeId());
        }
    }

    private record SettlementReservation(
            UUID reservationId,
            UUID accountId,
            long amount,
            String status,
            String businessType,
            UUID businessId
    ) {
    }

    private record SettlementAllocation(
            UUID lotId,
            long amount,
            long availableAmount,
            long reservedAmount,
            Instant expiresAt,
            int priority,
            PointLotStatus status
    ) {
    }

    private record ExistingSettlement(
            UUID settlementId,
            UUID reservationId,
            long capturedAmount,
            long releasedAmount,
            String reservationStatus,
            String requestHash,
            Instant settledAt
    ) {
    }
}

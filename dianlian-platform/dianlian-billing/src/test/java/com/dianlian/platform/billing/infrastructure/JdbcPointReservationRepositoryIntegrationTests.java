package com.dianlian.platform.billing.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import com.dianlian.platform.billing.api.SettlePointsCommand;
import com.dianlian.platform.billing.application.SettlePointsRequest;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.UUID;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.postgresql.ds.PGSimpleDataSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

class JdbcPointReservationRepositoryIntegrationTests {

    private static final Instant NOW = Instant.parse("2026-08-11T08:00:00Z");

    @Test
    void settlesAcrossExpiryWithoutRestoringExpiredPointsAndKeepsLedgerBalanced() {
        String jdbcUrl = System.getProperty("dianlian.billing.jdbc.url", "");
        Assumptions.assumeTrue(!jdbcUrl.isBlank(), "PostgreSQL integration URL was not supplied");

        var dataSource = new PGSimpleDataSource();
        dataSource.setURL(jdbcUrl);
        dataSource.setUser(System.getProperty("dianlian.billing.jdbc.user", "dianlian_app"));
        dataSource.setPassword(System.getProperty("dianlian.billing.jdbc.password", ""));
        var jdbcTemplate = new JdbcTemplate(dataSource);
        var transactionTemplate = new TransactionTemplate(new DataSourceTransactionManager(dataSource));

        transactionTemplate.executeWithoutResult(status -> {
            var tenantId = UUID.randomUUID();
            var actorId = UUID.randomUUID();
            var accountId = UUID.randomUUID();
            var ledgerScopeId = UUID.randomUUID();
            var expiredLotId = UUID.randomUUID();
            var validLotId = UUID.randomUUID();
            var reservationId = UUID.randomUUID();
            var businessId = UUID.randomUUID();
            var availableLedgerAccountId = UUID.randomUUID();
            var reservedLedgerAccountId = UUID.randomUUID();
            var reserveTransactionId = UUID.randomUUID();

            insertIdentity(jdbcTemplate, tenantId, actorId);
            insertAccountAndLots(
                    jdbcTemplate,
                    tenantId,
                    accountId,
                    ledgerScopeId,
                    expiredLotId,
                    validLotId
            );
            insertReservationAndReserveLedger(
                    jdbcTemplate,
                    tenantId,
                    actorId,
                    accountId,
                    ledgerScopeId,
                    expiredLotId,
                    validLotId,
                    reservationId,
                    businessId,
                    availableLedgerAccountId,
                    reservedLedgerAccountId,
                    reserveTransactionId
            );

            var repository = new JdbcPointReservationRepository(jdbcTemplate);
            var request = new SettlePointsRequest(
                    new SettlePointsCommand(
                            tenantId,
                            actorId,
                            reservationId,
                            50,
                            "settle-" + reservationId,
                            "sha256:settle-" + reservationId,
                            "MODEL_USAGE"
                    ),
                    NOW
            );

            var settled = repository.settle(request);
            var replay = repository.settle(request);

            assertThat(settled.capturedAmount()).isEqualTo(50);
            assertThat(settled.releasedAmount()).isEqualTo(50);
            assertThat(settled.replayed()).isFalse();
            assertThat(replay.replayed()).isTrue();
            assertThat(replay.settlementId()).isEqualTo(settled.settlementId());
            assertAccount(jdbcTemplate, accountId);
            assertLot(jdbcTemplate, expiredLotId, 0, 0, "EXPIRED");
            assertLot(jdbcTemplate, validLotId, 40, 0, "ACTIVE");
            assertLedgerTransaction(jdbcTemplate, tenantId, ledgerScopeId, "CAPTURE", 50);
            assertLedgerTransaction(jdbcTemplate, tenantId, ledgerScopeId, "RELEASE", 20);
            assertLedgerTransaction(jdbcTemplate, tenantId, ledgerScopeId, "EXPIRE", 40);
            assertThat(jdbcTemplate.queryForObject(
                    """
                    SELECT COUNT(*)
                      FROM dianlian_business.point_ledger_transaction
                     WHERE tenant_id = ?
                       AND transaction_type IN ('CAPTURE', 'RELEASE', 'EXPIRE')
                       AND business_type = 'TASK'
                       AND business_id = ?
                    """,
                    Long.class,
                    tenantId,
                    businessId
            )).isEqualTo(3);
            assertThat(jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM dianlian_business.point_reservation_settlement WHERE reservation_id = ?",
                    Long.class,
                    reservationId
            )).isEqualTo(1);
            assertThat(jdbcTemplate.queryForObject(
                    "SELECT COUNT(*) FROM dianlian_business.point_ledger_transaction WHERE tenant_id = ?",
                    Long.class,
                    tenantId
            )).isEqualTo(4);

            jdbcTemplate.execute("SET CONSTRAINTS ALL IMMEDIATE");
            status.setRollbackOnly();
        });
    }

    private void insertIdentity(JdbcTemplate jdbcTemplate, UUID tenantId, UUID actorId) {
        jdbcTemplate.update(
                "INSERT INTO dianlian_business.tenant (tenant_id, display_name, status) VALUES (?, ?, 'ACTIVE')",
                tenantId,
                "Billing integration tenant"
        );
        jdbcTemplate.update(
                "INSERT INTO dianlian_business.user_account (user_id, display_name, status) VALUES (?, ?, 'ACTIVE')",
                actorId,
                "Billing integration actor"
        );
    }

    private void insertAccountAndLots(
            JdbcTemplate jdbcTemplate,
            UUID tenantId,
            UUID accountId,
            UUID ledgerScopeId,
            UUID expiredLotId,
            UUID validLotId
    ) {
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.point_account
                    (account_id, tenant_id, ledger_scope_id, account_type, unit_code, status,
                     available_amount_snapshot, reserved_amount_snapshot)
                VALUES (?, ?, ?, 'MAIN', 'POINT', 'ACTIVE', 30, 100)
                """,
                accountId,
                tenantId,
                ledgerScopeId
        );
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.point_lot
                    (lot_id, tenant_id, account_id, source_type, source_id, total_amount,
                     available_amount_snapshot, reserved_amount_snapshot, expires_at, priority, status)
                VALUES (?, ?, ?, 'GRANT', ?, 90, 10, 80, ?, 10, 'ACTIVE')
                """,
                expiredLotId,
                tenantId,
                accountId,
                "expired-" + expiredLotId,
                Timestamp.from(NOW.minus(1, ChronoUnit.DAYS))
        );
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.point_lot
                    (lot_id, tenant_id, account_id, source_type, source_id, total_amount,
                     available_amount_snapshot, reserved_amount_snapshot, expires_at, priority, status)
                VALUES (?, ?, ?, 'GRANT', ?, 40, 20, 20, ?, 20, 'ACTIVE')
                """,
                validLotId,
                tenantId,
                accountId,
                "valid-" + validLotId,
                Timestamp.from(NOW.plus(1, ChronoUnit.DAYS))
        );
    }

    private void insertReservationAndReserveLedger(
            JdbcTemplate jdbcTemplate,
            UUID tenantId,
            UUID actorId,
            UUID accountId,
            UUID ledgerScopeId,
            UUID expiredLotId,
            UUID validLotId,
            UUID reservationId,
            UUID businessId,
            UUID availableLedgerAccountId,
            UUID reservedLedgerAccountId,
            UUID reserveTransactionId
    ) {
        insertLedgerAccount(
                jdbcTemplate,
                availableLedgerAccountId,
                tenantId,
                ledgerScopeId,
                "AVAILABLE"
        );
        insertLedgerAccount(
                jdbcTemplate,
                reservedLedgerAccountId,
                tenantId,
                ledgerScopeId,
                "RESERVED"
        );
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.point_ledger_transaction
                    (transaction_id, tenant_id, ledger_scope_id, transaction_type, idempotency_key,
                     business_type, business_id, reason_code, operator_id, status, created_at, posted_at)
                VALUES (?, ?, ?, 'RESERVE', ?, 'TASK', ?, 'RESERVATION_ADMISSION', ?, 'POSTED', ?, ?)
                """,
                reserveTransactionId,
                tenantId,
                ledgerScopeId,
                "reserve-" + reservationId,
                businessId,
                actorId,
                Timestamp.from(NOW.minus(2, ChronoUnit.DAYS)),
                Timestamp.from(NOW.minus(2, ChronoUnit.DAYS))
        );
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.point_reservation
                    (reservation_id, tenant_id, account_id, business_type, business_id,
                     billing_scope_type, billing_scope_id, amount, status, idempotency_key,
                     reserve_ledger_transaction_id, created_by, created_at, updated_at)
                VALUES (?, ?, ?, 'TASK', ?, 'TENANT', ?, 100, 'ACTIVE', ?, ?, ?, ?, ?)
                """,
                reservationId,
                tenantId,
                accountId,
                businessId,
                tenantId,
                "reserve-" + reservationId,
                reserveTransactionId,
                actorId,
                Timestamp.from(NOW.minus(2, ChronoUnit.DAYS)),
                Timestamp.from(NOW.minus(2, ChronoUnit.DAYS))
        );
        jdbcTemplate.update(
                "INSERT INTO dianlian_business.point_reservation_allocation VALUES (?, ?, ?, 80)",
                tenantId,
                reservationId,
                expiredLotId
        );
        jdbcTemplate.update(
                "INSERT INTO dianlian_business.point_reservation_allocation VALUES (?, ?, ?, 20)",
                tenantId,
                reservationId,
                validLotId
        );
        insertLedgerEntry(
                jdbcTemplate,
                tenantId,
                ledgerScopeId,
                reserveTransactionId,
                availableLedgerAccountId,
                expiredLotId,
                "CREDIT",
                80,
                1
        );
        insertLedgerEntry(
                jdbcTemplate,
                tenantId,
                ledgerScopeId,
                reserveTransactionId,
                reservedLedgerAccountId,
                expiredLotId,
                "DEBIT",
                80,
                2
        );
        insertLedgerEntry(
                jdbcTemplate,
                tenantId,
                ledgerScopeId,
                reserveTransactionId,
                availableLedgerAccountId,
                validLotId,
                "CREDIT",
                20,
                3
        );
        insertLedgerEntry(
                jdbcTemplate,
                tenantId,
                ledgerScopeId,
                reserveTransactionId,
                reservedLedgerAccountId,
                validLotId,
                "DEBIT",
                20,
                4
        );
    }

    private void insertLedgerAccount(
            JdbcTemplate jdbcTemplate,
            UUID ledgerAccountId,
            UUID tenantId,
            UUID ledgerScopeId,
            String bucketCode
    ) {
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.point_ledger_account
                    (ledger_account_id, tenant_id, ledger_scope_id, owner_type, owner_id,
                     bucket_code, unit_code, status)
                VALUES (?, ?, ?, 'TENANT', ?, ?, 'POINT', 'ACTIVE')
                """,
                ledgerAccountId,
                tenantId,
                ledgerScopeId,
                tenantId,
                bucketCode
        );
    }

    private void insertLedgerEntry(
            JdbcTemplate jdbcTemplate,
            UUID tenantId,
            UUID ledgerScopeId,
            UUID transactionId,
            UUID ledgerAccountId,
            UUID lotId,
            String direction,
            long amount,
            int sequence
    ) {
        jdbcTemplate.update(
                """
                INSERT INTO dianlian_business.point_ledger_entry
                    (entry_id, tenant_id, ledger_scope_id, transaction_id, ledger_account_id,
                     unit_code, direction, amount, point_lot_id, sequence_no, created_at)
                VALUES (?, ?, ?, ?, ?, 'POINT', ?, ?, ?, ?, ?)
                """,
                UUID.randomUUID(),
                tenantId,
                ledgerScopeId,
                transactionId,
                ledgerAccountId,
                direction,
                amount,
                lotId,
                sequence,
                Timestamp.from(NOW.minus(2, ChronoUnit.DAYS))
        );
    }

    private void assertAccount(JdbcTemplate jdbcTemplate, UUID accountId) {
        var row = jdbcTemplate.queryForMap(
                """
                SELECT available_amount_snapshot, reserved_amount_snapshot,
                       gross_captured_amount_snapshot, net_consumed_amount_snapshot
                  FROM dianlian_business.point_account
                 WHERE account_id = ?
                """,
                accountId
        );
        assertThat(((Number) row.get("available_amount_snapshot")).longValue()).isEqualTo(40);
        assertThat(((Number) row.get("reserved_amount_snapshot")).longValue()).isZero();
        assertThat(((Number) row.get("gross_captured_amount_snapshot")).longValue()).isEqualTo(50);
        assertThat(((Number) row.get("net_consumed_amount_snapshot")).longValue()).isEqualTo(50);
    }

    private void assertLot(
            JdbcTemplate jdbcTemplate,
            UUID lotId,
            long availableAmount,
            long reservedAmount,
            String status
    ) {
        var row = jdbcTemplate.queryForMap(
                """
                SELECT available_amount_snapshot, reserved_amount_snapshot, status
                  FROM dianlian_business.point_lot
                 WHERE lot_id = ?
                """,
                lotId
        );
        assertThat(((Number) row.get("available_amount_snapshot")).longValue()).isEqualTo(availableAmount);
        assertThat(((Number) row.get("reserved_amount_snapshot")).longValue()).isEqualTo(reservedAmount);
        assertThat(row.get("status")).isEqualTo(status);
    }

    private void assertLedgerTransaction(
            JdbcTemplate jdbcTemplate,
            UUID tenantId,
            UUID ledgerScopeId,
            String transactionType,
            long expectedAmount
    ) {
        var row = jdbcTemplate.queryForMap(
                """
                SELECT COALESCE(SUM(CASE WHEN entry.direction = 'DEBIT' THEN entry.amount ELSE 0 END), 0) AS debit,
                       COALESCE(SUM(CASE WHEN entry.direction = 'CREDIT' THEN entry.amount ELSE 0 END), 0) AS credit
                  FROM dianlian_business.point_ledger_transaction ledger_transaction
                  JOIN dianlian_business.point_ledger_entry entry
                    ON entry.transaction_id = ledger_transaction.transaction_id
                 WHERE ledger_transaction.tenant_id = ?
                   AND ledger_transaction.ledger_scope_id = ?
                   AND ledger_transaction.transaction_type = ?
                """,
                tenantId,
                ledgerScopeId,
                transactionType
        );
        assertThat(((Number) row.get("debit")).longValue()).isEqualTo(expectedAmount);
        assertThat(((Number) row.get("credit")).longValue()).isEqualTo(expectedAmount);
    }
}

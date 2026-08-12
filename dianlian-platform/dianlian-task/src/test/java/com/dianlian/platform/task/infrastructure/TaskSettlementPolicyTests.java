package com.dianlian.platform.task.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class TaskSettlementPolicyTests {

    @Test
    void settlesOnlyTerminalTaskStatuses() {
        assertThat(JdbcTaskExecutionRepository.settlementAllowed("SUCCEEDED")).isTrue();
        assertThat(JdbcTaskExecutionRepository.settlementAllowed("PARTIAL_SUCCESS")).isTrue();
        assertThat(JdbcTaskExecutionRepository.settlementAllowed("FAILED")).isTrue();
        assertThat(JdbcTaskExecutionRepository.settlementAllowed("CANCELLED")).isTrue();

        assertThat(JdbcTaskExecutionRepository.settlementAllowed("WAITING_CONFIRMATION")).isFalse();
        assertThat(JdbcTaskExecutionRepository.settlementAllowed("PAUSED")).isFalse();
        assertThat(JdbcTaskExecutionRepository.settlementAllowed("RUNNING")).isFalse();
    }
}

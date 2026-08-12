package com.dianlian.platform.context.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;

import java.lang.reflect.Modifier;
import org.junit.jupiter.api.Test;

class JdbcContextIndexDispatchRepositoryTests {

    @Test
    void repositoryRemainsProxyableForSpringExceptionTranslation() {
        assertThat(Modifier.isFinal(JdbcContextIndexDispatchRepository.class.getModifiers()))
                .as("@Repository beans must support Spring class-based proxies")
                .isFalse();
    }

    @Test
    void claimSqlUsesBoundedPostgresSkipLockedAndLeaseEpochFencing() {
        assertThat(JdbcContextIndexDispatchRepository.CLAIM_SQL)
                .contains("index_target = :indexTarget")
                .contains("index_profile_version = :indexProfileVersion")
                .contains("attempt_count < :maxAttempts")
                .contains("status = 'RUNNING' AND lease_expires_at <= :now")
                .contains("FOR UPDATE SKIP LOCKED")
                .contains("lease_epoch = job.lease_epoch + 1")
                .contains("index_profile_version")
                .contains("CASE operation WHEN 'DELETE' THEN 0 ELSE 1 END");
    }

    @Test
    void authorityQueriesReadCurrentParentStateAndTheRequestedMemoryVersion() {
        assertThat(JdbcContextIndexDispatchRepository.KNOWLEDGE_AUTHORITY_SQL)
                .contains("document.current_version_id")
                .contains("space.owner_scope = :authorityScope")
                .contains("version.tenant_id IS NOT DISTINCT FROM CAST(:tenantId AS UUID)")
                .contains("version.status AS version_status")
                .contains("version.access_state")
                .contains("version.normalized_text_hash")
                .contains("version.normalization_profile_version")
                .contains("GREATEST(version.event_sequence, document.event_sequence, space.event_sequence)");
        assertThat(JdbcContextIndexDispatchRepository.MEMORY_AUTHORITY_SQL)
                .contains("item.current_version")
                .contains("item.tenant_id = :tenantId")
                .contains("item.status AS item_status")
                .contains("requested.version_no = :requestedVersion")
                .contains("LEFT JOIN dianlian_business.ai_memory_version origin")
                .contains("COALESCE(requested.source_candidate_id, origin.source_candidate_id)")
                .contains("source_message.sequence_no AS source_message_sequence_no");
    }
}

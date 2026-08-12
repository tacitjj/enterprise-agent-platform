-- Keep capability-specific workers on their declared projection target and profile.
-- The V11/V12 dispatch indexes remain in place because the global exhausted-job cleanup
-- intentionally has no target/profile predicate.

CREATE INDEX idx_context_index_job_ready_capability_dispatch
    ON dianlian_business.context_index_job
        (index_target, index_profile_version, next_attempt_at, event_sequence, job_id)
    INCLUDE (operation, attempt_count)
    WHERE status IN ('PENDING', 'FAILED');

CREATE INDEX idx_context_index_job_expired_capability_dispatch
    ON dianlian_business.context_index_job
        (index_target, index_profile_version, lease_expires_at, event_sequence, job_id)
    INCLUDE (operation, attempt_count)
    WHERE status = 'RUNNING';

COMMENT ON INDEX dianlian_business.idx_context_index_job_ready_capability_dispatch IS
    'Finds ready projection jobs for one worker target/profile without scanning unrelated capabilities.';
COMMENT ON INDEX dianlian_business.idx_context_index_job_expired_capability_dispatch IS
    'Finds expired running projection jobs for takeover by a worker with the same target/profile.';

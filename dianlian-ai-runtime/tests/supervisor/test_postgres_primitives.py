from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from queue import Queue
from threading import Barrier
from time import monotonic, sleep
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
import pytest


TEST_DSN = os.getenv("DIANLIAN_TEST_SUPERVISOR_DATABASE_DSN")
pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="DIANLIAN_TEST_SUPERVISOR_DATABASE_DSN is not configured",
)


ADMIT_RUNTIME_RUN_SQL = """
    SELECT runtime_run_id, runtime_thread_id, status, run_version,
           next_event_sequence_no, lease_epoch, attempt
      FROM deer_runtime.admit_runtime_run(
          %s::UUID, %s::UUID, %s::UUID, %s::UUID,
          %s::UUID, %s::UUID, %s::VARCHAR, %s::UUID, %s::UUID,
          %s::BIGINT, %s::VARCHAR, %s::VARCHAR,
          %s::UUID, %s::UUID, %s::UUID, %s::UUID, %s::JSONB,
          %s::UUID, %s::BIGINT, %s::VARCHAR, %s::VARCHAR,
          %s::CHAR(64), %s::VARCHAR, %s::UUID, %s::VARCHAR,
          %s::VARCHAR, %s::VARCHAR,
          %s::VARCHAR, %s::UUID, %s::CHAR(64),
          %s::UUID, %s::JSONB
      )
"""

ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL = """
    SELECT *
      FROM deer_runtime.issue_runtime_external_permit(
          %s::UUID, %s::UUID, %s::VARCHAR, %s::BIGINT, %s::UUID,
          %s::VARCHAR, %s::UUID, %s::CHAR(64), %s::INTEGER, %s::UUID
      )
"""

CONSUME_RUNTIME_EXTERNAL_PERMIT_SQL = """
    SELECT *
      FROM deer_runtime.consume_runtime_external_permit(
          %s::UUID, %s::UUID, %s::UUID, %s::BIGINT,
          %s::VARCHAR, %s::BIGINT, %s::UUID, %s::CHAR(64),
          %s::VARCHAR, %s::UUID, %s::CHAR(64), %s::UUID, %s::VARCHAR
      )
"""

CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL = """
    SELECT *
      FROM deer_runtime.consume_and_authorize_runtime_external_permit(
          %s::UUID, %s::UUID, %s::UUID, %s::BIGINT,
          %s::VARCHAR, %s::BIGINT, %s::UUID, %s::CHAR(64),
          %s::VARCHAR, %s::UUID, %s::CHAR(64), %s::UUID, %s::VARCHAR
      )
"""

CONSUME_AND_ARM_RUNTIME_EXTERNAL_DISPATCH_SQL = """
    SELECT *
      FROM deer_runtime.consume_and_arm_runtime_external_dispatch(
          %s::UUID, %s::UUID, %s::UUID, %s::BIGINT,
          %s::VARCHAR, %s::BIGINT, %s::UUID, %s::CHAR(64),
          %s::VARCHAR, %s::UUID, %s::CHAR(64), %s::UUID, %s::VARCHAR
      )
"""

RECORD_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL = """
    SELECT *
      FROM deer_runtime.record_runtime_external_operation_outcome(
          %s::UUID, %s::UUID, %s::UUID, %s::BIGINT,
          %s::VARCHAR, %s::BIGINT, %s::UUID, %s::CHAR(64),
          %s::VARCHAR, %s::UUID, %s::CHAR(64), %s::UUID,
          %s::VARCHAR, %s::UUID, %s::BIGINT, %s::CHAR(64),
          %s::VARCHAR, %s::VARCHAR, %s::CHAR(64), %s::VARCHAR
      )
"""

RECONCILE_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL = """
    SELECT *
      FROM deer_runtime.reconcile_runtime_external_operation_outcome(
          %s::UUID, %s::UUID, %s::UUID, %s::BIGINT,
          %s::VARCHAR, %s::BIGINT, %s::UUID, %s::CHAR(64),
          %s::VARCHAR, %s::UUID, %s::CHAR(64), %s::UUID, %s::UUID,
          %s::VARCHAR, %s::UUID, %s::BIGINT, %s::CHAR(64),
          %s::VARCHAR, %s::VARCHAR, %s::CHAR(64), %s::VARCHAR
      )
"""


def _arm_parameters(
    tenant_id: UUID,
    runtime_run_id: UUID,
    binding: dict[str, Any],
    permit_id: UUID,
    intent_id: UUID,
    request_hash: str,
    arm_event_id: UUID,
    *,
    lease_owner: str = "worker-a",
    lease_epoch: int = 1,
) -> tuple[Any, ...]:
    return (
        tenant_id,
        permit_id,
        runtime_run_id,
        binding["task_execution_generation"],
        lease_owner,
        lease_epoch,
        binding["admission_snapshot_id"],
        binding["admission_snapshot_hash"],
        "MODEL_INVOKE",
        intent_id,
        request_hash,
        arm_event_id,
        "java-runtime",
    )


def _admission_parameters(
    *,
    tenant_id: UUID | None = None,
    runtime_thread_id: UUID | None = None,
    task_run_id: UUID | None = None,
    task_step_id: UUID | None = None,
    runtime_thread_revision: int = 1,
    runtime_run_id: UUID | None = None,
    task_execution_generation: int = 1,
    request_hash: str = "a" * 64,
    idempotency_key: str | None = None,
    admission_contract_version: str = "2.2",
    admission_snapshot_id: UUID | None = None,
    admission_snapshot_hash: str = "f" * 64,
    runtime_version: str = "adapter-s0",
    agent_name: str = "concurrency-test",
    accepted_event_id: UUID | None = None,
) -> tuple[Any, ...]:
    admitted_run_id = runtime_run_id or uuid4()
    return (
        tenant_id or uuid4(),
        runtime_thread_id or uuid4(),
        task_run_id or uuid4(),
        task_step_id or uuid4(),
        uuid4(),
        uuid4(),
        "CONVERSATION",
        uuid4(),
        None,
        runtime_thread_revision,
        "DEERFLOW",
        "concurrency-test",
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        "[]",
        admitted_run_id,
        task_execution_generation,
        "START",
        "REJECT",
        request_hash,
        idempotency_key or f"admit-{admitted_run_id}",
        None,
        None,
        runtime_version,
        agent_name,
        admission_contract_version,
        admission_snapshot_id or uuid4(),
        admission_snapshot_hash,
        accepted_event_id or uuid4(),
        '{"schemaVersion":"runtime-run-accepted-v2","source":"postgres-test"}',
    )


def _seed_claimed_run() -> tuple[UUID, UUID]:
    assert TEST_DSN is not None
    tenant_id = uuid4()
    runtime_thread_id = uuid4()
    task_step_id = uuid4()
    runtime_run_id = uuid4()
    admission_parameters = _admission_parameters(
        tenant_id=tenant_id,
        runtime_thread_id=runtime_thread_id,
        task_step_id=task_step_id,
        runtime_run_id=runtime_run_id,
    )
    with psycopg.connect(TEST_DSN) as connection:
        admitted = connection.execute(
            ADMIT_RUNTIME_RUN_SQL,
            admission_parameters,
        ).fetchone()
        assert admitted == (runtime_run_id, runtime_thread_id, "QUEUED", 1, 2, 0, 0)
        claimed = connection.execute(
            """
            SELECT runtime_run_id, lease_owner, lease_epoch, run_version
              FROM deer_runtime.claim_runtime_run(
                  %s, %s, 'worker-a', 60, %s, '{"test":"claim"}'::JSONB
              )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone()
        assert claimed == (runtime_run_id, "worker-a", 1, 2)
    return tenant_id, runtime_run_id


def _runtime_permit_binding(
    tenant_id: UUID,
    runtime_run_id: UUID,
) -> dict[str, Any]:
    assert TEST_DSN is not None
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        binding = connection.execute(
            """
            SELECT runtime_run.task_execution_generation,
                   admission_ref.admission_snapshot_id,
                   admission_ref.admission_snapshot_hash
              FROM deer_runtime.runtime_run AS runtime_run
              JOIN deer_runtime.runtime_execution_admission_ref AS admission_ref
                USING (tenant_id, runtime_run_id)
             WHERE runtime_run.tenant_id = %s
               AND runtime_run.runtime_run_id = %s
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()
        assert binding is not None
        return dict(binding)


def _expire_and_take_over(
    tenant_id: UUID,
    runtime_run_id: UUID,
    *,
    new_owner: str,
) -> dict[str, Any]:
    assert TEST_DSN is not None
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        connection.execute(
            """
            UPDATE deer_runtime.runtime_run
               SET heartbeat_at = CLOCK_TIMESTAMP() - INTERVAL '2 seconds',
                   lease_until = CLOCK_TIMESTAMP() - INTERVAL '1 second'
             WHERE tenant_id = %s AND runtime_run_id = %s
            """,
            (tenant_id, runtime_run_id),
        )
        taken_over = connection.execute(
            """
            SELECT runtime_run_id, lease_owner, lease_epoch, status
              FROM deer_runtime.takeover_runtime_run(
                  %s, %s, %s, 60, %s, '{"test":"permit-takeover"}'::JSONB
              )
            """,
            (tenant_id, runtime_run_id, new_owner, uuid4()),
        ).fetchone()
        assert taken_over is not None
        return dict(taken_over)


def test_external_operation_arm_is_one_shot_and_unknown_reconciles_monotonically() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    binding = _runtime_permit_binding(tenant_id, runtime_run_id)
    permit_id, intent_id, arm_event_id = uuid4(), uuid4(), uuid4()
    unknown_event_id, reconcile_event_id, source_fact_id = uuid4(), uuid4(), uuid4()
    request_hash = "7" * 64

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        assert connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (tenant_id, runtime_run_id, "worker-a", 1, permit_id,
             "MODEL_INVOKE", intent_id, request_hash, 30, uuid4()),
        ).fetchone() is not None
        arm_parameters = _arm_parameters(
            tenant_id, runtime_run_id, binding, permit_id, intent_id,
            request_hash, arm_event_id,
        )
        armed = connection.execute(
            CONSUME_AND_ARM_RUNTIME_EXTERNAL_DISPATCH_SQL, arm_parameters
        ).fetchone()
        assert armed is not None and armed["dispatch_decision"] == "GRANTED_NOW"
        replay = connection.execute(
            CONSUME_AND_ARM_RUNTIME_EXTERNAL_DISPATCH_SQL, arm_parameters
        ).fetchone()
        assert replay is not None and replay["dispatch_decision"] == "DO_NOT_DISPATCH"

        record_parameters = (
            *arm_parameters[:11], unknown_event_id, "OUTCOME_UNKNOWN",
            source_fact_id, 1, "8" * 64, "PROVIDER_RESPONSE_UNCERTAIN",
            "JAVA_CANONICAL_FACT", None, "java-reconciler",
        )
        unknown = connection.execute(
            RECORD_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL, record_parameters
        ).fetchone()
        assert unknown is not None and unknown["status"] == "OUTCOME_UNKNOWN"
        assert connection.execute(
            RECORD_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL, record_parameters
        ).fetchone() == unknown
        wrong_record_hash = list(record_parameters)
        wrong_record_hash[15] = "d" * 64
        with pytest.raises(psycopg.errors.UniqueViolation):
            with connection.transaction():
                connection.execute(
                    RECORD_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL,
                    tuple(wrong_record_hash),
                ).fetchone()

        reconcile_parameters = (
            *arm_parameters[:11], unknown_event_id, reconcile_event_id,
            "SUCCEEDED", source_fact_id, 2, "9" * 64,
            "PROVIDER_SUCCEEDED", "JAVA_CANONICAL_FACT", "a" * 64,
            "java-reconciler",
        )
        reconciled = connection.execute(
            RECONCILE_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL, reconcile_parameters
        ).fetchone()
        assert reconciled is not None and reconciled["status"] == "SUCCEEDED"
        assert connection.execute(
            RECONCILE_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL, reconcile_parameters
        ).fetchone() == reconciled
        wrong_reconcile_version = list(reconcile_parameters)
        wrong_reconcile_version[15] = 3
        with pytest.raises(psycopg.errors.UniqueViolation):
            with connection.transaction():
                connection.execute(
                    RECONCILE_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL,
                    tuple(wrong_reconcile_version),
                ).fetchone()
        wrong_reconcile_hash = list(reconcile_parameters)
        wrong_reconcile_hash[16] = "c" * 64
        with pytest.raises(psycopg.errors.UniqueViolation):
            with connection.transaction():
                connection.execute(
                    RECONCILE_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL,
                    tuple(wrong_reconcile_hash),
                ).fetchone()

        events = connection.execute(
            """
            SELECT event_id, event_sequence, event_type, from_status, to_status,
                   source_fact_id, source_fact_version, source_fact_hash,
                   outcome_code, evidence_kind, result_hash
              FROM deer_runtime.runtime_external_operation_event
             WHERE tenant_id = %s AND runtime_external_permit_id = %s
             ORDER BY event_sequence
            """,
            (tenant_id, permit_id),
        ).fetchall()
        assert events == [
            {
                "event_id": arm_event_id,
                "event_sequence": 1,
                "event_type": "DISPATCH_ARMED",
                "from_status": None,
                "to_status": "DISPATCH_ARMED",
                "source_fact_id": None,
                "source_fact_version": None,
                "source_fact_hash": None,
                "outcome_code": None,
                "evidence_kind": None,
                "result_hash": None,
            },
            {
                "event_id": unknown_event_id,
                "event_sequence": 2,
                "event_type": "OUTCOME_RECORDED",
                "from_status": "DISPATCH_ARMED",
                "to_status": "OUTCOME_UNKNOWN",
                "source_fact_id": source_fact_id,
                "source_fact_version": 1,
                "source_fact_hash": "8" * 64,
                "outcome_code": "PROVIDER_RESPONSE_UNCERTAIN",
                "evidence_kind": "JAVA_CANONICAL_FACT",
                "result_hash": None,
            },
            {
                "event_id": reconcile_event_id,
                "event_sequence": 3,
                "event_type": "OUTCOME_RECONCILED",
                "from_status": "OUTCOME_UNKNOWN",
                "to_status": "SUCCEEDED",
                "source_fact_id": source_fact_id,
                "source_fact_version": 2,
                "source_fact_hash": "9" * 64,
                "outcome_code": "PROVIDER_SUCCEEDED",
                "evidence_kind": "JAVA_CANONICAL_FACT",
                "result_hash": "a" * 64,
            },
        ]

        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            with connection.transaction():
                connection.execute(
                    """
                    UPDATE deer_runtime.runtime_external_operation_event
                       SET actor = actor
                     WHERE tenant_id = %s AND runtime_external_permit_id = %s
                    """,
                    (tenant_id, permit_id),
                )
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            with connection.transaction():
                connection.execute(
                    """
                    DELETE FROM deer_runtime.runtime_external_operation_event
                     WHERE tenant_id = %s AND runtime_external_permit_id = %s
                    """,
                    (tenant_id, permit_id),
                )

        with pytest.raises(psycopg.errors.UniqueViolation):
            with connection.transaction():
                connection.execute(
                    RECONCILE_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL,
                    (*reconcile_parameters[:11], uuid4(), *reconcile_parameters[12:]),
                ).fetchone()


def test_external_operation_arm_serializes_to_exactly_one_grant() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    binding = _runtime_permit_binding(tenant_id, runtime_run_id)
    permit_id, intent_id, arm_event_id = uuid4(), uuid4(), uuid4()
    request_hash = "b" * 64
    with psycopg.connect(TEST_DSN) as connection:
        connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (tenant_id, runtime_run_id, "worker-a", 1, permit_id,
             "MODEL_INVOKE", intent_id, request_hash, 30, uuid4()),
        ).fetchone()

    parameters = _arm_parameters(
        tenant_id, runtime_run_id, binding, permit_id, intent_id,
        request_hash, arm_event_id,
    )
    ready = Barrier(2)

    def invoke() -> str:
        with psycopg.connect(TEST_DSN) as connection:
            ready.wait(timeout=5)
            row = connection.execute(
                CONSUME_AND_ARM_RUNTIME_EXTERNAL_DISPATCH_SQL, parameters
            ).fetchone()
            assert row is not None
            return row[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions = list(pool.map(lambda _index: invoke(), range(2)))
    assert sorted(decisions) == ["DO_NOT_DISPATCH", "GRANTED_NOW"]


def test_external_operation_cross_run_outcome_misbinding_does_not_deadlock() -> None:
    assert TEST_DSN is not None
    fixtures: list[tuple[UUID, UUID, dict[str, Any], UUID, UUID, str, UUID]] = []
    for hash_digit in ("c", "d"):
        tenant_id, runtime_run_id = _seed_claimed_run()
        binding = _runtime_permit_binding(tenant_id, runtime_run_id)
        permit_id, intent_id, arm_event_id = uuid4(), uuid4(), uuid4()
        request_hash = hash_digit * 64
        with psycopg.connect(TEST_DSN) as connection:
            connection.execute(
                ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
                (tenant_id, runtime_run_id, "worker-a", 1, permit_id,
                 "MODEL_INVOKE", intent_id, request_hash, 30, uuid4()),
            ).fetchone()
            assert connection.execute(
                CONSUME_AND_ARM_RUNTIME_EXTERNAL_DISPATCH_SQL,
                _arm_parameters(
                    tenant_id, runtime_run_id, binding, permit_id, intent_id,
                    request_hash, arm_event_id,
                ),
            ).fetchone()[0] == "GRANTED_NOW"
        fixtures.append(
            (tenant_id, runtime_run_id, binding, permit_id, intent_id,
             request_hash, arm_event_id)
        )

    ready = Barrier(2)

    def invoke(index: int) -> str:
        tenant_id, runtime_run_id, binding, _permit_id, intent_id, request_hash, _ = fixtures[index]
        wrong_permit_id = fixtures[1 - index][3]
        parameters = (
            tenant_id, wrong_permit_id, runtime_run_id,
            binding["task_execution_generation"], "worker-a", 1,
            binding["admission_snapshot_id"], binding["admission_snapshot_hash"],
            "MODEL_INVOKE", intent_id, request_hash, uuid4(),
            "OUTCOME_UNKNOWN", uuid4(), 1, "e" * 64,
            "PROVIDER_RESPONSE_UNCERTAIN", "JAVA_CANONICAL_FACT", None,
            "java-reconciler",
        )
        with psycopg.connect(TEST_DSN) as connection:
            ready.wait(timeout=5)
            try:
                connection.execute(
                    RECORD_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL, parameters
                ).fetchone()
            except psycopg.errors.UniqueViolation as error:
                return error.sqlstate or ""
        return "unexpected-success"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(invoke, range(2)))
    assert outcomes == ["23505", "23505"]


def test_external_operation_barrier_blocks_normal_terminal_but_allows_unknown_failure() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    binding = _runtime_permit_binding(tenant_id, runtime_run_id)
    permit_id, intent_id, arm_event_id = uuid4(), uuid4(), uuid4()
    request_hash = "f" * 64
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (tenant_id, runtime_run_id, "worker-a", 1, permit_id,
             "MODEL_INVOKE", intent_id, request_hash, 30, uuid4()),
        ).fetchone()
        armed = connection.execute(
            CONSUME_AND_ARM_RUNTIME_EXTERNAL_DISPATCH_SQL,
            _arm_parameters(
                tenant_id, runtime_run_id, binding, permit_id, intent_id,
                request_hash, arm_event_id,
            ),
        ).fetchone()
        assert armed is not None and armed["status"] == "DISPATCH_ARMED"

        barrier = connection.execute(
            """
            SELECT * FROM deer_runtime.load_runtime_external_operation_barrier(
                %s::UUID, %s::UUID, 1::BIGINT, 'worker-a'::VARCHAR, 1::BIGINT
            )
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()
        assert barrier is not None
        assert barrier["dispatch_armed_count"] == 1
        assert barrier["outcome_unknown_count"] == 0
        assert barrier["blocking"] is True

        assert connection.execute(
            """
            SELECT status FROM deer_runtime.complete_runtime_run(
                %s, %s, 'worker-a', 1, %s, 'NORMAL_COMPLETION', '{}'::JSONB
            )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone() is None
        assert connection.execute(
            """
            SELECT status FROM deer_runtime.fail_runtime_run(
                %s, %s, 'worker-a', 1, %s,
                'MODEL_FAILED', 'PROVIDER_FAILED', '{}'::JSONB
            )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone() is None

        unknown_event_id = uuid4()
        source_fact_id = uuid4()
        unknown = connection.execute(
            RECORD_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL,
            (
                *_arm_parameters(
                    tenant_id, runtime_run_id, binding, permit_id, intent_id,
                    request_hash, arm_event_id,
                )[:11],
                unknown_event_id, "OUTCOME_UNKNOWN", source_fact_id, 1,
                "0" * 64, "PROVIDER_RESPONSE_UNCERTAIN",
                "JAVA_CANONICAL_FACT", None, "java-reconciler",
            ),
        ).fetchone()
        assert unknown is not None and unknown["status"] == "OUTCOME_UNKNOWN"
        barrier = connection.execute(
            """
            SELECT * FROM deer_runtime.load_runtime_external_operation_barrier(
                %s::UUID, %s::UUID, 1::BIGINT, 'worker-a'::VARCHAR, 1::BIGINT
            )
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()
        assert barrier is not None
        assert barrier["dispatch_armed_count"] == 0
        assert barrier["outcome_unknown_count"] == 1
        assert barrier["blocking"] is True
        assert connection.execute(
            """
            SELECT status FROM deer_runtime.complete_runtime_run(
                %s, %s, 'worker-a', 1, %s, 'NORMAL_COMPLETION', '{}'::JSONB
            )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone() is None
        assert connection.execute(
            """
            SELECT status FROM deer_runtime.fail_runtime_run(
                %s, %s, 'worker-a', 1, %s,
                'MODEL_FAILED', 'PROVIDER_FAILED', '{}'::JSONB
            )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone() is None

        failed = connection.execute(
            """
            SELECT status, failure_code FROM deer_runtime.fail_runtime_run(
                %s, %s, 'worker-a', 1, %s,
                'MODEL_OUTCOME_UNKNOWN', 'EXTERNAL_OUTCOME_UNKNOWN', '{}'::JSONB
            )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone()
        assert failed == {
            "status": "FAILED",
            "failure_code": "EXTERNAL_OUTCOME_UNKNOWN",
        }
        projection = connection.execute(
            """
            SELECT status FROM deer_runtime.runtime_external_operation_attempt
             WHERE tenant_id = %s AND runtime_external_permit_id = %s
            """,
            (tenant_id, permit_id),
        ).fetchone()
        assert projection == {"status": "OUTCOME_UNKNOWN"}


def test_external_operation_late_outcome_after_takeover_uses_historical_binding() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    binding = _runtime_permit_binding(tenant_id, runtime_run_id)
    permit_id, intent_id, arm_event_id = uuid4(), uuid4(), uuid4()
    request_hash = "1" * 64
    with psycopg.connect(TEST_DSN) as connection:
        connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (tenant_id, runtime_run_id, "worker-a", 1, permit_id,
             "MODEL_INVOKE", intent_id, request_hash, 30, uuid4()),
        ).fetchone()
        assert connection.execute(
            CONSUME_AND_ARM_RUNTIME_EXTERNAL_DISPATCH_SQL,
            _arm_parameters(
                tenant_id, runtime_run_id, binding, permit_id, intent_id,
                request_hash, arm_event_id,
            ),
        ).fetchone()[0] == "GRANTED_NOW"

    takeover = _expire_and_take_over(
        tenant_id, runtime_run_id, new_owner="worker-b"
    )
    assert takeover["lease_epoch"] == 2
    late_parameters = (
        tenant_id, permit_id, runtime_run_id,
        binding["task_execution_generation"], "worker-a", 1,
        binding["admission_snapshot_id"], binding["admission_snapshot_hash"],
        "MODEL_INVOKE", intent_id, request_hash, uuid4(), "SUCCEEDED",
        uuid4(), 1, "2" * 64, "PROVIDER_SUCCEEDED",
        "JAVA_CANONICAL_FACT", "3" * 64, "java-reconciler",
    )
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        late = connection.execute(
            RECORD_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL, late_parameters
        ).fetchone()
        assert late is not None and late["status"] == "SUCCEEDED"
        wrong_epoch = list(late_parameters)
        wrong_epoch[11] = uuid4()
        wrong_epoch[5] = 2
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                RECORD_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL,
                tuple(wrong_epoch),
            ).fetchone()


def test_external_operation_barrier_blocks_cancelled_but_allows_unknown_cancel() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    binding = _runtime_permit_binding(tenant_id, runtime_run_id)
    permit_id, intent_id = uuid4(), uuid4()
    request_hash = "4" * 64
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (tenant_id, runtime_run_id, "worker-a", 1, permit_id,
             "TOOL_INVOKE", intent_id, request_hash, 30, uuid4()),
        ).fetchone()
        arm_event_id = uuid4()
        tool_arm_parameters = list(_arm_parameters(
            tenant_id, runtime_run_id, binding, permit_id, intent_id,
            request_hash, arm_event_id,
        ))
        tool_arm_parameters[8] = "TOOL_INVOKE"
        assert connection.execute(
            CONSUME_AND_ARM_RUNTIME_EXTERNAL_DISPATCH_SQL,
            tuple(tool_arm_parameters),
        ).fetchone()["dispatch_decision"] == "GRANTED_NOW"
        control_id = uuid4()
        cancel_actor_id = uuid4()
        cancel_key = f"cancel-{control_id}"
        assert connection.execute(
            """
            SELECT COUNT(*) AS row_count
              FROM deer_runtime.request_runtime_run_cancel(
                  %s, %s, %s, %s, 'USER_REQUESTED', 2,
                  %s, %s, '{}'::JSONB
              )
            """,
            (
                tenant_id,
                runtime_run_id,
                control_id,
                cancel_actor_id,
                cancel_key,
                "6" * 64,
            ),
        ).fetchone()["row_count"] == 1
        assert connection.execute(
            """
            SELECT status FROM deer_runtime.begin_runtime_run_cancellation(
                %s, %s, 'worker-a', 1, %s, '{}'::JSONB
            )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone() == {"status": "CANCELLING"}
        assert connection.execute(
            """
            SELECT status FROM deer_runtime.finish_runtime_run_cancellation(
                %s, %s, 'worker-a', 1, 'CANCELLED', %s,
                'USER_REQUESTED', '{}'::JSONB
            )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone() is None
        unknown_event_id = uuid4()
        source_fact_id = uuid4()
        unknown_parameters = (
            *tuple(tool_arm_parameters)[:11], unknown_event_id, "OUTCOME_UNKNOWN",
            source_fact_id, 1, "5" * 64, "PROVIDER_RESPONSE_UNCERTAIN",
            "JAVA_CANONICAL_FACT", None, "java-reconciler",
        )
        unknown = connection.execute(
            RECORD_RUNTIME_EXTERNAL_OPERATION_OUTCOME_SQL, unknown_parameters
        ).fetchone()
        assert unknown is not None and unknown["status"] == "OUTCOME_UNKNOWN"
        assert connection.execute(
            """
            SELECT status FROM deer_runtime.finish_runtime_run_cancellation(
                %s, %s, 'worker-a', 1, 'CANCELLED', %s,
                'USER_REQUESTED', '{}'::JSONB
            )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone() is None
        finished = connection.execute(
            """
            SELECT status FROM deer_runtime.finish_runtime_run_cancellation(
                %s, %s, 'worker-a', 1, 'CANCEL_OUTCOME_UNKNOWN', %s,
                'EXTERNAL_OUTCOME_UNKNOWN', '{}'::JSONB
            )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone()
        assert finished == {"status": "CANCEL_OUTCOME_UNKNOWN"}
        assert connection.execute(
            """
            SELECT status FROM deer_runtime.runtime_external_operation_attempt
             WHERE tenant_id = %s AND runtime_external_permit_id = %s
            """,
            (tenant_id, permit_id),
        ).fetchone() == {"status": "OUTCOME_UNKNOWN"}


def _invoke_twice_behind_run_lock(
    *,
    tenant_id: UUID,
    runtime_run_id: UUID,
    statement: str,
    parameters: tuple[Any, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    assert TEST_DSN is not None
    ready = Barrier(3)
    backend_pids: Queue[int] = Queue()

    def invoke() -> dict[str, Any]:
        with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
            backend_pids.put(connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
            ready.wait(timeout=5)
            row = connection.execute(statement, parameters).fetchone()
            assert row is not None
            return dict(row)

    with psycopg.connect(TEST_DSN) as lock_connection:
        lock_connection.execute(
            """
            SELECT 1
              FROM deer_runtime.runtime_run
             WHERE tenant_id = %s AND runtime_run_id = %s
             FOR UPDATE
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()
        with ThreadPoolExecutor(max_workers=2) as executor:
            try:
                first = executor.submit(invoke)
                second = executor.submit(invoke)
                ready.wait(timeout=5)
                pids = [backend_pids.get(timeout=5), backend_pids.get(timeout=5)]
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    lock_connection.execute("SELECT pg_stat_clear_snapshot()")
                    waiting = lock_connection.execute(
                        """
                        SELECT COUNT(*)
                          FROM pg_catalog.pg_stat_activity
                         WHERE pid = ANY(%s)
                           AND wait_event_type = 'Lock'
                        """,
                        (pids,),
                    ).fetchone()[0]
                    if waiting == 2:
                        break
                    sleep(0.01)
                else:
                    raise AssertionError(
                        "both concurrent calls did not reach the Run row lock"
                    )
                lock_connection.commit()
                return first.result(timeout=5), second.result(timeout=5)
            except BaseException:
                lock_connection.rollback()
                raise


def _race_statements_behind_run_lock(
    *,
    tenant_id: UUID,
    runtime_run_id: UUID,
    first_statement: str,
    first_parameters: tuple[Any, ...],
    second_statement: str,
    second_parameters: tuple[Any, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    assert TEST_DSN is not None
    ready = Barrier(3)
    backend_pids: Queue[int] = Queue()

    def invoke(statement: str, parameters: tuple[Any, ...]) -> dict[str, Any]:
        with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
            backend_pids.put(connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"])
            ready.wait(timeout=5)
            row = connection.execute(statement, parameters).fetchone()
            assert row is not None
            return dict(row)

    with psycopg.connect(TEST_DSN) as lock_connection:
        lock_connection.execute(
            """
            SELECT 1
              FROM deer_runtime.runtime_run
             WHERE tenant_id = %s AND runtime_run_id = %s
             FOR UPDATE
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()
        with ThreadPoolExecutor(max_workers=2) as executor:
            try:
                first = executor.submit(invoke, first_statement, first_parameters)
                second = executor.submit(invoke, second_statement, second_parameters)
                ready.wait(timeout=5)
                pids = [backend_pids.get(timeout=5), backend_pids.get(timeout=5)]
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    lock_connection.execute("SELECT pg_stat_clear_snapshot()")
                    waiting = lock_connection.execute(
                        """
                        SELECT COUNT(*)
                          FROM pg_catalog.pg_stat_activity
                         WHERE pid = ANY(%s)
                           AND wait_event_type = 'Lock'
                        """,
                        (pids,),
                    ).fetchone()[0]
                    if waiting == 2:
                        break
                    sleep(0.01)
                else:
                    raise AssertionError(
                        "both competing calls did not reach the Run row lock"
                    )
                lock_connection.commit()
                return first.result(timeout=5), second.result(timeout=5)
            except BaseException:
                lock_connection.rollback()
                raise


def _wait_until_backend_is_blocked_on_lock(connection, pid: int) -> None:
    deadline = monotonic() + 5
    while monotonic() < deadline:
        connection.execute("SELECT pg_stat_clear_snapshot()")
        row = connection.execute(
            """
            SELECT wait_event_type
              FROM pg_catalog.pg_stat_activity
             WHERE pid = %s
            """,
            (pid,),
        ).fetchone()
        if row is not None and row[0] == "Lock":
            return
        sleep(0.01)
    raise AssertionError(f"backend {pid} did not reach the Run row lock")


def _invoke_ordered_behind_run_lock(
    *,
    tenant_id: UUID,
    runtime_run_id: UUID,
    first_statement: str,
    first_parameters: tuple[Any, ...],
    second_statement: str,
    second_parameters: tuple[Any, ...],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    assert TEST_DSN is not None
    backend_pids: Queue[int] = Queue()

    def invoke(
        statement: str,
        parameters: tuple[Any, ...],
    ) -> dict[str, Any] | None:
        with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
            backend_pids.put(
                connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            )
            row = connection.execute(statement, parameters).fetchone()
            return None if row is None else dict(row)

    with psycopg.connect(TEST_DSN) as lock_connection:
        lock_connection.execute(
            """
            SELECT 1
              FROM deer_runtime.runtime_run
             WHERE tenant_id = %s AND runtime_run_id = %s
             FOR UPDATE
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()
        with ThreadPoolExecutor(max_workers=2) as executor:
            try:
                first = executor.submit(invoke, first_statement, first_parameters)
                first_pid = backend_pids.get(timeout=5)
                _wait_until_backend_is_blocked_on_lock(lock_connection, first_pid)
                second = executor.submit(invoke, second_statement, second_parameters)
                second_pid = backend_pids.get(timeout=5)
                _wait_until_backend_is_blocked_on_lock(lock_connection, second_pid)
                lock_connection.commit()
                return first.result(timeout=5), second.result(timeout=5)
            except BaseException:
                lock_connection.rollback()
                raise


def _invoke_after_lease_expires_behind_run_lock(
    *,
    tenant_id: UUID,
    runtime_run_id: UUID,
    statement: str,
    parameters: tuple[Any, ...],
) -> dict[str, Any] | None:
    assert TEST_DSN is not None
    backend_pid: Queue[int] = Queue()

    def invoke() -> dict[str, Any] | None:
        with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
            backend_pid.put(
                connection.execute("SELECT pg_backend_pid() AS pid").fetchone()["pid"]
            )
            row = connection.execute(statement, parameters).fetchone()
            return None if row is None else dict(row)

    with psycopg.connect(TEST_DSN) as lock_connection:
        lease_until = lock_connection.execute(
            """
            UPDATE deer_runtime.runtime_run
               SET heartbeat_at = CLOCK_TIMESTAMP(),
                   lease_until = CLOCK_TIMESTAMP() + INTERVAL '1 second'
             WHERE tenant_id = %s AND runtime_run_id = %s
         RETURNING lease_until
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()[0]
        with ThreadPoolExecutor(max_workers=1) as executor:
            try:
                result = executor.submit(invoke)
                pid = backend_pid.get(timeout=5)
                _wait_until_backend_is_blocked_on_lock(lock_connection, pid)
                lock_connection.execute("SELECT pg_sleep(1.1)")
                assert lock_connection.execute(
                    "SELECT CLOCK_TIMESTAMP() >= %s",
                    (lease_until,),
                ).fetchone()[0]
                lock_connection.commit()
                return result.result(timeout=5)
            except BaseException:
                lock_connection.rollback()
                raise


def test_external_permit_issue_consume_and_response_replay_are_exact() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    binding = _runtime_permit_binding(tenant_id, runtime_run_id)
    permit_id = uuid4()
    intent_id = uuid4()
    issue_event_id = uuid4()
    consume_event_id = uuid4()
    issue_parameters = (
        tenant_id,
        runtime_run_id,
        "worker-a",
        1,
        permit_id,
        "MODEL_INVOKE",
        intent_id,
        "7" * 64,
        30,
        issue_event_id,
    )
    consume_parameters = (
        tenant_id,
        permit_id,
        runtime_run_id,
        binding["task_execution_generation"],
        "worker-a",
        1,
        binding["admission_snapshot_id"],
        binding["admission_snapshot_hash"],
        "MODEL_INVOKE",
        intent_id,
        "7" * 64,
        consume_event_id,
        "java-model-authorizer",
    )

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        issued = connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            issue_parameters,
        ).fetchone()
        assert issued is not None
        connection.execute(
            """
            UPDATE deer_runtime.runtime_run
               SET heartbeat_at = CLOCK_TIMESTAMP(),
                   lease_until = CLOCK_TIMESTAMP() + INTERVAL '2 seconds'
             WHERE tenant_id = %s AND runtime_run_id = %s
            """,
            (tenant_id, runtime_run_id),
        )
        replayed_issue = connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            issue_parameters,
        ).fetchone()
        assert issued == replayed_issue
        connection.execute(
            """
            UPDATE deer_runtime.runtime_run
               SET heartbeat_at = CLOCK_TIMESTAMP(),
                   lease_until = CLOCK_TIMESTAMP() + INTERVAL '60 seconds'
             WHERE tenant_id = %s AND runtime_run_id = %s
            """,
            (tenant_id, runtime_run_id),
        )
        assert list(issued) == [
            "tenant_id",
            "runtime_external_permit_id",
            "runtime_run_id",
            "runtime_thread_id",
            "task_step_id",
            "task_execution_generation",
            "admission_contract_version",
            "admission_snapshot_id",
            "admission_snapshot_hash",
            "operation_kind",
            "intent_id",
            "request_hash",
            "lease_owner",
            "lease_epoch",
            "permit_attempt",
            "status",
            "requested_ttl_seconds",
            "issued_at",
            "expires_at",
            "issue_event_id",
            "consume_event_id",
            "consumed_by",
            "consumed_at",
            "updated_at",
        ]
        assert issued["status"] == "ISSUED"
        assert issued["permit_attempt"] == 1
        assert issued["admission_contract_version"] == "2.2"
        assert issued["expires_at"] <= connection.execute(
            """
            SELECT lease_until FROM deer_runtime.runtime_run
             WHERE tenant_id = %s AND runtime_run_id = %s
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()["lease_until"]

        consumed = connection.execute(
            CONSUME_RUNTIME_EXTERNAL_PERMIT_SQL,
            consume_parameters,
        ).fetchone()
        replayed_consume = connection.execute(
            CONSUME_RUNTIME_EXTERNAL_PERMIT_SQL,
            consume_parameters,
        ).fetchone()
        assert consumed == replayed_consume
        assert consumed is not None
        assert consumed["status"] == "CONSUMED"
        assert consumed["consume_event_id"] == consume_event_id
        assert consumed["consumed_by"] == "java-model-authorizer"
        assert consumed["issued_at"] <= consumed["consumed_at"] < consumed["expires_at"]
        assert connection.execute(
            """
            SELECT COUNT(*) AS event_count
              FROM deer_runtime.runtime_external_permit_event
             WHERE tenant_id = %s AND runtime_external_permit_id = %s
            """,
            (tenant_id, permit_id),
        ).fetchone()["event_count"] == 2

        canonical = connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (
                tenant_id,
                runtime_run_id,
                "worker-a",
                1,
                uuid4(),
                "MODEL_INVOKE",
                intent_id,
                "7" * 64,
                10,
                uuid4(),
            ),
        ).fetchone()
        assert canonical == consumed

    _expire_and_take_over(tenant_id, runtime_run_id, new_owner="worker-b")
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        canonical_after_takeover = connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (
                tenant_id,
                runtime_run_id,
                "worker-b",
                2,
                uuid4(),
                "MODEL_INVOKE",
                intent_id,
                "7" * 64,
                10,
                uuid4(),
            ),
        ).fetchone()
        assert canonical_after_takeover == consumed
        assert connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (
                tenant_id,
                runtime_run_id,
                "worker-a",
                1,
                uuid4(),
                "MODEL_INVOKE",
                intent_id,
                "7" * 64,
                10,
                uuid4(),
            ),
        ).fetchone() is None
        assert connection.execute(
            """
            SELECT COUNT(*) AS attempt_count
              FROM deer_runtime.runtime_external_permit_attempt
             WHERE tenant_id = %s AND runtime_run_id = %s
               AND operation_kind = 'MODEL_INVOKE' AND intent_id = %s
            """,
            (tenant_id, runtime_run_id, intent_id),
        ).fetchone()["attempt_count"] == 1
        historical_replay = connection.execute(
            CONSUME_RUNTIME_EXTERNAL_PERMIT_SQL,
            consume_parameters,
        ).fetchone()
        assert historical_replay == consumed
        conflicting = list(consume_parameters)
        conflicting[11] = uuid4()
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                CONSUME_RUNTIME_EXTERNAL_PERMIT_SQL,
                tuple(conflicting),
            ).fetchone()

    with psycopg.connect(TEST_DSN) as connection:
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
            connection.execute(
                """
                UPDATE deer_runtime.runtime_external_permit_attempt
                   SET consumed_at = expires_at, updated_at = expires_at
                 WHERE tenant_id = %s AND runtime_external_permit_id = %s
                """,
                (tenant_id, permit_id),
            )


def test_external_permit_current_wrapper_fences_historical_replay_after_takeover() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    binding = _runtime_permit_binding(tenant_id, runtime_run_id)
    permit_id = uuid4()
    intent_id = uuid4()
    consume_event_id = uuid4()
    request_hash = "6" * 64
    consume_parameters = (
        tenant_id,
        permit_id,
        runtime_run_id,
        binding["task_execution_generation"],
        "worker-a",
        1,
        binding["admission_snapshot_id"],
        binding["admission_snapshot_hash"],
        "ADMISSION_RESOLVE",
        intent_id,
        request_hash,
        consume_event_id,
        "java-admission-authorizer",
    )

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        assert connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (
                tenant_id,
                runtime_run_id,
                "worker-a",
                1,
                permit_id,
                "ADMISSION_RESOLVE",
                intent_id,
                request_hash,
                30,
                uuid4(),
            ),
        ).fetchone() is not None
        consumed = connection.execute(
            CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
            consume_parameters,
        ).fetchone()
        replayed = connection.execute(
            CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
            consume_parameters,
        ).fetchone()
        assert consumed is not None and consumed == replayed
        assert consumed["status"] == "CONSUMED"

    with psycopg.connect(TEST_DSN) as connection:
        connection.execute(
            """
            UPDATE deer_runtime.runtime_run
               SET heartbeat_at = CLOCK_TIMESTAMP() - INTERVAL '2 seconds',
                   lease_until = CLOCK_TIMESTAMP() - INTERVAL '1 second'
             WHERE tenant_id = %s AND runtime_run_id = %s
            """,
            (tenant_id, runtime_run_id),
        )
    takeover_statement = """
        SELECT runtime_run_id, lease_owner, lease_epoch
          FROM deer_runtime.takeover_runtime_run(
              %s, %s, 'worker-b', 60, %s, '{"test":"current-permit-race"}'::JSONB
          )
    """
    takeover, fenced_replay = _invoke_ordered_behind_run_lock(
        tenant_id=tenant_id,
        runtime_run_id=runtime_run_id,
        first_statement=takeover_statement,
        first_parameters=(tenant_id, runtime_run_id, uuid4()),
        second_statement=CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
        second_parameters=consume_parameters,
    )
    assert takeover == {
        "runtime_run_id": runtime_run_id,
        "lease_owner": "worker-b",
        "lease_epoch": 2,
    }
    assert fenced_replay is None

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        assert connection.execute(
            CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
            consume_parameters,
        ).fetchone() is None
        assert connection.execute(
            CONSUME_RUNTIME_EXTERNAL_PERMIT_SQL,
            consume_parameters,
        ).fetchone() is not None

        current_permit_id = uuid4()
        current_intent_id = uuid4()
        current_request_hash = "5" * 64
        assert connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (
                tenant_id,
                runtime_run_id,
                "worker-b",
                2,
                current_permit_id,
                "ADMISSION_RESOLVE",
                current_intent_id,
                current_request_hash,
                30,
                uuid4(),
            ),
        ).fetchone() is not None
        current_parameters = (
            tenant_id,
            current_permit_id,
            runtime_run_id,
            binding["task_execution_generation"],
            "worker-b",
            2,
            binding["admission_snapshot_id"],
            binding["admission_snapshot_hash"],
            "ADMISSION_RESOLVE",
            current_intent_id,
            current_request_hash,
            uuid4(),
            "java-admission-authorizer",
        )

    current, current_replay = _invoke_twice_behind_run_lock(
        tenant_id=tenant_id,
        runtime_run_id=runtime_run_id,
        statement=CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
        parameters=current_parameters,
    )
    assert current == current_replay
    assert current["lease_owner"] == "worker-b"
    assert current["lease_epoch"] == 2
    assert current["status"] == "CONSUMED"
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*) FILTER (WHERE event_type = 'CONSUMED') AS event_count
              FROM deer_runtime.runtime_external_permit_event
             WHERE tenant_id = %s AND runtime_external_permit_id = %s
            """,
            (tenant_id, current_permit_id),
        ).fetchone() == {"event_count": 1}
        assert connection.execute(
            """
            SELECT status
              FROM deer_runtime.complete_runtime_run(
                  %s, %s, 'worker-b', 2, %s,
                  'NORMAL_COMPLETION', '{"test":"current-permit-terminal"}'::JSONB
              )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone() == {"status": "COMPLETED"}
        assert connection.execute(
            CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
            current_parameters,
        ).fetchone() is None


def test_external_permit_current_wrapper_rechecks_expiry_after_run_lock_wait() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    binding = _runtime_permit_binding(tenant_id, runtime_run_id)
    permit_id = uuid4()
    intent_id = uuid4()
    request_hash = "3" * 64
    consume_parameters = (
        tenant_id,
        permit_id,
        runtime_run_id,
        binding["task_execution_generation"],
        "worker-a",
        1,
        binding["admission_snapshot_id"],
        binding["admission_snapshot_hash"],
        "ADMISSION_RESOLVE",
        intent_id,
        request_hash,
        uuid4(),
        "java-admission-authorizer",
    )
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        assert connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (
                tenant_id,
                runtime_run_id,
                "worker-a",
                1,
                permit_id,
                "ADMISSION_RESOLVE",
                intent_id,
                request_hash,
                30,
                uuid4(),
            ),
        ).fetchone() is not None
        consumed = connection.execute(
            CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
            consume_parameters,
        ).fetchone()
        assert consumed is not None and consumed["status"] == "CONSUMED"

    assert _invoke_after_lease_expires_behind_run_lock(
        tenant_id=tenant_id,
        runtime_run_id=runtime_run_id,
        statement=CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
        parameters=consume_parameters,
    ) is None
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        run_and_events = connection.execute(
            """
            SELECT runtime_run.status, runtime_run.lease_owner,
                   runtime_run.lease_epoch,
                   runtime_run.lease_until <= CLOCK_TIMESTAMP() AS lease_expired,
                   (SELECT COUNT(*)
                      FROM deer_runtime.runtime_external_permit_event AS permit_event
                     WHERE permit_event.tenant_id = runtime_run.tenant_id
                       AND permit_event.runtime_external_permit_id = %s
                       AND permit_event.event_type = 'CONSUMED') AS consumed_event_count
              FROM deer_runtime.runtime_run AS runtime_run
             WHERE runtime_run.tenant_id = %s
               AND runtime_run.runtime_run_id = %s
            """,
            (permit_id, tenant_id, runtime_run_id),
        ).fetchone()
        assert run_and_events == {
            "status": "RUNNING",
            "lease_owner": "worker-a",
            "lease_epoch": 1,
            "lease_expired": True,
            "consumed_event_count": 1,
        }
        assert connection.execute(
            CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
            consume_parameters,
        ).fetchone() is None


def test_external_permit_authorizer_acl_rejects_old_consume_and_allows_wrapper() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    binding = _runtime_permit_binding(tenant_id, runtime_run_id)
    permit_id = uuid4()
    intent_id = uuid4()
    request_hash = "4" * 64
    consume_parameters = (
        tenant_id,
        permit_id,
        runtime_run_id,
        binding["task_execution_generation"],
        "worker-a",
        1,
        binding["admission_snapshot_id"],
        binding["admission_snapshot_hash"],
        "ADMISSION_RESOLVE",
        intent_id,
        request_hash,
        uuid4(),
        "java-admission-authorizer",
    )
    with psycopg.connect(TEST_DSN) as connection:
        assert connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (
                tenant_id,
                runtime_run_id,
                "worker-a",
                1,
                permit_id,
                "ADMISSION_RESOLVE",
                intent_id,
                request_hash,
                30,
                uuid4(),
            ),
        ).fetchone() is not None

    with psycopg.connect(TEST_DSN) as connection:
        connection.execute("SET ROLE dianlian_supervisor_permit_authorizer")
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as denied:
            connection.execute(
                CONSUME_RUNTIME_EXTERNAL_PERMIT_SQL,
                consume_parameters,
            ).fetchone()
        assert denied.value.sqlstate == "42501"
        connection.rollback()

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        connection.execute("SET ROLE dianlian_supervisor_permit_authorizer")
        consumed = connection.execute(
            CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
            consume_parameters,
        ).fetchone()
        assert consumed is not None
        assert consumed["status"] == "CONSUMED"
        assert consumed["runtime_external_permit_id"] == permit_id


def test_external_permit_takeover_before_consume_fences_old_attempt() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    binding = _runtime_permit_binding(tenant_id, runtime_run_id)
    old_permit_id = uuid4()
    intent_id = uuid4()
    request_hash = "8" * 64
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        issued = connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (
                tenant_id,
                runtime_run_id,
                "worker-a",
                1,
                old_permit_id,
                "TOOL_INVOKE",
                intent_id,
                request_hash,
                30,
                uuid4(),
            ),
        ).fetchone()
        assert issued is not None and issued["status"] == "ISSUED"

    takeover = _expire_and_take_over(
        tenant_id,
        runtime_run_id,
        new_owner="worker-b",
    )
    assert takeover["lease_epoch"] == 2
    old_consume_parameters = (
        tenant_id,
        old_permit_id,
        runtime_run_id,
        binding["task_execution_generation"],
        "worker-a",
        1,
        binding["admission_snapshot_id"],
        binding["admission_snapshot_hash"],
        "TOOL_INVOKE",
        intent_id,
        request_hash,
        uuid4(),
        "java-tool-authorizer",
    )
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        assert connection.execute(
            CONSUME_RUNTIME_EXTERNAL_PERMIT_SQL,
            old_consume_parameters,
        ).fetchone() is None

        new_permit_id = uuid4()
        new_issue_parameters = (
            tenant_id,
            runtime_run_id,
            "worker-b",
            2,
            new_permit_id,
            "TOOL_INVOKE",
            intent_id,
            request_hash,
            30,
            uuid4(),
        )
        new_attempt = connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            new_issue_parameters,
        ).fetchone()
        assert new_attempt is not None
        assert new_attempt["runtime_external_permit_id"] == new_permit_id
        assert new_attempt["permit_attempt"] == 2
        assert new_attempt["lease_owner"] == "worker-b"
        assert new_attempt["lease_epoch"] == 2

        new_consume_parameters = list(old_consume_parameters)
        new_consume_parameters[1] = new_permit_id
        new_consume_parameters[4] = "worker-b"
        new_consume_parameters[5] = 2
        new_consume_parameters[11] = uuid4()
        consumed = connection.execute(
            CONSUME_RUNTIME_EXTERNAL_PERMIT_SQL,
            tuple(new_consume_parameters),
        ).fetchone()
        assert consumed is not None
        assert consumed["status"] == "CONSUMED"
        assert consumed["permit_attempt"] == 2
        assert connection.execute(
            """
            SELECT COUNT(*) FILTER (WHERE status = 'CONSUMED') AS consumed_count,
                   COUNT(*) AS attempt_count
              FROM deer_runtime.runtime_external_permit_attempt
             WHERE tenant_id = %s AND runtime_run_id = %s
               AND operation_kind = 'TOOL_INVOKE' AND intent_id = %s
            """,
            (tenant_id, runtime_run_id, intent_id),
        ).fetchone() == {"consumed_count": 1, "attempt_count": 2}


def test_admission_permit_takeover_reissues_one_read_attempt_per_epoch() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    binding = _runtime_permit_binding(tenant_id, runtime_run_id)
    intent_id = binding["admission_snapshot_id"]
    request_hash = binding["admission_snapshot_hash"]
    first_permit_id = uuid4()

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        first = connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (
                tenant_id,
                runtime_run_id,
                "worker-a",
                1,
                first_permit_id,
                "ADMISSION_RESOLVE",
                intent_id,
                request_hash,
                30,
                uuid4(),
            ),
        ).fetchone()
        assert first is not None and first["permit_attempt"] == 1
        consumed = connection.execute(
            CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (
                tenant_id,
                first_permit_id,
                runtime_run_id,
                binding["task_execution_generation"],
                "worker-a",
                1,
                binding["admission_snapshot_id"],
                binding["admission_snapshot_hash"],
                "ADMISSION_RESOLVE",
                intent_id,
                request_hash,
                uuid4(),
                "java-admission-authorizer",
            ),
        ).fetchone()
        assert consumed is not None and consumed["status"] == "CONSUMED"

    takeover = _expire_and_take_over(
        tenant_id,
        runtime_run_id,
        new_owner="worker-b",
    )
    assert takeover["lease_epoch"] == 2

    second_permit_id = uuid4()
    second_issue_event_id = uuid4()
    second_issue_parameters = (
        tenant_id,
        runtime_run_id,
        "worker-b",
        2,
        second_permit_id,
        "ADMISSION_RESOLVE",
        intent_id,
        request_hash,
        30,
        second_issue_event_id,
    )
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        second = connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            second_issue_parameters,
        ).fetchone()
        assert second is not None
        assert second["runtime_external_permit_id"] == second_permit_id
        assert second["permit_attempt"] == 2
        assert second["status"] == "ISSUED"
        assert second["lease_owner"] == "worker-b"
        assert second["lease_epoch"] == 2

        second_consumed = connection.execute(
            CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (
                tenant_id,
                second_permit_id,
                runtime_run_id,
                binding["task_execution_generation"],
                "worker-b",
                2,
                binding["admission_snapshot_id"],
                binding["admission_snapshot_hash"],
                "ADMISSION_RESOLVE",
                intent_id,
                request_hash,
                uuid4(),
                "java-admission-authorizer",
            ),
        ).fetchone()
        assert second_consumed is not None
        assert second_consumed["status"] == "CONSUMED"
        assert second_consumed["permit_attempt"] == 2

        # A different identity in the same epoch cannot create attempt 3.
        same_epoch = list(second_issue_parameters)
        same_epoch[4] = uuid4()
        same_epoch[9] = uuid4()
        replayed = connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            tuple(same_epoch),
        ).fetchone()
        assert replayed is not None
        assert replayed["runtime_external_permit_id"] == second_permit_id
        assert replayed["permit_attempt"] == 2
        assert connection.execute(
            """
            SELECT COUNT(*) AS attempt_count,
                   COUNT(*) FILTER (WHERE status = 'CONSUMED') AS consumed_count
              FROM deer_runtime.runtime_external_permit_attempt
             WHERE tenant_id = %s AND runtime_run_id = %s
               AND operation_kind = 'ADMISSION_RESOLVE' AND intent_id = %s
            """,
            (tenant_id, runtime_run_id, intent_id),
        ).fetchone() == {"attempt_count": 2, "consumed_count": 2}


def test_external_permit_current_wrapper_concurrent_replay_is_single_fact() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    binding = _runtime_permit_binding(tenant_id, runtime_run_id)
    intent_id = uuid4()
    request_hash = "9" * 64
    permit_id = uuid4()
    issue_parameters = (
        tenant_id,
        runtime_run_id,
        "worker-a",
        1,
        permit_id,
        "ADMISSION_RESOLVE",
        intent_id,
        request_hash,
        30,
        uuid4(),
    )
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        assert connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            issue_parameters,
        ).fetchone() is not None
        connection.commit()
        conflicting_issue = list(issue_parameters)
        conflicting_issue[4] = uuid4()
        conflicting_issue[9] = uuid4()
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
                tuple(conflicting_issue),
            ).fetchone()
        connection.rollback()

    consume_event_id = uuid4()
    consume_parameters = (
        tenant_id,
        permit_id,
        runtime_run_id,
        binding["task_execution_generation"],
        "worker-a",
        1,
        binding["admission_snapshot_id"],
        binding["admission_snapshot_hash"],
        "ADMISSION_RESOLVE",
        intent_id,
        request_hash,
        consume_event_id,
        "java-admission-authorizer",
    )
    first, second = _invoke_twice_behind_run_lock(
        tenant_id=tenant_id,
        runtime_run_id=runtime_run_id,
        statement=CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
        parameters=consume_parameters,
    )
    assert first == second
    assert first["status"] == "CONSUMED"
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        assert connection.execute(
            """
            SELECT COUNT(DISTINCT permit_attempt.runtime_external_permit_id)
                       AS attempt_count,
                   COUNT(*) FILTER (WHERE event_type = 'CONSUMED') AS consumed_event_count
              FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
              JOIN deer_runtime.runtime_external_permit_event AS permit_event
                USING (tenant_id, runtime_external_permit_id)
             WHERE permit_attempt.tenant_id = %s
               AND permit_attempt.runtime_external_permit_id = %s
            """,
            (tenant_id, permit_id),
        ).fetchone() == {"attempt_count": 1, "consumed_event_count": 1}


def test_external_permit_current_wrapper_and_takeover_serialize_in_both_lock_orders() -> None:
    assert TEST_DSN is not None
    takeover_statement = """
        SELECT runtime_run_id, lease_owner, lease_epoch
          FROM deer_runtime.takeover_runtime_run(
              %s, %s, 'worker-b', 60, %s, '{"test":"permit-race"}'::JSONB
          )
    """

    consume_first_tenant, consume_first_run = _seed_claimed_run()
    consume_first_binding = _runtime_permit_binding(
        consume_first_tenant,
        consume_first_run,
    )
    consume_first_permit = uuid4()
    consume_first_intent = uuid4()
    consume_first_event = uuid4()
    with psycopg.connect(TEST_DSN) as connection:
        assert connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (
                consume_first_tenant,
                consume_first_run,
                "worker-a",
                1,
                consume_first_permit,
                "ADMISSION_RESOLVE",
                consume_first_intent,
                "c" * 64,
                30,
                uuid4(),
            ),
        ).fetchone() is not None
    consume_first_parameters = (
        consume_first_tenant,
        consume_first_permit,
        consume_first_run,
        consume_first_binding["task_execution_generation"],
        "worker-a",
        1,
        consume_first_binding["admission_snapshot_id"],
        consume_first_binding["admission_snapshot_hash"],
        "ADMISSION_RESOLVE",
        consume_first_intent,
        "c" * 64,
        consume_first_event,
        "java-model-authorizer",
    )
    consumed, live_takeover = _invoke_ordered_behind_run_lock(
        tenant_id=consume_first_tenant,
        runtime_run_id=consume_first_run,
        first_statement=CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
        first_parameters=consume_first_parameters,
        second_statement=takeover_statement,
        second_parameters=(consume_first_tenant, consume_first_run, uuid4()),
    )
    assert consumed is not None and consumed["status"] == "CONSUMED"
    assert live_takeover is None

    takeover_first_tenant, takeover_first_run = _seed_claimed_run()
    takeover_first_binding = _runtime_permit_binding(
        takeover_first_tenant,
        takeover_first_run,
    )
    takeover_first_permit = uuid4()
    takeover_first_intent = uuid4()
    with psycopg.connect(TEST_DSN) as connection:
        assert connection.execute(
            ISSUE_RUNTIME_EXTERNAL_PERMIT_SQL,
            (
                takeover_first_tenant,
                takeover_first_run,
                "worker-a",
                1,
                takeover_first_permit,
                "ADMISSION_RESOLVE",
                takeover_first_intent,
                "d" * 64,
                30,
                uuid4(),
            ),
        ).fetchone() is not None
        connection.execute(
            """
            UPDATE deer_runtime.runtime_run
               SET heartbeat_at = CLOCK_TIMESTAMP() - INTERVAL '2 seconds',
                   lease_until = CLOCK_TIMESTAMP() - INTERVAL '1 second'
             WHERE tenant_id = %s AND runtime_run_id = %s
            """,
            (takeover_first_tenant, takeover_first_run),
        )
    stale_consume_parameters = (
        takeover_first_tenant,
        takeover_first_permit,
        takeover_first_run,
        takeover_first_binding["task_execution_generation"],
        "worker-a",
        1,
        takeover_first_binding["admission_snapshot_id"],
        takeover_first_binding["admission_snapshot_hash"],
        "ADMISSION_RESOLVE",
        takeover_first_intent,
        "d" * 64,
        uuid4(),
        "java-tool-authorizer",
    )
    taken_over, fenced_consume = _invoke_ordered_behind_run_lock(
        tenant_id=takeover_first_tenant,
        runtime_run_id=takeover_first_run,
        first_statement=takeover_statement,
        first_parameters=(takeover_first_tenant, takeover_first_run, uuid4()),
        second_statement=CONSUME_AND_AUTHORIZE_RUNTIME_EXTERNAL_PERMIT_SQL,
        second_parameters=stale_consume_parameters,
    )
    assert taken_over == {
        "runtime_run_id": takeover_first_run,
        "lease_owner": "worker-b",
        "lease_epoch": 2,
    }
    assert fenced_consume is None
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        assert connection.execute(
            """
            SELECT status,
                   (SELECT COUNT(*)
                      FROM deer_runtime.runtime_external_permit_event AS permit_event
                     WHERE permit_event.tenant_id = permit_attempt.tenant_id
                       AND permit_event.runtime_external_permit_id =
                           permit_attempt.runtime_external_permit_id) AS event_count
              FROM deer_runtime.runtime_external_permit_attempt AS permit_attempt
             WHERE tenant_id = %s AND runtime_external_permit_id = %s
            """,
            (takeover_first_tenant, takeover_first_permit),
        ).fetchone() == {"status": "ISSUED", "event_count": 1}


def test_admission_exact_replay_rejects_distinct_active_intent() -> None:
    assert TEST_DSN is not None
    tenant_id = uuid4()
    runtime_thread_id = uuid4()
    task_step_id = uuid4()
    runtime_run_id = uuid4()
    parameters = _admission_parameters(
        tenant_id=tenant_id,
        runtime_thread_id=runtime_thread_id,
        task_step_id=task_step_id,
        runtime_run_id=runtime_run_id,
    )

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        first = connection.execute(ADMIT_RUNTIME_RUN_SQL, parameters).fetchone()
        replayed = connection.execute(ADMIT_RUNTIME_RUN_SQL, parameters).fetchone()
        assert first == replayed == {
            "runtime_run_id": runtime_run_id,
            "runtime_thread_id": runtime_thread_id,
            "status": "QUEUED",
            "run_version": 1,
            "next_event_sequence_no": 2,
            "lease_epoch": 0,
            "attempt": 0,
        }

        distinct_active_parameters = list(parameters)
        distinct_active_parameters[17] = uuid4()
        distinct_active_parameters[18] = 2
        distinct_active_parameters[22] = f"admit-{distinct_active_parameters[17]}"
        distinct_active_parameters[28] = uuid4()
        distinct_active_parameters[30] = uuid4()
        assert connection.execute(
            ADMIT_RUNTIME_RUN_SQL,
            tuple(distinct_active_parameters),
        ).fetchone() is None

        connection.commit()

    with psycopg.connect(TEST_DSN) as connection:
        conflicting_parameters = list(parameters)
        conflicting_parameters[21] = "b" * 64
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(ADMIT_RUNTIME_RUN_SQL, tuple(conflicting_parameters)).fetchone()
        connection.rollback()

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        facts = connection.execute(
            """
            SELECT runtime_run.status,
                   COUNT(runtime_run_event.event_id) AS event_count,
                   MIN(runtime_run_event.event_type) AS event_type,
                   MIN(admission_ref.admission_contract_version) AS admission_contract_version,
                   MIN(admission_ref.admission_snapshot_id::TEXT)::UUID AS admission_snapshot_id,
                   MIN(admission_ref.admission_snapshot_hash) AS admission_snapshot_hash
              FROM deer_runtime.runtime_run
              JOIN deer_runtime.runtime_run_event USING (tenant_id, runtime_run_id)
              JOIN deer_runtime.runtime_execution_admission_ref AS admission_ref
                USING (tenant_id, runtime_run_id)
             WHERE runtime_run.tenant_id = %s
               AND runtime_run.runtime_run_id = %s
             GROUP BY runtime_run.tenant_id, runtime_run.runtime_run_id
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()
        assert facts == {
            "status": "QUEUED",
            "event_count": 1,
            "event_type": "RUN_ACCEPTED",
            "admission_contract_version": parameters[27],
            "admission_snapshot_id": parameters[28],
            "admission_snapshot_hash": parameters[29],
        }


def test_admission_receipt_conflicts_roll_back_atomically_and_is_append_only() -> None:
    assert TEST_DSN is not None
    parameters = _admission_parameters()
    tenant_id = parameters[0]
    runtime_run_id = parameters[17]
    snapshot_id = parameters[28]
    with psycopg.connect(TEST_DSN) as connection:
        assert connection.execute(ADMIT_RUNTIME_RUN_SQL, parameters).fetchone() is not None

    for index, conflicting_value in (
        (28, uuid4()),
        (29, "e" * 64),
    ):
        conflicting_parameters = list(parameters)
        conflicting_parameters[index] = conflicting_value
        with psycopg.connect(TEST_DSN) as connection:
            with pytest.raises(psycopg.errors.UniqueViolation):
                connection.execute(
                    ADMIT_RUNTIME_RUN_SQL,
                    tuple(conflicting_parameters),
                ).fetchone()

    unsupported_parameters = list(parameters)
    unsupported_parameters[27] = "2.1"
    with psycopg.connect(TEST_DSN) as connection:
        with pytest.raises(psycopg.errors.FeatureNotSupported):
            connection.execute(
                ADMIT_RUNTIME_RUN_SQL,
                tuple(unsupported_parameters),
            ).fetchone()

    colliding_parameters = _admission_parameters(admission_snapshot_id=snapshot_id)
    colliding_tenant_id = colliding_parameters[0]
    colliding_thread_id = colliding_parameters[1]
    colliding_run_id = colliding_parameters[17]
    colliding_event_id = colliding_parameters[30]
    with psycopg.connect(TEST_DSN) as connection:
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(ADMIT_RUNTIME_RUN_SQL, colliding_parameters).fetchone()
        connection.rollback()
        assert connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM deer_runtime.runtime_thread
                  WHERE tenant_id = %s AND runtime_thread_id = %s),
                (SELECT COUNT(*) FROM deer_runtime.runtime_run
                  WHERE tenant_id = %s AND runtime_run_id = %s),
                (SELECT COUNT(*) FROM deer_runtime.runtime_execution_admission_ref
                  WHERE tenant_id = %s AND runtime_run_id = %s),
                (SELECT COUNT(*) FROM deer_runtime.runtime_run_event
                  WHERE tenant_id = %s AND event_id = %s)
            """,
            (
                colliding_tenant_id,
                colliding_thread_id,
                colliding_tenant_id,
                colliding_run_id,
                colliding_tenant_id,
                colliding_run_id,
                colliding_tenant_id,
                colliding_event_id,
            ),
        ).fetchone() == (0, 0, 0, 0)

    for statement in (
        """
        UPDATE deer_runtime.runtime_execution_admission_ref
           SET admission_snapshot_hash = %s
         WHERE tenant_id = %s AND runtime_run_id = %s
        """,
        """
        DELETE FROM deer_runtime.runtime_execution_admission_ref
         WHERE tenant_id = %s AND runtime_run_id = %s
        """,
            "TRUNCATE deer_runtime.runtime_execution_admission_ref CASCADE",
    ):
        with psycopg.connect(TEST_DSN) as connection:
            parameters_for_statement: tuple[Any, ...]
            if statement.lstrip().startswith("UPDATE"):
                parameters_for_statement = ("d" * 64, tenant_id, runtime_run_id)
            elif statement.lstrip().startswith("DELETE"):
                parameters_for_statement = (tenant_id, runtime_run_id)
            else:
                parameters_for_statement = ()
            with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState):
                connection.execute(statement, parameters_for_statement)

    with psycopg.connect(TEST_DSN) as connection:
        signatures = connection.execute(
            """
            SELECT
                TO_REGPROCEDURE(
                    'deer_runtime.admit_runtime_run(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,bigint,varchar,varchar,uuid,uuid,uuid,uuid,jsonb,uuid,bigint,varchar,varchar,character,varchar,uuid,varchar,varchar,varchar,uuid,jsonb)'
                ) IS NULL,
                TO_REGPROCEDURE(
                    'deer_runtime.admit_runtime_run(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,bigint,varchar,varchar,uuid,uuid,uuid,uuid,jsonb,uuid,bigint,varchar,varchar,character,varchar,uuid,varchar,varchar,varchar,varchar,uuid,character,uuid,jsonb)'
                ) IS NULL,
                TO_REGPROCEDURE(
                    'deer_runtime.admit_runtime_run(uuid,uuid,uuid,uuid,uuid,uuid,varchar,uuid,uuid,bigint,varchar,varchar,uuid,uuid,uuid,uuid,jsonb,uuid,bigint,varchar,varchar,character,varchar,uuid,varchar,varchar,varchar,varchar,uuid,character,uuid,jsonb)'
                ) IS NOT NULL,
                TO_REGPROCEDURE(
                    'deer_runtime.select_next_runtime_run_candidate(varchar,varchar)'
                ) IS NULL,
                TO_REGPROCEDURE(
                    'deer_runtime.select_next_runtime_run_candidate(varchar,varchar,varchar)'
                ) IS NOT NULL
            """
        ).fetchone()
        assert signatures == (True, True, True, True, True)


def test_admission_serializes_competing_threads_for_one_step_revision() -> None:
    assert TEST_DSN is not None
    tenant_id = uuid4()
    task_run_id = uuid4()
    task_step_id = uuid4()
    first_parameters = _admission_parameters(
        tenant_id=tenant_id,
        task_run_id=task_run_id,
        task_step_id=task_step_id,
    )
    second_parameters = _admission_parameters(
        tenant_id=tenant_id,
        task_run_id=task_run_id,
        task_step_id=task_step_id,
    )
    ready = Barrier(3)

    def admit(parameters: tuple[Any, ...]) -> tuple[str, UUID | None]:
        try:
            with psycopg.connect(TEST_DSN) as connection:
                ready.wait(timeout=5)
                row = connection.execute(ADMIT_RUNTIME_RUN_SQL, parameters).fetchone()
                return "admitted", row[0] if row else None
        except psycopg.errors.UniqueViolation:
            return "conflict", None

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(admit, first_parameters)
        second = executor.submit(admit, second_parameters)
        ready.wait(timeout=5)
        outcomes = [first.result(timeout=5), second.result(timeout=5)]

    assert sorted(outcome[0] for outcome in outcomes) == ["admitted", "conflict"]
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        facts = connection.execute(
            """
            SELECT COUNT(DISTINCT runtime_thread.runtime_thread_id) AS thread_count,
                   COUNT(DISTINCT runtime_run.runtime_run_id) AS run_count,
                   COUNT(runtime_run_event.event_id) AS event_count
              FROM deer_runtime.runtime_thread
              JOIN deer_runtime.runtime_run USING (tenant_id, runtime_thread_id, task_step_id)
              JOIN deer_runtime.runtime_run_event USING (tenant_id, runtime_run_id, runtime_thread_id)
             WHERE runtime_thread.tenant_id = %s
               AND runtime_thread.task_step_id = %s
               AND runtime_thread.runtime_thread_revision = 1
            """,
            (tenant_id, task_step_id),
        ).fetchone()
        assert facts == {"thread_count": 1, "run_count": 1, "event_count": 1}


def test_only_bound_v22_runs_can_be_discovered_claimed_taken_over_or_loaded() -> None:
    assert TEST_DSN is not None
    runtime_version = f"adapter-{uuid4()}"
    agent_name = f"agent-{uuid4()}"
    bound_parameters = _admission_parameters(
        runtime_version=runtime_version,
        agent_name=agent_name,
    )
    tenant_id = bound_parameters[0]
    bound_run_id = bound_parameters[17]
    legacy_tenant_id = uuid4()
    legacy_thread_id = uuid4()
    legacy_task_step_id = uuid4()
    legacy_run_id = uuid4()

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        connection.execute(ADMIT_RUNTIME_RUN_SQL, bound_parameters).fetchone()
        connection.execute(
            """
            INSERT INTO deer_runtime.runtime_thread (
                tenant_id, runtime_thread_id, task_run_id, task_step_id,
                agent_instance_id, user_id, source_kind, conversation_id, runtime_type,
                runtime_agent_name, capability_version_id, prompt_version_id,
                model_policy_id, budget_reservation_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, 'CONVERSATION', %s, 'DEERFLOW', %s,
                %s, %s, %s, %s
            )
            """,
            (
                legacy_tenant_id,
                legacy_thread_id,
                uuid4(),
                legacy_task_step_id,
                uuid4(),
                uuid4(),
                uuid4(),
                agent_name,
                uuid4(),
                uuid4(),
                uuid4(),
                uuid4(),
            ),
        )
        connection.execute(
            """
            INSERT INTO deer_runtime.runtime_run (
                tenant_id, runtime_run_id, runtime_thread_id, task_step_id,
                task_execution_generation, status, operation_kind,
                multitask_strategy, request_hash, idempotency_key,
                runtime_version, agent_name
            ) VALUES (
                %s, %s, %s, %s, 1, 'QUEUED', 'START', 'REJECT',
                %s, %s, %s, %s
            )
            """,
            (
                legacy_tenant_id,
                legacy_run_id,
                legacy_thread_id,
                legacy_task_step_id,
                "c" * 64,
                f"legacy-{legacy_run_id}",
                runtime_version,
                agent_name,
            ),
        )

        candidate = connection.execute(
            """
            SELECT * FROM deer_runtime.select_next_runtime_run_candidate(
                %s, %s, '2.2'
            )
            """,
            (runtime_version, agent_name),
        ).fetchone()
        assert candidate == {
            "tenant_id": tenant_id,
            "runtime_run_id": bound_run_id,
        }
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            connection.execute(
                """
                SELECT 1 FROM deer_runtime.select_next_runtime_run_candidate(
                    %s, %s, '2.1'
                )
                """,
                (runtime_version, agent_name),
            ).fetchone()
        connection.rollback()

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        connection.execute(ADMIT_RUNTIME_RUN_SQL, bound_parameters).fetchone()
        bound_claim = connection.execute(
            """
            SELECT runtime_run_id, status, lease_epoch
              FROM deer_runtime.claim_runtime_run(
                  %s, %s, 'bound-worker', 60, %s, '{}'::JSONB
              )
            """,
            (tenant_id, bound_run_id, uuid4()),
        ).fetchone()
        assert bound_claim == {
            "runtime_run_id": bound_run_id,
            "status": "RUNNING",
            "lease_epoch": 1,
        }
        assert connection.execute(
            """
            SELECT COUNT(*) AS row_count
              FROM deer_runtime.load_runtime_execution_authority(
                  %s, %s, 'bound-worker', 1
              )
            """,
            (tenant_id, bound_run_id),
        ).fetchone()["row_count"] == 1

        connection.execute(
            """
            INSERT INTO deer_runtime.runtime_thread (
                tenant_id, runtime_thread_id, task_run_id, task_step_id,
                agent_instance_id, user_id, source_kind, conversation_id, runtime_type,
                runtime_agent_name, capability_version_id, prompt_version_id,
                model_policy_id, budget_reservation_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, 'CONVERSATION', %s, 'DEERFLOW', %s,
                %s, %s, %s, %s
            )
            """,
            (
                legacy_tenant_id,
                legacy_thread_id,
                uuid4(),
                legacy_task_step_id,
                uuid4(),
                uuid4(),
                uuid4(),
                agent_name,
                uuid4(),
                uuid4(),
                uuid4(),
                uuid4(),
            ),
        )
        connection.execute(
            """
            INSERT INTO deer_runtime.runtime_run (
                tenant_id, runtime_run_id, runtime_thread_id, task_step_id,
                task_execution_generation, status, operation_kind,
                multitask_strategy, request_hash, idempotency_key,
                runtime_version, agent_name
            ) VALUES (
                %s, %s, %s, %s, 1, 'QUEUED', 'START', 'REJECT',
                %s, %s, %s, %s
            )
            """,
            (
                legacy_tenant_id,
                legacy_run_id,
                legacy_thread_id,
                legacy_task_step_id,
                "c" * 64,
                f"legacy-{legacy_run_id}",
                runtime_version,
                agent_name,
            ),
        )
        assert connection.execute(
            """
            SELECT COUNT(*) AS row_count
              FROM deer_runtime.claim_runtime_run(
                  %s, %s, 'legacy-worker', 60, %s, '{}'::JSONB
              )
            """,
            (legacy_tenant_id, legacy_run_id, uuid4()),
        ).fetchone()["row_count"] == 0

        connection.execute(
            """
            UPDATE deer_runtime.runtime_run
               SET status = 'RUNNING', lease_owner = 'legacy-worker',
                   lease_until = CLOCK_TIMESTAMP() - INTERVAL '1 second',
                   lease_epoch = 1,
                   heartbeat_at = CLOCK_TIMESTAMP() - INTERVAL '2 seconds',
                   attempt = 1,
                   started_at = CLOCK_TIMESTAMP() - INTERVAL '3 seconds',
                   run_version = 2,
                   updated_at = CLOCK_TIMESTAMP()
             WHERE tenant_id = %s AND runtime_run_id = %s
            """,
            (
                legacy_tenant_id,
                legacy_run_id,
            ),
        )
        assert connection.execute(
            """
            SELECT COUNT(*) AS row_count
              FROM deer_runtime.takeover_runtime_run(
                  %s, %s, 'other-worker', 60, %s, '{}'::JSONB
              )
            """,
            (legacy_tenant_id, legacy_run_id, uuid4()),
        ).fetchone()["row_count"] == 0
        assert connection.execute(
            """
            SELECT COUNT(*) AS row_count
              FROM deer_runtime.load_runtime_execution_authority(
                  %s, %s, 'legacy-worker', 1
              )
            """,
            (legacy_tenant_id, legacy_run_id),
        ).fetchone()["row_count"] == 0


def test_exact_progress_and_checkpoint_replays_serialize_on_the_run_row() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    progress_event_id = uuid4()
    progress_statement = """
        SELECT event_id, sequence_no, run_version, lease_owner, lease_epoch
          FROM deer_runtime.append_runtime_run_event(
              %s, %s, 'worker-a', 1::BIGINT, %s,
              'STEP_PROGRESS', 1::SMALLINT, '{"progress":50}'::JSONB
          )
    """
    progress_first, progress_second = _invoke_twice_behind_run_lock(
        tenant_id=tenant_id,
        runtime_run_id=runtime_run_id,
        statement=progress_statement,
        parameters=(tenant_id, runtime_run_id, progress_event_id),
    )
    assert progress_first == progress_second
    assert progress_first == {
        "event_id": progress_event_id,
        "sequence_no": 3,
        "run_version": 3,
        "lease_owner": "worker-a",
        "lease_epoch": 1,
    }

    checkpoint_event_id = uuid4()
    checkpoint_id = f"checkpoint-{uuid4()}"
    checkpoint_statement = """
        SELECT checkpoint_id, sequence_no, event_id, run_version, lease_epoch
          FROM deer_runtime.record_runtime_checkpoint_ref(
              %s, %s, 'worker-a', 1::BIGINT, %s, %s,
              '', 'langgraph-v1', '{"kind":"concurrent"}'::JSONB
          )
    """
    checkpoint_first, checkpoint_second = _invoke_twice_behind_run_lock(
        tenant_id=tenant_id,
        runtime_run_id=runtime_run_id,
        statement=checkpoint_statement,
        parameters=(tenant_id, runtime_run_id, checkpoint_event_id, checkpoint_id),
    )
    assert checkpoint_first == checkpoint_second
    assert checkpoint_first == {
        "checkpoint_id": checkpoint_id,
        "sequence_no": 4,
        "event_id": checkpoint_event_id,
        "run_version": 4,
        "lease_epoch": 1,
    }

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        facts = connection.execute(
            """
            SELECT runtime_run.run_version,
                   runtime_run.next_event_sequence_no,
                   runtime_run.current_checkpoint_id,
                   runtime_run.current_checkpoint_sequence_no,
                   COUNT(runtime_run_event.event_id) AS event_count
              FROM deer_runtime.runtime_run
              JOIN deer_runtime.runtime_run_event USING (tenant_id, runtime_run_id)
             WHERE runtime_run.tenant_id = %s
               AND runtime_run.runtime_run_id = %s
             GROUP BY runtime_run.tenant_id, runtime_run.runtime_run_id
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()
        assert facts == {
            "run_version": 4,
            "next_event_sequence_no": 5,
            "current_checkpoint_id": checkpoint_id,
            "current_checkpoint_sequence_no": 4,
            "event_count": 4,
        }


def test_cancel_wins_before_completion_and_finishes_with_exact_terminal_fact() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    cancel_request_id = uuid4()
    cancelling_event_id = uuid4()
    cancelled_event_id = uuid4()
    completed_event_id = uuid4()

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        control = connection.execute(
            """
            SELECT control_id, control_type, expected_run_version
              FROM deer_runtime.request_runtime_run_cancel(
                  %s, %s, %s, %s, 'USER_REQUESTED', 2, %s, %s,
                  '{"reason":"user-requested"}'::JSONB
              )
            """,
            (
                tenant_id,
                runtime_run_id,
                cancel_request_id,
                uuid4(),
                f"cancel-{cancel_request_id}",
                "b" * 64,
            ),
        ).fetchone()
        assert control == {
            "control_id": cancel_request_id,
            "control_type": "CANCEL",
            "expected_run_version": 2,
        }
        completion_count = connection.execute(
            """
            SELECT COUNT(*) AS row_count
              FROM deer_runtime.complete_runtime_run(
                  %s, %s, 'worker-a', 1, %s, 'NORMAL_COMPLETION', '{}'::JSONB
              )
            """,
            (tenant_id, runtime_run_id, completed_event_id),
        ).fetchone()["row_count"]
        assert completion_count == 0

        cancelling = connection.execute(
            """
            SELECT status, run_version, lease_owner, lease_epoch
              FROM deer_runtime.begin_runtime_run_cancellation(
                  %s, %s, 'worker-a', 1, %s, '{"stage":"stopping"}'::JSONB
              )
            """,
            (tenant_id, runtime_run_id, cancelling_event_id),
        ).fetchone()
        assert cancelling == {
            "status": "CANCELLING",
            "run_version": 4,
            "lease_owner": "worker-a",
            "lease_epoch": 1,
        }

        cancelled = connection.execute(
            """
            SELECT status, run_version, terminal_event_id, terminal_reason,
                   lease_owner, lease_epoch, failure_code
              FROM deer_runtime.finish_runtime_run_cancellation(
                  %s, %s, 'worker-a', 1, 'CANCELLED', %s,
                  'USER_REQUESTED', '{"result":"cancelled"}'::JSONB
              )
            """,
            (tenant_id, runtime_run_id, cancelled_event_id),
        ).fetchone()
        assert cancelled == {
            "status": "CANCELLED",
            "run_version": 5,
            "terminal_event_id": cancelled_event_id,
            "terminal_reason": "USER_REQUESTED",
            "lease_owner": None,
            "lease_epoch": 1,
            "failure_code": None,
        }
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")

        terminal_event = connection.execute(
            """
            SELECT event_type, sequence_no, run_version, lease_owner, lease_epoch
              FROM deer_runtime.runtime_run_event
             WHERE tenant_id = %s AND runtime_run_id = %s AND event_id = %s
            """,
            (tenant_id, runtime_run_id, cancelled_event_id),
        ).fetchone()
        assert terminal_event == {
            "event_type": "RUN_CANCELLED",
            "sequence_no": 5,
            "run_version": 5,
            "lease_owner": "worker-a",
            "lease_epoch": 1,
        }
        assert connection.execute(
            "SELECT COUNT(*) FROM deer_runtime.renew_runtime_run_lease(%s, %s, 'worker-a', 1, 30)",
            (tenant_id, runtime_run_id),
        ).fetchone()["count"] == 0
        assert connection.execute(
            """
            SELECT COUNT(*) FROM deer_runtime.record_runtime_checkpoint_ref(
                %s, %s, 'worker-a', 1, %s, 'after-terminal', '',
                'langgraph-v1', '{}'::JSONB
            )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone()["count"] == 0


def test_completion_wins_before_cancel_and_replays_only_for_original_epoch() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    completed_event_id = uuid4()
    cancel_request_id = uuid4()

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        completed = connection.execute(
            """
            SELECT status, run_version, terminal_event_id, terminal_reason,
                   lease_owner, lease_epoch, failure_code
              FROM deer_runtime.complete_runtime_run(
                  %s, %s, 'worker-a', 1, %s,
                  'NORMAL_COMPLETION', '{"result":"done"}'::JSONB
              )
            """,
            (tenant_id, runtime_run_id, completed_event_id),
        ).fetchone()
        assert completed == {
            "status": "COMPLETED",
            "run_version": 3,
            "terminal_event_id": completed_event_id,
            "terminal_reason": "NORMAL_COMPLETION",
            "lease_owner": None,
            "lease_epoch": 1,
            "failure_code": None,
        }

        replayed = connection.execute(
            """
            SELECT status, run_version, terminal_event_id
              FROM deer_runtime.complete_runtime_run(
                  %s, %s, 'worker-a', 1, %s,
                  'NORMAL_COMPLETION', '{"result":"done"}'::JSONB
              )
            """,
            (tenant_id, runtime_run_id, completed_event_id),
        ).fetchone()
        assert replayed == {
            "status": "COMPLETED",
            "run_version": 3,
            "terminal_event_id": completed_event_id,
        }
        stale_replay_count = connection.execute(
            """
            SELECT COUNT(*) AS row_count
              FROM deer_runtime.complete_runtime_run(
                  %s, %s, 'worker-b', 2, %s,
                  'NORMAL_COMPLETION', '{"result":"done"}'::JSONB
              )
            """,
            (tenant_id, runtime_run_id, completed_event_id),
        ).fetchone()["row_count"]
        assert stale_replay_count == 0

        cancel_count = connection.execute(
            """
            SELECT COUNT(*) AS row_count
              FROM deer_runtime.request_runtime_run_cancel(
                  %s, %s, %s, %s, 'USER_REQUESTED', 3, %s, %s, '{}'::JSONB
              )
            """,
            (
                tenant_id,
                runtime_run_id,
                cancel_request_id,
                uuid4(),
                f"cancel-{cancel_request_id}",
                "c" * 64,
            ),
        ).fetchone()["row_count"]
        assert cancel_count == 0
        connection.execute("SET CONSTRAINTS ALL IMMEDIATE")

        facts = connection.execute(
            """
            SELECT runtime_run.status, runtime_run.run_version,
                   COUNT(runtime_run_event.event_id) AS event_count
              FROM deer_runtime.runtime_run
              JOIN deer_runtime.runtime_run_event USING (tenant_id, runtime_run_id)
             WHERE runtime_run.tenant_id = %s AND runtime_run.runtime_run_id = %s
             GROUP BY runtime_run.tenant_id, runtime_run.runtime_run_id
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()
        assert facts == {"status": "COMPLETED", "run_version": 3, "event_count": 3}


def test_cancel_and_completion_race_has_exactly_one_winner() -> None:
    assert TEST_DSN is not None
    tenant_id, runtime_run_id = _seed_claimed_run()
    cancel_request_id = uuid4()
    completed_event_id = uuid4()
    actor_id = uuid4()
    cancel_key = f"cancel-{cancel_request_id}"

    cancel_result, completion_result = _race_statements_behind_run_lock(
        tenant_id=tenant_id,
        runtime_run_id=runtime_run_id,
        first_statement="""
            SELECT COUNT(*) AS row_count
              FROM deer_runtime.request_runtime_run_cancel(
                  %s, %s, %s, %s, 'USER_REQUESTED', 2, %s, %s,
                  '{"reason":"race"}'::JSONB
              )
        """,
        first_parameters=(
            tenant_id,
            runtime_run_id,
            cancel_request_id,
            actor_id,
            cancel_key,
            "d" * 64,
        ),
        second_statement="""
            SELECT COUNT(*) AS row_count
              FROM deer_runtime.complete_runtime_run(
                  %s, %s, 'worker-a', 1, %s,
                  'NORMAL_COMPLETION', '{"result":"race"}'::JSONB
              )
        """,
        second_parameters=(tenant_id, runtime_run_id, completed_event_id),
    )
    assert cancel_result["row_count"] + completion_result["row_count"] == 1

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        run = connection.execute(
            """
            SELECT status, run_version, terminal_event_id, cancel_requested_at IS NOT NULL AS cancel_requested
              FROM deer_runtime.runtime_run
             WHERE tenant_id = %s AND runtime_run_id = %s
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()
        event_types = {
            row["event_type"]
            for row in connection.execute(
                """
                SELECT event_type
                  FROM deer_runtime.runtime_run_event
                 WHERE tenant_id = %s AND runtime_run_id = %s
                """,
                (tenant_id, runtime_run_id),
            ).fetchall()
        }
        control_count = connection.execute(
            """
            SELECT COUNT(*) AS row_count
              FROM deer_runtime.runtime_run_control
             WHERE tenant_id = %s AND runtime_run_id = %s
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()["row_count"]

        if cancel_result["row_count"] == 1:
            assert run == {
                "status": "CANCEL_REQUESTED",
                "run_version": 3,
                "terminal_event_id": None,
                "cancel_requested": True,
            }
            assert event_types == {"RUN_ACCEPTED", "RUN_STARTED", "RUN_CANCEL_REQUESTED"}
            assert control_count == 1
        else:
            assert run == {
                "status": "COMPLETED",
                "run_version": 3,
                "terminal_event_id": completed_event_id,
                "cancel_requested": False,
            }
            assert event_types == {"RUN_ACCEPTED", "RUN_STARTED", "RUN_COMPLETED"}
            assert control_count == 0


def test_execution_and_cancellation_authority_are_state_and_fence_exclusive() -> None:
    assert TEST_DSN is not None
    admission_parameters = _admission_parameters()
    tenant_id = admission_parameters[0]
    runtime_thread_id = admission_parameters[1]
    task_run_id = admission_parameters[2]
    task_step_id = admission_parameters[3]
    runtime_run_id = admission_parameters[17]
    cancel_request_id = uuid4()

    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        connection.execute(ADMIT_RUNTIME_RUN_SQL, admission_parameters).fetchone()
        connection.execute(
            """
            SELECT 1
              FROM deer_runtime.claim_runtime_run(
                  %s, %s, 'worker-authority', 60, %s, '{}'::JSONB
              )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone()

        execution = connection.execute(
            """
            SELECT *
              FROM deer_runtime.load_runtime_execution_authority(
                  %s, %s, 'worker-authority', 1
              )
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()
        assert execution is not None
        assert list(execution) == [
            "tenant_id",
            "runtime_run_id",
            "runtime_thread_id",
            "task_run_id",
            "task_step_id",
            "task_execution_generation",
            "agent_instance_id",
            "user_id",
            "conversation_id",
            "source_kind",
            "source_message_id",
            "runtime_thread_revision",
            "runtime_type",
            "runtime_agent_name",
            "capability_version_id",
            "prompt_version_id",
            "model_policy_id",
            "budget_reservation_id",
            "operation_kind",
            "multitask_strategy",
            "request_hash",
            "idempotency_key",
            "predecessor_runtime_run_id",
            "expected_checkpoint_id",
            "runtime_version",
            "agent_name",
            "lease_owner",
            "lease_epoch",
            "admission_contract_version",
            "admission_snapshot_id",
            "admission_snapshot_hash",
        ]
        assert execution == {
            "tenant_id": tenant_id,
            "runtime_run_id": runtime_run_id,
            "runtime_thread_id": runtime_thread_id,
            "task_run_id": task_run_id,
            "task_step_id": task_step_id,
            "task_execution_generation": admission_parameters[18],
            "agent_instance_id": admission_parameters[4],
            "user_id": admission_parameters[5],
            "source_kind": admission_parameters[6],
            "conversation_id": admission_parameters[7],
            "source_message_id": admission_parameters[8],
            "runtime_thread_revision": admission_parameters[9],
            "runtime_type": admission_parameters[10],
            "runtime_agent_name": admission_parameters[11],
            "capability_version_id": admission_parameters[12],
            "prompt_version_id": admission_parameters[13],
            "model_policy_id": admission_parameters[14],
            "budget_reservation_id": admission_parameters[15],
            "operation_kind": admission_parameters[19],
            "multitask_strategy": admission_parameters[20],
            "request_hash": admission_parameters[21],
            "idempotency_key": admission_parameters[22],
            "predecessor_runtime_run_id": admission_parameters[23],
            "expected_checkpoint_id": admission_parameters[24],
            "runtime_version": admission_parameters[25],
            "agent_name": admission_parameters[26],
            "lease_owner": "worker-authority",
            "lease_epoch": 1,
            "admission_contract_version": admission_parameters[27],
            "admission_snapshot_id": admission_parameters[28],
            "admission_snapshot_hash": admission_parameters[29],
        }
        assert connection.execute(
            """
            SELECT COUNT(*) AS row_count
              FROM deer_runtime.authorize_runtime_run_cancellation(
                  %s, %s, 'worker-authority', 1
              )
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()["row_count"] == 0
        for owner, epoch in (("wrong-worker", 1), ("worker-authority", 2)):
            assert connection.execute(
                """
                SELECT COUNT(*) AS row_count
                  FROM deer_runtime.load_runtime_execution_authority(
                      %s, %s, %s, %s
                  )
                """,
                (tenant_id, runtime_run_id, owner, epoch),
            ).fetchone()["row_count"] == 0

        connection.execute(
            """
            SELECT 1
              FROM deer_runtime.request_runtime_run_cancel(
                  %s, %s, %s, %s, 'USER_REQUESTED', 2, %s, %s, '{}'::JSONB
              )
            """,
            (
                tenant_id,
                runtime_run_id,
                cancel_request_id,
                uuid4(),
                f"cancel-{cancel_request_id}",
                "e" * 64,
            ),
        ).fetchone()
        for function_name in (
            "load_runtime_execution_authority",
            "authorize_runtime_run_cancellation",
        ):
            assert connection.execute(
                f"""
                SELECT COUNT(*) AS row_count
                  FROM deer_runtime.{function_name}(
                      %s, %s, 'worker-authority', 1
                  )
                """,
                (tenant_id, runtime_run_id),
            ).fetchone()["row_count"] == 0

        connection.execute(
            """
            SELECT 1
              FROM deer_runtime.begin_runtime_run_cancellation(
                  %s, %s, 'worker-authority', 1, %s, '{}'::JSONB
              )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone()
        cancellation = connection.execute(
            """
            SELECT *
              FROM deer_runtime.authorize_runtime_run_cancellation(
                  %s, %s, 'worker-authority', 1
              )
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()
        assert cancellation is not None
        assert list(cancellation) == [
            "tenant_id",
            "runtime_run_id",
            "runtime_thread_id",
            "task_step_id",
            "task_execution_generation",
            "status",
            "lease_owner",
            "lease_epoch",
            "run_version",
            "cancel_requested_at",
        ]
        assert cancellation["tenant_id"] == tenant_id
        assert cancellation["runtime_run_id"] == runtime_run_id
        assert cancellation["runtime_thread_id"] == runtime_thread_id
        assert cancellation["task_step_id"] == task_step_id
        assert cancellation["task_execution_generation"] == 1
        assert cancellation["status"] == "CANCELLING"
        assert cancellation["lease_owner"] == "worker-authority"
        assert cancellation["lease_epoch"] == 1
        assert cancellation["run_version"] == 4
        assert cancellation["cancel_requested_at"] is not None
        assert connection.execute(
            """
            SELECT COUNT(*) AS row_count
              FROM deer_runtime.load_runtime_execution_authority(
                  %s, %s, 'worker-authority', 1
              )
            """,
            (tenant_id, runtime_run_id),
        ).fetchone()["row_count"] == 0
        for owner, epoch in (("wrong-worker", 1), ("worker-authority", 2)):
            assert connection.execute(
                """
                SELECT COUNT(*) AS row_count
                  FROM deer_runtime.authorize_runtime_run_cancellation(
                      %s, %s, %s, %s
                  )
                """,
                (tenant_id, runtime_run_id, owner, epoch),
            ).fetchone()["row_count"] == 0

        connection.execute(
            """
            SELECT 1
              FROM deer_runtime.finish_runtime_run_cancellation(
                  %s, %s, 'worker-authority', 1, 'CANCELLED', %s,
                  'USER_REQUESTED', '{}'::JSONB
              )
            """,
            (tenant_id, runtime_run_id, uuid4()),
        ).fetchone()
        for function_name in (
            "load_runtime_execution_authority",
            "authorize_runtime_run_cancellation",
        ):
            assert connection.execute(
                f"""
                SELECT COUNT(*) AS row_count
                  FROM deer_runtime.{function_name}(
                      %s, %s, 'worker-authority', 1
                  )
                """,
                (tenant_id, runtime_run_id),
            ).fetchone()["row_count"] == 0

    expired_tenant_id, expired_run_id = _seed_claimed_run()
    with psycopg.connect(TEST_DSN, row_factory=dict_row) as connection:
        connection.execute(
            """
            UPDATE deer_runtime.runtime_run
               SET heartbeat_at = CLOCK_TIMESTAMP() - INTERVAL '2 seconds',
                   lease_until = CLOCK_TIMESTAMP() - INTERVAL '1 second'
             WHERE tenant_id = %s AND runtime_run_id = %s
            """,
            (expired_tenant_id, expired_run_id),
        )
        for function_name in (
            "load_runtime_execution_authority",
            "authorize_runtime_run_cancellation",
        ):
            assert connection.execute(
                f"""
                SELECT COUNT(*) AS row_count
                  FROM deer_runtime.{function_name}(
                      %s, %s, 'worker-a', 1
                  )
                """,
                (expired_tenant_id, expired_run_id),
            ).fetchone()["row_count"] == 0

    for function_name in (
        "load_runtime_execution_authority",
        "authorize_runtime_run_cancellation",
    ):
        with psycopg.connect(TEST_DSN) as connection:
            with pytest.raises(psycopg.errors.InvalidParameterValue):
                connection.execute(
                    f"""
                    SELECT 1 FROM deer_runtime.{function_name}(
                        NULL::UUID, %s, 'worker-a', 1
                    )
                    """,
                    (expired_run_id,),
                ).fetchone()

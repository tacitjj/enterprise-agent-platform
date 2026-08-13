from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from dianlian_runtime.harness import DeerFlowH0Runtime, StartExecutionRequest


UPSTREAM_ROOT = os.getenv("DIANLIAN_DEERFLOW_SOURCE_ROOT")


@pytest.mark.skipif(
    not UPSTREAM_ROOT,
    reason="set DIANLIAN_DEERFLOW_SOURCE_ROOT to the pinned DeerFlow checkout",
)
def test_h0_persists_mapping_events_checkpoint_guidance_and_restart(
    tmp_path: Path,
) -> None:
    asyncio.run(_run_h0_smoke(tmp_path))


async def _run_h0_smoke(tmp_path: Path) -> None:
    request = StartExecutionRequest(
        execution_id="execution-h0-001",
        idempotency_key="h0-smoke-key",
        thread_id="thread-h0-001",
        request_hash="request-hash-h0-001",
        prompt="draft a deterministic H0 result",
    )

    async with DeerFlowH0Runtime(
        data_dir=tmp_path,
        upstream_root=Path(UPSTREAM_ROOT),
    ) as runtime:
        waiting = await runtime.start_execution(request)
        repeated = await runtime.start_execution(request)

        assert waiting.status == "WAITING_GUIDANCE"
        assert waiting.checkpoint_id
        assert repeated.deerflow_run_id == waiting.deerflow_run_id

        completed = await runtime.guide(
            request.execution_id,
            expected_checkpoint_id=waiting.checkpoint_id,
            guidance="continue deterministically",
        )
        events = await runtime.stream_events(request.execution_id)

        assert completed.status == "SUCCEEDED"
        assert completed.result == (
            "draft a deterministic H0 result | guidance=continue deterministically"
        )
        assert [event.event_type for event in events] == [
            "dianlian.h0.started",
            "dianlian.h0.checkpoint",
            "dianlian.h0.completed",
        ]

        cancel_request = StartExecutionRequest(
            execution_id="execution-h0-002",
            idempotency_key="h0-cancel-key",
            thread_id="thread-h0-002",
            request_hash="request-hash-h0-002",
            prompt="wait for cancellation",
        )
        await runtime.start_execution(cancel_request)
        cancelled = await runtime.cancel(cancel_request.execution_id)

        assert cancelled.status == "INTERRUPTED"
        assert cancelled.cancel_action == "interrupt"

    async with DeerFlowH0Runtime(
        data_dir=tmp_path,
        upstream_root=Path(UPSTREAM_ROOT),
    ) as restarted:
        restored = await restarted.get_execution(request.execution_id)
        repeated_after_restart = await restarted.start_execution(request)
        replayed = await restarted.stream_events(request.execution_id)

        assert restored == completed
        assert repeated_after_restart.deerflow_run_id == completed.deerflow_run_id
        assert [event.sequence for event in replayed] == [1, 2, 3]

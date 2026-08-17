from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from dianlian_runtime.supervisor.contracts import (
    ExternalOperation,
    ExternalPermitStatus,
    IssueRuntimeExternalPermitRequest,
    MultitaskStrategy,
    OperationKind,
    PrimitiveOutcome,
    PrimitiveResult,
    RuntimeExecutionAuthorityFact,
    RuntimeExternalPermitFact,
    SupervisorErrorCode,
    SupervisorPrimitive,
    SupervisorUnavailable,
)
from dianlian_runtime.supervisor.driver import DriverFence
from dianlian_runtime.supervisor.tool_permit_issuer import (
    DormantToolPermitIssuer,
    IssueToolPermitRequest,
    ToolPermitDisposition,
    ToolPermitFenceRequired,
    ToolPermitOutcomeUnknown,
    derive_tool_permit_identities,
)


TENANT_ID = UUID("b1000000-0000-4000-8000-000000000001")
RUN_ID = UUID("b1000000-0000-4000-8000-000000000002")
THREAD_ID = UUID("b1000000-0000-4000-8000-000000000003")
STEP_ID = UUID("b1000000-0000-4000-8000-000000000004")
INTENT_ID = UUID("b1000000-0000-4000-8000-000000000005")
ADMISSION_ID = UUID("b1000000-0000-4000-8000-000000000006")
NOW = datetime(2026, 8, 14, 1, 0, tzinfo=timezone.utc)
REQUEST_HASH = "a" * 64
ADMISSION_HASH = "b" * 64


def _authority(*, lease_owner: str = "worker:current", lease_epoch: int = 7):
    return RuntimeExecutionAuthorityFact(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        runtime_thread_id=THREAD_ID,
        task_run_id=UUID("b1000000-0000-4000-8000-000000000007"),
        task_step_id=STEP_ID,
        task_execution_generation=3,
        agent_instance_id=UUID("b1000000-0000-4000-8000-000000000008"),
        user_id=UUID("b1000000-0000-4000-8000-000000000009"),
        conversation_id=UUID("b1000000-0000-4000-8000-00000000000a"),
        source_message_id=None,
        runtime_thread_revision=1,
        runtime_type="DEERFLOW",
        runtime_agent_name="runtime-agent",
        capability_version_id=UUID("b1000000-0000-4000-8000-00000000000b"),
        prompt_version_id=UUID("b1000000-0000-4000-8000-00000000000c"),
        model_policy_id=UUID("b1000000-0000-4000-8000-00000000000d"),
        budget_reservation_id=UUID("b1000000-0000-4000-8000-00000000000e"),
        operation_kind=OperationKind.START,
        multitask_strategy=MultitaskStrategy.REJECT,
        request_hash="c" * 64,
        idempotency_key="run-intent",
        predecessor_runtime_run_id=None,
        expected_checkpoint_id=None,
        runtime_version="runtime-v1",
        agent_name="agent-v1",
        lease_owner=lease_owner,
        lease_epoch=lease_epoch,
        admission_contract_version="2.2",
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=ADMISSION_HASH,
    )


def _request() -> IssueToolPermitRequest:
    authority = _authority()
    return IssueToolPermitRequest(
        authority,
        DriverFence(
            authority.tenant_id,
            authority.runtime_run_id,
            authority.task_execution_generation,
            authority.lease_owner,
            authority.lease_epoch,
            authority.admission_contract_version,
            authority.admission_snapshot_id,
            authority.admission_snapshot_hash,
        ),
        INTENT_ID,
        REQUEST_HASH,
        30,
    )


def _fact(
    command: IssueRuntimeExternalPermitRequest,
    *,
    status: ExternalPermitStatus = ExternalPermitStatus.ISSUED,
) -> RuntimeExternalPermitFact:
    consumed = status == ExternalPermitStatus.CONSUMED
    identities = derive_tool_permit_identities(
        tenant_id=command.tenant_id,
        runtime_run_id=command.runtime_run_id,
        task_execution_generation=3,
        lease_owner=command.lease_owner,
        lease_epoch=command.lease_epoch,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=ADMISSION_HASH,
        intent_id=command.intent_id,
        request_hash=command.request_hash,
    )
    issued_at = NOW - timedelta(seconds=10)
    consumed_at = NOW - timedelta(seconds=1) if consumed else None
    return RuntimeExternalPermitFact(
        tenant_id=command.tenant_id,
        runtime_external_permit_id=command.runtime_external_permit_id,
        runtime_run_id=command.runtime_run_id,
        runtime_thread_id=THREAD_ID,
        task_step_id=STEP_ID,
        task_execution_generation=3,
        admission_contract_version="2.2",
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=ADMISSION_HASH,
        operation_kind=command.operation_kind,
        intent_id=command.intent_id,
        request_hash=command.request_hash,
        lease_owner=command.lease_owner,
        lease_epoch=command.lease_epoch,
        permit_attempt=1,
        status=status,
        requested_ttl_seconds=command.requested_ttl_seconds,
        issued_at=issued_at,
        expires_at=issued_at + timedelta(seconds=command.requested_ttl_seconds),
        issue_event_id=command.issue_event_id,
        consume_event_id=identities.arm_event_id if consumed else None,
        consumed_by="dianlian-platform" if consumed else None,
        consumed_at=consumed_at,
        updated_at=consumed_at or issued_at,
    )


class _Repository:
    def __init__(self, result_factory):
        self.result_factory = result_factory
        self.calls: list[IssueRuntimeExternalPermitRequest] = []

    def issue_external_permit(self, request):
        self.calls.append(request)
        return self.result_factory(request)


def test_tool_identities_are_stable_and_bind_the_full_authority() -> None:
    common = dict(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        task_execution_generation=3,
        lease_owner="worker:current",
        lease_epoch=7,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=ADMISSION_HASH,
        intent_id=INTENT_ID,
        request_hash=REQUEST_HASH,
    )

    first = derive_tool_permit_identities(**common)
    assert first == derive_tool_permit_identities(**common)
    assert first != derive_tool_permit_identities(
        **{**common, "lease_epoch": 8}
    )
    assert first != derive_tool_permit_identities(
        **{**common, "admission_snapshot_hash": "d" * 64}
    )
    assert first != derive_tool_permit_identities(
        **{**common, "request_hash": "e" * 64}
    )


def test_current_issued_fact_returns_the_only_dispatchable_receipt() -> None:
    repository = _Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            _fact(command),
        )
    )
    result = DormantToolPermitIssuer(repository, clock=lambda: NOW).issue(
        _request()
    )

    assert result.disposition == ToolPermitDisposition.CURRENT_ISSUED
    assert result.tool_dispatch_allowed is True
    assert result.receipt.operation_kind == ExternalOperation.TOOL_INVOKE
    assert result.receipt.intent_id == INTENT_ID
    assert len(repository.calls) == 1


def test_historical_consumed_fact_is_exact_but_never_dispatchable() -> None:
    def historical(command: IssueRuntimeExternalPermitRequest):
        old = derive_tool_permit_identities(
            tenant_id=command.tenant_id,
            runtime_run_id=command.runtime_run_id,
            task_execution_generation=3,
            lease_owner="worker:old",
            lease_epoch=6,
            admission_snapshot_id=ADMISSION_ID,
            admission_snapshot_hash=ADMISSION_HASH,
            intent_id=command.intent_id,
            request_hash=command.request_hash,
        )
        old_command = replace(
            command,
            lease_owner="worker:old",
            lease_epoch=6,
            runtime_external_permit_id=old.runtime_external_permit_id,
            issue_event_id=old.issue_event_id,
        )
        return PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            _fact(old_command, status=ExternalPermitStatus.CONSUMED),
        )

    result = DormantToolPermitIssuer(
        _Repository(historical),
        clock=lambda: NOW,
    ).issue(_request())

    assert result.disposition == ToolPermitDisposition.HISTORICAL_CONSUMED
    assert result.tool_dispatch_allowed is False
    assert result.receipt.lease_epoch == 6


@pytest.mark.parametrize(
    "result_factory",
    [
        lambda _command: PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None),
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            replace(_fact(command), operation_kind=ExternalOperation.MODEL_INVOKE),
        ),
        lambda _command: (_ for _ in ()).throw(RuntimeError("database lost")),
    ],
)
def test_unknown_or_mismatched_facts_fail_closed(result_factory) -> None:
    repository = _Repository(result_factory)

    with pytest.raises(ToolPermitFenceRequired):
        DormantToolPermitIssuer(repository, clock=lambda: NOW).issue(_request())
    assert len(repository.calls) == 1


def test_typed_repository_unavailability_has_recoverable_outcome_semantics() -> None:
    failure = SupervisorUnavailable(
        SupervisorErrorCode.UNAVAILABLE,
        SupervisorPrimitive.ISSUE_EXTERNAL_PERMIT,
        "08001",
        "unavailable",
    )
    repository = _Repository(
        lambda _command: (_ for _ in ()).throw(failure)
    )

    with pytest.raises(ToolPermitOutcomeUnknown):
        DormantToolPermitIssuer(repository, clock=lambda: NOW).issue(_request())

    assert len(repository.calls) == 1

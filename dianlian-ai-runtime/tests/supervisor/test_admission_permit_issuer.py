from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from dianlian_runtime.supervisor.admission_permit_issuer import (
    ADMISSION_PERMIT_FENCE_REQUIRED,
    ADMISSION_PERMIT_OUTCOME_UNKNOWN,
    AdmissionPermitDisposition,
    AdmissionPermitFenceRequired,
    AdmissionPermitOutcomeUnknown,
    DormantAdmissionPermitIssuer,
    IssueAdmissionPermitRequest,
    derive_admission_permit_identities,
)
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
    SupervisorOutcomeUnknown,
    SupervisorPrimitive,
)
from dianlian_runtime.supervisor.driver import DriverFence


TENANT_ID = UUID("b1000000-0000-4000-8000-000000000001")
RUN_ID = UUID("b1000000-0000-4000-8000-000000000002")
THREAD_ID = UUID("b1000000-0000-4000-8000-000000000003")
TASK_ID = UUID("b1000000-0000-4000-8000-000000000004")
STEP_ID = UUID("b1000000-0000-4000-8000-000000000005")
ADMISSION_ID = UUID("b1000000-0000-4000-8000-000000000006")
NOW = datetime(2026, 8, 14, 2, 0, 10, tzinfo=timezone.utc)
ADMISSION_HASH = "c" * 64


def authority(
    *,
    lease_owner: str = "worker:current",
    lease_epoch: int = 7,
) -> RuntimeExecutionAuthorityFact:
    return RuntimeExecutionAuthorityFact(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        runtime_thread_id=THREAD_ID,
        task_run_id=TASK_ID,
        task_step_id=STEP_ID,
        task_execution_generation=3,
        agent_instance_id=UUID("b1000000-0000-4000-8000-000000000007"),
        user_id=UUID("b1000000-0000-4000-8000-000000000008"),
        conversation_id=UUID("b1000000-0000-4000-8000-000000000009"),
        source_message_id=None,
        runtime_thread_revision=1,
        runtime_type="DEERFLOW",
        runtime_agent_name="runtime-agent",
        capability_version_id=UUID("b1000000-0000-4000-8000-00000000000a"),
        prompt_version_id=UUID("b1000000-0000-4000-8000-00000000000b"),
        model_policy_id=UUID("b1000000-0000-4000-8000-00000000000c"),
        budget_reservation_id=UUID("b1000000-0000-4000-8000-00000000000d"),
        operation_kind=OperationKind.START,
        multitask_strategy=MultitaskStrategy.REJECT,
        request_hash="d" * 64,
        idempotency_key="admission-run-intent",
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


def issue_request(
    execution_authority: RuntimeExecutionAuthorityFact | None = None,
) -> IssueAdmissionPermitRequest:
    execution_authority = execution_authority or authority()
    return IssueAdmissionPermitRequest(
        authority=execution_authority,
        fence=DriverFence(
            tenant_id=execution_authority.tenant_id,
            runtime_run_id=execution_authority.runtime_run_id,
            task_execution_generation=execution_authority.task_execution_generation,
            lease_owner=execution_authority.lease_owner,
            lease_epoch=execution_authority.lease_epoch,
            admission_contract_version=execution_authority.admission_contract_version,
            admission_snapshot_id=execution_authority.admission_snapshot_id,
            admission_snapshot_hash=execution_authority.admission_snapshot_hash,
        ),
        requested_ttl_seconds=30,
    )


def permit_fact(
    command: IssueRuntimeExternalPermitRequest,
    *,
    status: ExternalPermitStatus = ExternalPermitStatus.ISSUED,
    execution_authority: RuntimeExecutionAuthorityFact | None = None,
) -> RuntimeExternalPermitFact:
    execution_authority = execution_authority or authority(
        lease_owner=command.lease_owner,
        lease_epoch=command.lease_epoch,
    )
    identities = derive_admission_permit_identities(
        tenant_id=command.tenant_id,
        runtime_run_id=command.runtime_run_id,
        task_execution_generation=execution_authority.task_execution_generation,
        lease_owner=command.lease_owner,
        lease_epoch=command.lease_epoch,
        admission_snapshot_id=execution_authority.admission_snapshot_id,
        admission_snapshot_hash=execution_authority.admission_snapshot_hash,
    )
    issued_at = NOW - timedelta(seconds=10)
    expires_at = issued_at + timedelta(seconds=command.requested_ttl_seconds)
    consumed_at = NOW - timedelta(seconds=1) if status == ExternalPermitStatus.CONSUMED else None
    return RuntimeExternalPermitFact(
        tenant_id=command.tenant_id,
        runtime_external_permit_id=command.runtime_external_permit_id,
        runtime_run_id=command.runtime_run_id,
        runtime_thread_id=THREAD_ID,
        task_step_id=STEP_ID,
        task_execution_generation=execution_authority.task_execution_generation,
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
        expires_at=expires_at,
        issue_event_id=command.issue_event_id,
        consume_event_id=(
            identities.consume_event_id
            if status == ExternalPermitStatus.CONSUMED
            else None
        ),
        consumed_by=(
            "dianlian-platform"
            if status == ExternalPermitStatus.CONSUMED
            else None
        ),
        consumed_at=consumed_at,
        updated_at=consumed_at or issued_at,
    )


def historical_consumed_fact(
    command: IssueRuntimeExternalPermitRequest,
) -> RuntimeExternalPermitFact:
    old_authority = authority(lease_owner="worker:old", lease_epoch=7)
    identities = derive_admission_permit_identities(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        task_execution_generation=3,
        lease_owner=old_authority.lease_owner,
        lease_epoch=old_authority.lease_epoch,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=ADMISSION_HASH,
    )
    old_command = replace(
        command,
        lease_owner=old_authority.lease_owner,
        lease_epoch=old_authority.lease_epoch,
        runtime_external_permit_id=identities.runtime_external_permit_id,
        issue_event_id=identities.issue_event_id,
    )
    fact = permit_fact(
        old_command,
        status=ExternalPermitStatus.CONSUMED,
        execution_authority=old_authority,
    )
    issued_at = NOW - timedelta(seconds=40)
    expires_at = issued_at + timedelta(seconds=30)
    consumed_at = expires_at - timedelta(seconds=1)
    return replace(
        fact,
        issued_at=issued_at,
        expires_at=expires_at,
        consumed_at=consumed_at,
        updated_at=consumed_at,
    )


class Repository:
    def __init__(self, result_factory: Any) -> None:
        self.result_factory = result_factory
        self.calls: list[IssueRuntimeExternalPermitRequest] = []

    def issue_external_permit(
        self,
        request: IssueRuntimeExternalPermitRequest,
    ) -> Any:
        self.calls.append(request)
        if isinstance(self.result_factory, BaseException):
            raise self.result_factory
        return self.result_factory(request)


def test_issues_current_admission_permit_once_with_frozen_identity() -> None:
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            permit_fact(command),
        )
    )

    result = DormantAdmissionPermitIssuer(repository, clock=lambda: NOW).issue(
        issue_request()
    )

    assert len(repository.calls) == 1
    command = repository.calls[0]
    assert result.disposition == AdmissionPermitDisposition.CURRENT_ISSUED
    assert result.manifest_resolve_allowed is True
    assert command.operation_kind == ExternalOperation.ADMISSION_RESOLVE
    assert command.intent_id == ADMISSION_ID
    assert command.request_hash == ADMISSION_HASH
    assert command.runtime_external_permit_id == result.permit.runtime_external_permit_id


def test_identity_derivation_binds_authority_and_matches_java_consume_id() -> None:
    common = dict(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        task_execution_generation=3,
        lease_owner="worker:[a:b]",
        lease_epoch=7,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=ADMISSION_HASH,
    )
    identity = derive_admission_permit_identities(**common)

    assert identity == derive_admission_permit_identities(**common)
    assert identity != derive_admission_permit_identities(
        **{**common, "lease_owner": "worker:[a,b:]"}
    )
    assert identity != derive_admission_permit_identities(
        **{**common, "lease_epoch": 8}
    )
    assert identity != derive_admission_permit_identities(
        **{**common, "admission_snapshot_hash": "e" * 64}
    )
    assert identity.consume_event_id == uuid5(
        NAMESPACE_URL,
        f"dianlian:admission-manifest:consume:{identity.runtime_external_permit_id}",
    )
    assert len(
        {
            identity.runtime_external_permit_id,
            identity.issue_event_id,
            identity.consume_event_id,
        }
    ) == 3


def test_current_consumed_permit_is_only_eligible_for_exact_manifest_replay() -> None:
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            permit_fact(command, status=ExternalPermitStatus.CONSUMED),
        )
    )

    result = DormantAdmissionPermitIssuer(repository, clock=lambda: NOW).issue(
        issue_request()
    )

    assert result.disposition == AdmissionPermitDisposition.CURRENT_CONSUMED
    assert result.manifest_resolve_allowed is True
    assert result.permit.consume_event_id is not None


def test_takeover_returns_historical_consumed_for_reconciliation_only() -> None:
    current_authority = authority(lease_owner="worker:new", lease_epoch=8)
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            historical_consumed_fact(command),
        )
    )

    result = DormantAdmissionPermitIssuer(repository, clock=lambda: NOW).issue(
        issue_request(current_authority)
    )

    assert result.disposition == AdmissionPermitDisposition.HISTORICAL_CONSUMED
    assert result.manifest_resolve_allowed is False
    assert result.permit.lease_owner == "worker:old"
    assert result.permit.lease_epoch == 7
    assert result.permit.expires_at < NOW


@pytest.mark.parametrize(
    "result_factory",
    [
        lambda command: PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None),
        lambda command: "invalid-result",
        RuntimeError("repository outcome unknown"),
    ],
)
def test_repository_failure_or_contract_violation_fails_closed_without_retry(
    result_factory: Any,
) -> None:
    repository = Repository(result_factory)

    with pytest.raises(AdmissionPermitFenceRequired) as raised:
        DormantAdmissionPermitIssuer(repository, clock=lambda: NOW).issue(
            issue_request()
        )

    assert raised.value.code == ADMISSION_PERMIT_FENCE_REQUIRED
    assert len(repository.calls) == 1


def test_typed_repository_outcome_unknown_is_not_reported_as_fence_loss() -> None:
    repository = Repository(
        SupervisorOutcomeUnknown(
            SupervisorErrorCode.OUTCOME_UNKNOWN,
            SupervisorPrimitive.ISSUE_EXTERNAL_PERMIT,
            "08006",
            "unknown",
        )
    )

    with pytest.raises(AdmissionPermitOutcomeUnknown) as raised:
        DormantAdmissionPermitIssuer(repository, clock=lambda: NOW).issue(
            issue_request()
        )

    assert raised.value.code == ADMISSION_PERMIT_OUTCOME_UNKNOWN
    assert len(repository.calls) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        {"operation_kind": ExternalOperation.MODEL_INVOKE},
        {"intent_id": UUID("b1000000-0000-4000-8000-000000000099")},
        {"request_hash": "f" * 64},
        {"task_execution_generation": 4},
        {"admission_snapshot_hash": "f" * 64},
        {"consume_event_id": UUID("b1000000-0000-4000-8000-000000000099")},
    ],
)
def test_consumed_fact_binding_drift_fails_closed(mutation: dict[str, object]) -> None:
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            replace(
                permit_fact(command, status=ExternalPermitStatus.CONSUMED),
                **mutation,
            ),
        )
    )

    with pytest.raises(AdmissionPermitFenceRequired):
        DormantAdmissionPermitIssuer(repository, clock=lambda: NOW).issue(
            issue_request()
        )

    assert len(repository.calls) == 1


def test_old_issued_fact_never_becomes_current_or_historical_authority() -> None:
    current_authority = authority(lease_owner="worker:new", lease_epoch=8)
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            replace(
                historical_consumed_fact(command),
                status=ExternalPermitStatus.ISSUED,
                consume_event_id=None,
                consumed_by=None,
                consumed_at=None,
                updated_at=NOW - timedelta(seconds=40),
            ),
        )
    )

    with pytest.raises(AdmissionPermitFenceRequired):
        DormantAdmissionPermitIssuer(repository, clock=lambda: NOW).issue(
            issue_request(current_authority)
        )

    assert len(repository.calls) == 1

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any
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
    RuntimeSourceKind,
    SupervisorErrorCode,
    SupervisorOutcomeUnknown,
    SupervisorPrimitive,
    SupervisorTransientConflict,
    SupervisorUnavailable,
)
from dianlian_runtime.supervisor.model_permit_issuer import (
    MODEL_PERMIT_FENCE_REQUIRED,
    MODEL_PERMIT_OUTCOME_UNKNOWN,
    DormantModelPermitIssuer,
    IssueModelPermitRequest,
    ModelPermitDisposition,
    ModelPermitFenceRequired,
    ModelPermitIssueResult,
    ModelPermitOutcomeUnknown,
    ModelPermitReceipt,
    derive_model_permit_identities,
)
from dianlian_runtime.supervisor.driver import DriverFence


TENANT_ID = UUID("a1000000-0000-4000-8000-000000000001")
RUN_ID = UUID("a1000000-0000-4000-8000-000000000002")
THREAD_ID = UUID("a1000000-0000-4000-8000-000000000003")
TASK_ID = UUID("a1000000-0000-4000-8000-000000000004")
STEP_ID = UUID("a1000000-0000-4000-8000-000000000005")
INTENT_ID = UUID("a1000000-0000-4000-8000-000000000006")
ADMISSION_ID = UUID("a1000000-0000-4000-8000-000000000007")
NOW = datetime(2026, 8, 13, 9, 0, 10, tzinfo=timezone.utc)
HASH = "a" * 64


def authority(
    *,
    lease_owner: str = "worker:region:one",
    admission_contract_version: str = "2.2",
) -> RuntimeExecutionAuthorityFact:
    structured = admission_contract_version == "3.0"
    return RuntimeExecutionAuthorityFact(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        runtime_thread_id=THREAD_ID,
        task_run_id=TASK_ID,
        task_step_id=STEP_ID,
        task_execution_generation=3,
        agent_instance_id=UUID("a1000000-0000-4000-8000-000000000008"),
        user_id=UUID("a1000000-0000-4000-8000-000000000009"),
        conversation_id=(
            None
            if structured
            else UUID("a1000000-0000-4000-8000-00000000000a")
        ),
        source_message_id=None,
        runtime_thread_revision=3 if structured else 1,
        runtime_type="DEERFLOW",
        runtime_agent_name="runtime-agent",
        capability_version_id=UUID("a1000000-0000-4000-8000-00000000000b"),
        prompt_version_id=UUID("a1000000-0000-4000-8000-00000000000c"),
        model_policy_id=UUID("a1000000-0000-4000-8000-00000000000d"),
        budget_reservation_id=UUID("a1000000-0000-4000-8000-00000000000e"),
        operation_kind=OperationKind.START,
        multitask_strategy=MultitaskStrategy.REJECT,
        request_hash="b" * 64,
        idempotency_key="run-intent",
        predecessor_runtime_run_id=None,
        expected_checkpoint_id=None,
        runtime_version="runtime-v1",
        agent_name="agent-v1",
        lease_owner=lease_owner,
        lease_epoch=7,
        admission_contract_version=admission_contract_version,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash="c" * 64,
        source_kind=(
            RuntimeSourceKind.TASK_STEP
            if structured
            else RuntimeSourceKind.CONVERSATION
        ),
    )


def issue_request(
    execution_authority: RuntimeExecutionAuthorityFact | None = None,
) -> IssueModelPermitRequest:
    execution_authority = execution_authority or authority()
    return IssueModelPermitRequest(
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
        intent_id=INTENT_ID,
        request_hash=HASH,
        requested_ttl_seconds=30,
    )


def permit_fact(
    command: IssueRuntimeExternalPermitRequest,
    *,
    status: ExternalPermitStatus = ExternalPermitStatus.ISSUED,
    admission_contract_version: str = "2.2",
) -> RuntimeExternalPermitFact:
    execution_authority = authority(
        lease_owner=command.lease_owner,
        admission_contract_version=admission_contract_version,
    )
    identities = derive_model_permit_identities(
        tenant_id=command.tenant_id,
        runtime_run_id=command.runtime_run_id,
        task_execution_generation=execution_authority.task_execution_generation,
        lease_owner=command.lease_owner,
        lease_epoch=command.lease_epoch,
        admission_snapshot_id=execution_authority.admission_snapshot_id,
        admission_snapshot_hash=execution_authority.admission_snapshot_hash,
        intent_id=command.intent_id,
        request_hash=command.request_hash,
    )
    consumed = status == ExternalPermitStatus.CONSUMED
    issued_at = NOW - timedelta(seconds=10)
    expires_at = issued_at + timedelta(seconds=command.requested_ttl_seconds)
    consumed_at = NOW - timedelta(seconds=1) if consumed else None
    return RuntimeExternalPermitFact(
        tenant_id=command.tenant_id,
        runtime_external_permit_id=command.runtime_external_permit_id,
        runtime_run_id=command.runtime_run_id,
        runtime_thread_id=THREAD_ID,
        task_step_id=STEP_ID,
        task_execution_generation=execution_authority.task_execution_generation,
        admission_contract_version=admission_contract_version,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash="c" * 64,
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
        consume_event_id=identities.arm_event_id if consumed else None,
        consumed_by="dianlian-platform" if consumed else None,
        consumed_at=consumed_at,
        updated_at=consumed_at or issued_at,
    )


def historical_consumed_fact(
    command: IssueRuntimeExternalPermitRequest,
    *,
    lease_owner: str = "worker:region:old",
    lease_epoch: int = 7,
    requested_ttl_seconds: int = 20,
) -> RuntimeExternalPermitFact:
    identities = derive_model_permit_identities(
        tenant_id=command.tenant_id,
        runtime_run_id=command.runtime_run_id,
        task_execution_generation=3,
        lease_owner=lease_owner,
        lease_epoch=lease_epoch,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash="c" * 64,
        intent_id=command.intent_id,
        request_hash=command.request_hash,
    )
    historical_command = replace(
        command,
        lease_owner=lease_owner,
        lease_epoch=lease_epoch,
        runtime_external_permit_id=identities.runtime_external_permit_id,
        requested_ttl_seconds=requested_ttl_seconds,
        issue_event_id=identities.issue_event_id,
    )
    fact = permit_fact(
        historical_command,
        status=ExternalPermitStatus.CONSUMED,
    )
    issued_at = NOW - timedelta(seconds=40)
    expires_at = issued_at + timedelta(seconds=requested_ttl_seconds)
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


def test_issues_once_and_returns_stable_one_shot_receipt() -> None:
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            permit_fact(command),
        )
    )
    issuer = DormantModelPermitIssuer(repository, clock=lambda: NOW)
    request = issue_request()

    first_result = issuer.issue(request)
    second_result = issuer.issue(request)

    assert first_result == second_result
    assert first_result.disposition == ModelPermitDisposition.CURRENT_ISSUED
    assert first_result.provider_dispatch_allowed is True
    first = first_result.receipt
    assert len(repository.calls) == 2
    assert repository.calls[0] == repository.calls[1]
    assert first.intent_id == INTENT_ID
    assert first.permit_attempt == 1
    assert first.expires_at - first.issued_at == timedelta(seconds=30)
    assert len({
        first.runtime_external_permit_id,
        first.issue_event_id,
        first.arm_event_id,
    }) == 3
    assert repository.calls[0].operation_kind == ExternalOperation.MODEL_INVOKE
    assert repository.calls[0].intent_id == INTENT_ID
    assert repository.calls[0].request_hash == HASH
    assert (
        first.tenant_id,
        first.runtime_external_permit_id,
        first.runtime_run_id,
        first.task_execution_generation,
        first.lease_owner,
        first.lease_epoch,
        first.admission_snapshot_id,
        first.admission_snapshot_hash,
        first.operation_kind,
        first.intent_id,
        first.request_hash,
    ) == (
        TENANT_ID,
        repository.calls[0].runtime_external_permit_id,
        RUN_ID,
        3,
        "worker:region:one",
        7,
        ADMISSION_ID,
        "c" * 64,
        ExternalOperation.MODEL_INVOKE,
        INTENT_ID,
        HASH,
    )


def test_accepts_exact_structured_admission_contract_version() -> None:
    structured_authority = authority(admission_contract_version="3.0")
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            permit_fact(command, admission_contract_version="3.0"),
        )
    )

    result = DormantModelPermitIssuer(repository, clock=lambda: NOW).issue(
        issue_request(structured_authority)
    )

    assert result.disposition == ModelPermitDisposition.CURRENT_ISSUED
    assert result.provider_dispatch_allowed is True
    assert result.receipt.admission_snapshot_id == ADMISSION_ID
    assert len(repository.calls) == 1


def test_identity_derivation_is_unambiguous_across_delimiters_and_field_boundaries() -> None:
    common = dict(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        task_execution_generation=3,
        lease_epoch=7,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash="c" * 64,
        intent_id=INTENT_ID,
        request_hash=HASH,
    )
    delimited = derive_model_permit_identities(
        **common,
        lease_owner='worker:["a:b",1]',
    )
    repeated = derive_model_permit_identities(
        **common,
        lease_owner='worker:["a:b",1]',
    )
    shifted_owner = derive_model_permit_identities(
        **common,
        lease_owner='worker:["a","b:1"]',
    )
    shifted_fields = derive_model_permit_identities(
        **{
            **common,
            "task_execution_generation": 37,
            "lease_epoch": 3,
        },
        lease_owner='worker:["a:b",1]',
    )
    shifted_admission_id = derive_model_permit_identities(
        **{
            **common,
            "admission_snapshot_id": UUID(
                "a1000000-0000-4000-8000-000000000099"
            ),
        },
        lease_owner='worker:["a:b",1]',
    )
    shifted_admission_hash = derive_model_permit_identities(
        **{**common, "admission_snapshot_hash": "d" * 64},
        lease_owner='worker:["a:b",1]',
    )
    other_tenant = derive_model_permit_identities(
        **{
            **common,
            "tenant_id": UUID("a1000000-0000-4000-8000-000000000099"),
        },
        lease_owner='worker:["a:b",1]',
    )
    other_run = derive_model_permit_identities(
        **{
            **common,
            "runtime_run_id": UUID("a1000000-0000-4000-8000-000000000099"),
        },
        lease_owner='worker:["a:b",1]',
    )
    other_intent = derive_model_permit_identities(
        **{
            **common,
            "intent_id": UUID("a1000000-0000-4000-8000-000000000099"),
        },
        lease_owner='worker:["a:b",1]',
    )
    other_request_hash = derive_model_permit_identities(
        **{**common, "request_hash": "d" * 64},
        lease_owner='worker:["a:b",1]',
    )

    assert delimited == repeated
    assert delimited != shifted_owner
    assert delimited != shifted_fields
    assert delimited != shifted_admission_id
    assert delimited != shifted_admission_hash
    assert delimited != other_tenant
    assert delimited != other_run
    assert delimited != other_intent
    assert delimited != other_request_hash


def test_exact_response_loss_reentry_returns_current_issued() -> None:
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            permit_fact(command),
        )
    )
    result = DormantModelPermitIssuer(repository, clock=lambda: NOW).issue(
        issue_request()
    )

    assert len(repository.calls) == 1
    assert result.disposition == ModelPermitDisposition.CURRENT_ISSUED
    assert result.provider_dispatch_allowed is True
    assert result.receipt.permit_attempt == 1


def test_same_epoch_consumed_is_historical_and_never_dispatchable() -> None:
    returned_fact: RuntimeExternalPermitFact | None = None

    def result_factory(
        command: IssueRuntimeExternalPermitRequest,
    ) -> PrimitiveResult[RuntimeExternalPermitFact]:
        nonlocal returned_fact
        returned_fact = permit_fact(command, status=ExternalPermitStatus.CONSUMED)
        return PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, returned_fact)

    repository = Repository(result_factory)
    result = DormantModelPermitIssuer(repository, clock=lambda: NOW).issue(
        issue_request()
    )

    assert returned_fact is not None
    assert result.disposition == ModelPermitDisposition.HISTORICAL_CONSUMED
    assert result.provider_dispatch_allowed is False
    assert result.receipt.arm_event_id == returned_fact.consume_event_id
    assert not hasattr(result.receipt, "status")


def test_old_owner_epoch_and_expired_consumed_fact_is_historical() -> None:
    current_authority = replace(
        authority(lease_owner="worker:region:new"),
        lease_epoch=8,
    )
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            historical_consumed_fact(command),
        )
    )

    result = DormantModelPermitIssuer(repository, clock=lambda: NOW).issue(
        issue_request(current_authority)
    )

    assert result.disposition == ModelPermitDisposition.HISTORICAL_CONSUMED
    assert result.provider_dispatch_allowed is False
    assert result.receipt.lease_owner == "worker:region:old"
    assert result.receipt.lease_epoch == 7
    assert result.receipt.expires_at < NOW
    assert result.receipt.expires_at - result.receipt.issued_at == timedelta(
        seconds=20
    )


@pytest.mark.parametrize(
    "fact_factory",
    [
        lambda command: replace(
            historical_consumed_fact(command),
            runtime_external_permit_id=UUID(
                "a1000000-0000-4000-8000-000000000099"
            ),
        ),
        lambda command: replace(
            historical_consumed_fact(command),
            issue_event_id=UUID("a1000000-0000-4000-8000-000000000099"),
        ),
        lambda command: replace(
            historical_consumed_fact(command),
            consume_event_id=UUID("a1000000-0000-4000-8000-000000000099"),
        ),
        lambda command: replace(
            historical_consumed_fact(command),
            lease_owner="worker:region:tampered",
        ),
        lambda command: historical_consumed_fact(
            command,
            lease_owner="worker:region:other",
            lease_epoch=8,
        ),
        lambda command: historical_consumed_fact(command, lease_epoch=9),
        lambda command: replace(
            historical_consumed_fact(command),
            runtime_thread_id=UUID("a1000000-0000-4000-8000-000000000099"),
        ),
    ],
)
def test_historical_consumed_identity_or_authority_mismatch_requires_fence(
    fact_factory: Any,
) -> None:
    current_authority = replace(
        authority(lease_owner="worker:region:new"),
        lease_epoch=8,
    )
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            fact_factory(command),
        )
    )

    with pytest.raises(ModelPermitFenceRequired):
        DormantModelPermitIssuer(repository, clock=lambda: NOW).issue(
            issue_request(current_authority)
        )

    assert len(repository.calls) == 1


def test_new_lease_epoch_accepts_the_database_second_attempt() -> None:
    next_authority = replace(authority(), lease_epoch=8)
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            replace(permit_fact(command), permit_attempt=2),
        )
    )

    result = DormantModelPermitIssuer(repository, clock=lambda: NOW).issue(
        issue_request(next_authority)
    )

    assert result.disposition == ModelPermitDisposition.CURRENT_ISSUED
    assert result.receipt.permit_attempt == 2
    assert result.receipt.lease_epoch == 8


@pytest.mark.parametrize(
    "result_factory",
    [
        lambda command: PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None),
        lambda command: "invalid-result",
        RuntimeError("adapter contract regression"),
    ],
)
def test_not_applied_unknown_or_contract_type_requires_fence_without_retry(
    result_factory: Any,
) -> None:
    repository = Repository(result_factory)

    with pytest.raises(ModelPermitFenceRequired) as raised:
        DormantModelPermitIssuer(repository, clock=lambda: NOW).issue(
            issue_request()
        )

    assert raised.value.code == MODEL_PERMIT_FENCE_REQUIRED
    assert len(repository.calls) == 1


@pytest.mark.parametrize(
    "result_factory",
    [
        SupervisorOutcomeUnknown(
            SupervisorErrorCode.OUTCOME_UNKNOWN,
            SupervisorPrimitive.ISSUE_EXTERNAL_PERMIT,
            "08006",
            "unknown",
        ),
        SupervisorUnavailable(
            SupervisorErrorCode.UNAVAILABLE,
            SupervisorPrimitive.ISSUE_EXTERNAL_PERMIT,
            "08001",
            "unavailable",
        ),
        SupervisorTransientConflict(
            SupervisorErrorCode.TRANSIENT_CONFLICT,
            SupervisorPrimitive.ISSUE_EXTERNAL_PERMIT,
            "40001",
            "retry exact command",
        ),
    ],
)
def test_typed_repository_uncertainty_is_distinct_from_a_fence_failure(
    result_factory: Any,
) -> None:
    repository = Repository(result_factory)

    with pytest.raises(ModelPermitOutcomeUnknown) as raised:
        DormantModelPermitIssuer(repository, clock=lambda: NOW).issue(
            issue_request()
        )

    assert raised.value.code == MODEL_PERMIT_OUTCOME_UNKNOWN
    assert len(repository.calls) == 1


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("tenant_id", UUID("a1000000-0000-4000-8000-000000000099")),
        ("runtime_run_id", UUID("a1000000-0000-4000-8000-000000000099")),
        ("runtime_thread_id", UUID("a1000000-0000-4000-8000-000000000099")),
        ("task_step_id", UUID("a1000000-0000-4000-8000-000000000099")),
        ("task_execution_generation", 4),
        ("admission_contract_version", "3.0"),
        ("admission_snapshot_id", UUID("a1000000-0000-4000-8000-000000000099")),
        ("admission_snapshot_hash", "d" * 64),
        ("operation_kind", ExternalOperation.TOOL_INVOKE),
        ("intent_id", UUID("a1000000-0000-4000-8000-000000000099")),
        ("request_hash", "d" * 64),
        ("lease_owner", "other-worker"),
        ("lease_epoch", 8),
        ("requested_ttl_seconds", 29),
        ("issue_event_id", UUID("a1000000-0000-4000-8000-000000000099")),
    ],
)
def test_any_fact_binding_mismatch_requires_fence(
    mutation: str,
    value: object,
) -> None:
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            replace(permit_fact(command), **{mutation: value}),
        )
    )

    with pytest.raises(ModelPermitFenceRequired):
        DormantModelPermitIssuer(repository, clock=lambda: NOW).issue(
            issue_request()
        )
    assert len(repository.calls) == 1


@pytest.mark.parametrize(
    "fact_factory",
    [
        lambda command: replace(
            permit_fact(command),
            issued_at=NOW - timedelta(seconds=31),
            expires_at=NOW - timedelta(seconds=1),
            updated_at=NOW - timedelta(seconds=31),
        ),
        lambda command: replace(
            permit_fact(command),
            expires_at=NOW + timedelta(seconds=21),
        ),
        lambda command: replace(
            permit_fact(command),
            updated_at=NOW - timedelta(seconds=9),
        ),
        lambda command: replace(
            permit_fact(command),
            issued_at=NOW + timedelta(seconds=1),
            expires_at=NOW + timedelta(seconds=31),
            updated_at=NOW + timedelta(seconds=1),
        ),
    ],
)
def test_expired_or_inconsistent_times_require_fence(fact_factory: Any) -> None:
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            fact_factory(command),
        )
    )

    with pytest.raises(ModelPermitFenceRequired):
        DormantModelPermitIssuer(repository, clock=lambda: NOW).issue(
            issue_request()
        )
    assert len(repository.calls) == 1


def test_request_contract_rejects_non_model_intent_shapes_before_repository() -> None:
    request = issue_request()
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        replace(request, request_hash="A" * 64)
    with pytest.raises(ValueError, match="outside its allowed range"):
        replace(request, requested_ttl_seconds=61)
    with pytest.raises(ValueError, match="nil UUID"):
        replace(request, intent_id=UUID(int=0))


def test_request_requires_the_structural_driver_fence_to_match_authority() -> None:
    request = issue_request()

    with pytest.raises(ValueError, match="authority and fence do not match"):
        replace(request, fence=replace(request.fence, lease_epoch=8))


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("tenant_id", UUID(int=0)),
        ("runtime_external_permit_id", UUID(int=0)),
        ("runtime_run_id", UUID(int=0)),
        ("task_execution_generation", 0),
        ("lease_owner", " padded"),
        ("lease_epoch", 0),
        ("admission_snapshot_id", UUID(int=0)),
        ("admission_snapshot_hash", "D" * 64),
        ("operation_kind", "MODEL_INVOKE"),
        ("operation_kind", ExternalOperation.TOOL_INVOKE),
        ("intent_id", UUID(int=0)),
        ("request_hash", "D" * 64),
    ],
)
def test_receipt_validates_each_java_arm_binding_field(
    field_name: str,
    invalid_value: object,
) -> None:
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            permit_fact(command),
        )
    )
    result: ModelPermitIssueResult = DormantModelPermitIssuer(
        repository,
        clock=lambda: NOW,
    ).issue(issue_request())
    receipt: ModelPermitReceipt = result.receipt

    with pytest.raises((TypeError, ValueError)):
        replace(receipt, **{field_name: invalid_value})


def test_result_cannot_enable_dispatch_for_historical_receipt() -> None:
    repository = Repository(
        lambda command: PrimitiveResult(
            PrimitiveOutcome.FACT_RETURNED,
            permit_fact(command),
        )
    )
    result = DormantModelPermitIssuer(repository, clock=lambda: NOW).issue(
        issue_request()
    )

    with pytest.raises(ValueError, match="does not match permit disposition"):
        replace(
            result,
            disposition=ModelPermitDisposition.HISTORICAL_CONSUMED,
        )


def test_module_is_dormant_and_not_exported_or_composed() -> None:
    import dianlian_runtime.supervisor as supervisor_package

    assert not hasattr(supervisor_package, "DormantModelPermitIssuer")

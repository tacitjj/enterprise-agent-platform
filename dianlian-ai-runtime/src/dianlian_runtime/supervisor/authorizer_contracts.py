from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from dianlian_runtime.supervisor.contracts import RuntimeSourceKind


_MAX_BIGINT = 9_223_372_036_854_775_807


def _require_non_nil_uuid(value: UUID) -> UUID:
    if value.int == 0:
        raise ValueError("UUID must not be the nil UUID")
    return value


NonNilUuid = Annotated[UUID, AfterValidator(_require_non_nil_uuid)]
LowerSha256 = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]


class _StrictCamelContract(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_alias=True,
        validate_by_name=False,
        extra="forbid",
        frozen=True,
    )


class PermitAuthorizationRequest(_StrictCamelContract):
    tenant_id: NonNilUuid
    runtime_external_permit_id: NonNilUuid
    runtime_run_id: NonNilUuid
    task_execution_generation: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    lease_owner: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=160),
    ]
    lease_epoch: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    admission_snapshot_id: NonNilUuid
    admission_snapshot_hash: LowerSha256
    operation_kind: Literal["ADMISSION_RESOLVE"]
    intent_id: NonNilUuid
    request_hash: LowerSha256
    consume_event_id: NonNilUuid

    @field_validator("lease_owner")
    @classmethod
    def require_trimmed_lease_owner(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("leaseOwner must be non-blank and trimmed")
        return value


class PermitAuthorizationOutcome(StrEnum):
    APPLIED = "APPLIED"
    NOT_APPLIED = "NOT_APPLIED"


class PermitAuthorizationResponse(_StrictCamelContract):
    outcome: PermitAuthorizationOutcome


class PermitAuthorizationProblem(_StrictCamelContract):
    code: str
    message: str


class ExternalDispatchArmRequest(_StrictCamelContract):
    tenant_id: NonNilUuid
    runtime_external_permit_id: NonNilUuid
    runtime_run_id: NonNilUuid
    task_execution_generation: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    lease_owner: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=160),
    ]
    lease_epoch: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    admission_snapshot_id: NonNilUuid
    admission_snapshot_hash: LowerSha256
    operation_kind: Literal["MODEL_INVOKE", "TOOL_INVOKE"]
    intent_id: NonNilUuid
    request_hash: LowerSha256
    arm_event_id: NonNilUuid

    @field_validator("lease_owner")
    @classmethod
    def require_trimmed_lease_owner(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("leaseOwner must be non-blank and trimmed")
        return value


class ExternalDispatchArmApiDecision(StrEnum):
    GRANTED_NOW = "GRANTED_NOW"
    DO_NOT_DISPATCH = "DO_NOT_DISPATCH"
    NOT_APPLIED = "NOT_APPLIED"


class ExternalDispatchGrantFact(_StrictCamelContract):
    """Exact persisted Supervisor attempt binding returned for grant recovery."""

    tenant_id: NonNilUuid
    runtime_external_permit_id: NonNilUuid
    runtime_run_id: NonNilUuid
    task_execution_generation: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    lease_owner: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=160),
    ]
    lease_epoch: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    admission_snapshot_id: NonNilUuid
    admission_snapshot_hash: LowerSha256
    operation_kind: Literal["MODEL_INVOKE", "TOOL_INVOKE"]
    intent_id: NonNilUuid
    request_hash: LowerSha256
    arm_event_id: NonNilUuid
    attempt_status: Literal[
        "DISPATCH_ARMED",
        "NOT_DISPATCHED",
        "SUCCEEDED",
        "FAILED_CONFIRMED",
        "OUTCOME_UNKNOWN",
    ]

    @field_validator("lease_owner")
    @classmethod
    def require_trimmed_lease_owner(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("leaseOwner must be non-blank and trimmed")
        return value

    @classmethod
    def from_attempt(
        cls,
        fact: object,
    ) -> "ExternalDispatchGrantFact":
        from dianlian_runtime.supervisor.contracts import (
            RuntimeExternalOperationAttemptFact,
        )

        if not isinstance(fact, RuntimeExternalOperationAttemptFact):
            raise TypeError("grant fact must be a runtime operation attempt fact")
        return cls.model_validate(
            {
                "tenantId": fact.tenant_id,
                "runtimeExternalPermitId": fact.runtime_external_permit_id,
                "runtimeRunId": fact.runtime_run_id,
                "taskExecutionGeneration": fact.task_execution_generation,
                "leaseOwner": fact.lease_owner,
                "leaseEpoch": fact.lease_epoch,
                "admissionSnapshotId": fact.admission_snapshot_id,
                "admissionSnapshotHash": fact.admission_snapshot_hash,
                "operationKind": fact.operation_kind.value,
                "intentId": fact.intent_id,
                "requestHash": fact.request_hash,
                "armEventId": fact.arm_event_id,
                "attemptStatus": fact.status.value,
            },
            strict=True,
        )


class ExternalDispatchArmResponse(_StrictCamelContract):
    decision: ExternalDispatchArmApiDecision
    grant_fact: ExternalDispatchGrantFact | None

    @model_validator(mode="after")
    def require_exact_decision_evidence(self) -> "ExternalDispatchArmResponse":
        if self.decision == ExternalDispatchArmApiDecision.NOT_APPLIED:
            if self.grant_fact is not None:
                raise ValueError("NOT_APPLIED must not contain a grant fact")
            return self
        if self.grant_fact is None:
            raise ValueError("dispatch decision requires its exact grant fact")
        if (
            self.decision == ExternalDispatchArmApiDecision.GRANTED_NOW
            and self.grant_fact.attempt_status != "DISPATCH_ARMED"
        ):
            raise ValueError("GRANTED_NOW requires a DISPATCH_ARMED grant fact")
        return self

    @classmethod
    def from_result(cls, result: object) -> "ExternalDispatchArmResponse":
        from dianlian_runtime.supervisor.contracts import (
            PrimitiveOutcome,
            RuntimeExternalDispatchArmResult,
        )

        if not isinstance(result, RuntimeExternalDispatchArmResult):
            raise TypeError("arm result must be a runtime dispatch arm result")
        if result.outcome == PrimitiveOutcome.NOT_APPLIED:
            return cls.model_validate(
                {
                    "decision": ExternalDispatchArmApiDecision.NOT_APPLIED,
                    "grantFact": None,
                },
                strict=True,
            )
        if result.decision is None or result.fact is None:
            raise ValueError("arm result is missing its exact grant fact")
        grant_fact = ExternalDispatchGrantFact.from_attempt(result.fact)
        return cls.model_validate(
            {
                "decision": ExternalDispatchArmApiDecision(result.decision.value),
                "grantFact": grant_fact,
            },
            strict=True,
        )


class ExternalDispatchArmProblem(_StrictCamelContract):
    code: str
    message: str


class _ExternalOperationOutcomeRequest(_StrictCamelContract):
    tenant_id: NonNilUuid
    runtime_external_permit_id: NonNilUuid
    runtime_run_id: NonNilUuid
    task_execution_generation: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    lease_owner: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=160),
    ]
    lease_epoch: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    admission_snapshot_id: NonNilUuid
    admission_snapshot_hash: LowerSha256
    operation_kind: Literal["MODEL_INVOKE", "TOOL_INVOKE"]
    intent_id: NonNilUuid
    request_hash: LowerSha256
    outcome_status: Literal[
        "NOT_DISPATCHED",
        "SUCCEEDED",
        "FAILED_CONFIRMED",
        "OUTCOME_UNKNOWN",
    ]
    source_fact_id: NonNilUuid
    source_fact_version: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    source_fact_hash: LowerSha256
    outcome_code: Annotated[
        StrictStr,
        StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$"),
    ]
    result_hash: LowerSha256 | None

    @field_validator("lease_owner")
    @classmethod
    def require_trimmed_lease_owner(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("leaseOwner must be non-blank and trimmed")
        return value

    @field_validator("result_hash")
    @classmethod
    def require_result_hash_for_confirmed_outcome(
        cls,
        value: str | None,
        info: object,
    ) -> str | None:
        outcome_status = getattr(info, "data", {}).get("outcome_status")
        if outcome_status in {"SUCCEEDED", "FAILED_CONFIRMED"}:
            if value is None:
                raise ValueError("resultHash is required for confirmed outcomes")
        elif value is not None:
            raise ValueError("resultHash must be null for this outcomeStatus")
        return value


class ExternalOperationOutcomeRecordRequest(_ExternalOperationOutcomeRequest):
    outcome_event_id: NonNilUuid


class ExternalOperationOutcomeReconcileRequest(_ExternalOperationOutcomeRequest):
    expected_unknown_event_id: NonNilUuid
    reconcile_event_id: NonNilUuid

    @field_validator("outcome_status")
    @classmethod
    def reject_unknown_reconciliation(cls, value: str) -> str:
        if value == "OUTCOME_UNKNOWN":
            raise ValueError("reconciliation requires a confirmed outcome")
        return value


class ExternalOperationOutcomeApiResult(StrEnum):
    APPLIED = "APPLIED"
    NOT_APPLIED = "NOT_APPLIED"


class ExternalOperationOutcomeResponse(_StrictCamelContract):
    outcome: ExternalOperationOutcomeApiResult


class ExternalOperationOutcomeProblem(_StrictCamelContract):
    code: str
    message: str


class RuntimeRunAcceptedEventPayload(_StrictCamelContract):
    schema_version: Literal["runtime-run-accepted-v2", "runtime-run-accepted-v3"]
    source_kind: Literal["TASK_STEP"] | None = None
    runtime_thread_id: NonNilUuid
    runtime_thread_revision: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    runtime_run_id: NonNilUuid
    task_run_id: NonNilUuid
    task_step_id: NonNilUuid
    agent_instance_id: NonNilUuid
    task_execution_generation: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    admission_snapshot_id: NonNilUuid
    admission_snapshot_hash: LowerSha256
    request_hash: LowerSha256
    execution_plan_version: StrictInt = Field(ge=1, le=2_147_483_647)
    execution_template_code: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=128),
    ]
    execution_template_version: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=64),
    ]
    step_key: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=100),
    ]
    execution_profile_hash: LowerSha256
    input_artifact_ids: tuple[NonNilUuid, ...] = Field(max_length=256)

    @field_validator(
        "execution_template_code",
        "execution_template_version",
        "step_key",
    )
    @classmethod
    def require_trimmed_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("accepted event text must be trimmed")
        return value

    @field_validator("input_artifact_ids")
    @classmethod
    def require_unique_artifacts(
        cls,
        value: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("inputArtifactIds must not contain duplicates")
        return value

    @model_validator(mode="after")
    def require_versioned_source(self) -> "RuntimeRunAcceptedEventPayload":
        if self.schema_version == "runtime-run-accepted-v2":
            if self.source_kind is not None:
                raise ValueError("v2 accepted event cannot carry a task-step source")
        elif self.source_kind != "TASK_STEP":
            raise ValueError("v3 accepted event requires sourceKind TASK_STEP")
        return self


class RuntimeRunAdmissionRequest(_StrictCamelContract):
    tenant_id: NonNilUuid
    runtime_thread_id: NonNilUuid
    task_run_id: NonNilUuid
    task_step_id: NonNilUuid
    agent_instance_id: NonNilUuid
    user_id: NonNilUuid
    source_kind: RuntimeSourceKind
    conversation_id: NonNilUuid | None
    source_message_id: NonNilUuid | None
    runtime_thread_revision: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    runtime_type: Annotated[
        StrictStr,
        StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,31}$"),
    ]
    runtime_agent_name: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=128),
    ]
    capability_version_id: NonNilUuid
    prompt_version_id: NonNilUuid
    model_policy_id: NonNilUuid
    budget_reservation_id: NonNilUuid
    input_artifact_ids: tuple[NonNilUuid, ...] = Field(max_length=256)
    runtime_run_id: NonNilUuid
    task_execution_generation: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    operation_kind: Literal["START"]
    multitask_strategy: Literal["REJECT"]
    request_hash: LowerSha256
    idempotency_key: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=200),
    ]
    predecessor_runtime_run_id: NonNilUuid | None
    expected_checkpoint_id: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=160),
    ] | None
    runtime_version: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=128),
    ]
    agent_name: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=128),
    ]
    admission_contract_version: Literal["2.2", "3.0"]
    admission_snapshot_id: NonNilUuid
    admission_snapshot_hash: LowerSha256
    accepted_event_id: NonNilUuid
    accepted_event_payload: RuntimeRunAcceptedEventPayload

    @field_validator(
        "runtime_agent_name",
        "idempotency_key",
        "expected_checkpoint_id",
        "runtime_version",
        "agent_name",
    )
    @classmethod
    def require_trimmed_text(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("Run admission text must be trimmed")
        return value

    @field_validator("input_artifact_ids")
    @classmethod
    def require_unique_artifacts(
        cls,
        value: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("inputArtifactIds must not contain duplicates")
        return value

    @model_validator(mode="after")
    def require_exact_accepted_event_binding(self) -> "RuntimeRunAdmissionRequest":
        event = self.accepted_event_payload
        if (
            event.runtime_thread_id != self.runtime_thread_id
            or event.runtime_thread_revision != self.runtime_thread_revision
            or event.runtime_run_id != self.runtime_run_id
            or event.task_run_id != self.task_run_id
            or event.task_step_id != self.task_step_id
            or event.agent_instance_id != self.agent_instance_id
            or event.task_execution_generation != self.task_execution_generation
            or event.admission_snapshot_id != self.admission_snapshot_id
            or event.admission_snapshot_hash != self.admission_snapshot_hash
            or event.request_hash != self.request_hash
            or event.input_artifact_ids != self.input_artifact_ids
        ):
            raise ValueError("acceptedEventPayload must match the Run admission binding")
        if self.admission_contract_version == "2.2":
            if (
                self.source_kind != RuntimeSourceKind.CONVERSATION
                or self.conversation_id is None
                or event.schema_version != "runtime-run-accepted-v2"
                or event.source_kind is not None
            ):
                raise ValueError("2.2 admission requires a v2 conversation source")
        elif (
            self.source_kind != RuntimeSourceKind.TASK_STEP
            or self.conversation_id is not None
            or self.source_message_id is not None
            or self.runtime_thread_revision != self.task_execution_generation
            or event.schema_version != "runtime-run-accepted-v3"
            or event.source_kind != RuntimeSourceKind.TASK_STEP.value
        ):
            raise ValueError("3.0 admission requires a v3 task-step source")
        return self


class RuntimeRunAdmissionApiResult(StrEnum):
    APPLIED = "APPLIED"
    NOT_APPLIED = "NOT_APPLIED"


class RuntimeRunAdmissionResponse(_StrictCamelContract):
    outcome: RuntimeRunAdmissionApiResult


class RuntimeRunAdmissionProblem(_StrictCamelContract):
    code: str
    message: str


class RuntimeRunCancelRequest(_StrictCamelContract):
    tenant_id: NonNilUuid
    runtime_run_id: NonNilUuid
    cancel_request_id: NonNilUuid
    actor_id: NonNilUuid
    reason_code: Annotated[
        StrictStr,
        StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,63}$"),
    ]
    expected_run_version: StrictInt = Field(ge=1, le=_MAX_BIGINT)
    idempotency_key: Annotated[
        StrictStr,
        StringConstraints(min_length=1, max_length=200),
    ]
    request_hash: LowerSha256

    @field_validator("idempotency_key")
    @classmethod
    def require_trimmed_idempotency_key(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("idempotencyKey must be trimmed")
        return value


class RuntimeRunCancelApiResult(StrEnum):
    APPLIED = "APPLIED"
    NOT_APPLIED = "NOT_APPLIED"


class RuntimeRunCancelResponse(_StrictCamelContract):
    outcome: RuntimeRunCancelApiResult


class RuntimeRunCancelProblem(_StrictCamelContract):
    code: str
    message: str

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, TypeVar, cast
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from dianlian_runtime.supervisor.contracts import (
    AdmitRuntimeRunRequest,
    AppendRuntimeRunEventRequest,
    AuthorizeRuntimeRunCancellationRequest,
    AuthorizeRuntimeRunRequest,
    BeginRuntimeRunCancellationRequest,
    ClaimRuntimeRunRequest,
    CompleteRuntimeRunRequest,
    ConsumeAndArmRuntimeExternalDispatchRequest,
    ConsumeRuntimeExternalPermitRequest,
    ExternalDispatchArmDecision,
    ExternalOperation,
    ExternalOperationAttemptStatus,
    ExternalOutcomeEvidenceKind,
    ExternalPermitStatus,
    FailRuntimeRunRequest,
    FinishRuntimeRunCancellationRequest,
    FrozenJsonObject,
    LoadRuntimeExecutionAuthorityRequest,
    IssueRuntimeExternalPermitRequest,
    LoadRuntimeExternalOperationBarrierRequest,
    PrimitiveOutcome,
    PrimitiveResult,
    ReconcileRuntimeExternalOperationOutcomeRequest,
    RecordRuntimeExternalOperationOutcomeRequest,
    RecordRuntimeCheckpointRequest,
    RenewRuntimeRunLeaseRequest,
    RequestRuntimeRunCancelRequest,
    RuntimeCancellationAuthorityFact,
    RuntimeCheckpointFact,
    RuntimeExecutionAuthorityFact,
    RuntimeExternalDispatchArmResult,
    RuntimeExternalOperationAttemptFact,
    RuntimeExternalOperationBarrierFact,
    RuntimeExternalPermitFact,
    RuntimeRunCandidateFact,
    RuntimeRunControlFact,
    RuntimeRunEventFact,
    RuntimeRunFact,
    SupervisorCommandConflict,
    SupervisorErrorCode,
    SupervisorIntegrityOrContractViolation,
    SupervisorInvalidCommand,
    SupervisorOutcomeUnknown,
    SupervisorPermissionBoundaryMisconfigured,
    SupervisorPrimitive,
    SupervisorRepositoryError,
    SupervisorTransientConflict,
    SupervisorUnavailable,
    SupervisorUnsupportedCommand,
    TakeoverRuntimeRunRequest,
    SelectNextRuntimeRunCandidateRequest,
    RuntimeStatus,
    OperationKind,
    MultitaskStrategy,
)


_RUN_COLUMNS = """
tenant_id, runtime_run_id, runtime_thread_id, task_step_id,
task_execution_generation, status, operation_kind, multitask_strategy,
request_hash, idempotency_key, predecessor_runtime_run_id,
expected_checkpoint_id, current_checkpoint_id, current_checkpoint_sequence_no,
next_event_sequence_no, event_retention_floor_sequence, run_version,
terminal_reason, terminal_event_id, lease_owner, lease_until, lease_epoch,
heartbeat_at, attempt, runtime_version, agent_name, failure_code,
cancel_requested_at, started_at, terminal_at, created_at, updated_at
"""
_EVENT_COLUMNS = """
tenant_id, runtime_run_id, runtime_thread_id, event_id, sequence_no,
event_type, event_version, run_version, lease_owner, lease_epoch,
checkpoint_id, payload, occurred_at, created_at
"""
_CHECKPOINT_COLUMNS = """
tenant_id, runtime_run_id, runtime_thread_id, checkpoint_id,
checkpoint_namespace, sequence_no, event_id, run_version, lease_epoch,
checkpoint_schema_version, created_at
"""
_CONTROL_COLUMNS = """
tenant_id, control_id, runtime_run_id, runtime_thread_id, control_type,
actor_id, reason_code, expected_run_version, idempotency_key, request_hash,
created_at
"""
_CANDIDATE_COLUMNS = "tenant_id, runtime_run_id"
_CANCELLATION_AUTHORITY_COLUMNS = """
tenant_id, runtime_run_id, runtime_thread_id, task_step_id,
task_execution_generation, status, lease_owner, lease_epoch, run_version,
cancel_requested_at
"""
_EXECUTION_AUTHORITY_COLUMNS = """
tenant_id, runtime_run_id, runtime_thread_id, task_run_id, task_step_id,
task_execution_generation, agent_instance_id, user_id, conversation_id,
source_message_id, runtime_thread_revision, runtime_type, runtime_agent_name,
capability_version_id, prompt_version_id, model_policy_id,
budget_reservation_id, operation_kind, multitask_strategy, request_hash,
idempotency_key, predecessor_runtime_run_id, expected_checkpoint_id,
runtime_version, agent_name, lease_owner, lease_epoch,
admission_contract_version, admission_snapshot_id, admission_snapshot_hash
"""
_EXTERNAL_PERMIT_COLUMNS = """
tenant_id, runtime_external_permit_id, runtime_run_id, runtime_thread_id,
task_step_id, task_execution_generation, admission_contract_version,
admission_snapshot_id, admission_snapshot_hash, operation_kind, intent_id,
request_hash, lease_owner, lease_epoch, permit_attempt, status,
requested_ttl_seconds, issued_at, expires_at, issue_event_id,
consume_event_id, consumed_by, consumed_at, updated_at
"""
_EXTERNAL_OPERATION_ATTEMPT_COLUMNS = """
tenant_id, runtime_external_permit_id, runtime_run_id, operation_kind,
intent_id, permit_attempt, task_execution_generation, admission_snapshot_id,
admission_snapshot_hash, request_hash, lease_owner, lease_epoch, arm_event_id,
armed_by, armed_at, status, last_event_id, source_fact_id,
source_fact_version, source_fact_hash, outcome_code, evidence_kind, result_hash,
recorded_by, outcome_recorded_at, updated_at
"""
_EXTERNAL_OPERATION_BARRIER_COLUMNS = """
tenant_id, runtime_run_id, task_execution_generation, lease_owner, lease_epoch,
dispatch_armed_count, outcome_unknown_count, blocking, oldest_blocking_at
"""


_SELECT_CANDIDATE_SQL = """
SELECT {candidate_columns} FROM deer_runtime.select_next_runtime_run_candidate(%s, %s, %s)
""".format(candidate_columns=_CANDIDATE_COLUMNS)
_ADMIT_SQL = """
SELECT {run_columns} FROM deer_runtime.admit_runtime_run(
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s
)
""".format(run_columns=_RUN_COLUMNS)
_CLAIM_SQL = """
SELECT {run_columns} FROM deer_runtime.claim_runtime_run(%s, %s, %s, %s, %s, %s)
""".format(run_columns=_RUN_COLUMNS)
_RENEW_LEASE_SQL = """
SELECT {run_columns} FROM deer_runtime.renew_runtime_run_lease(%s, %s, %s, %s, %s)
""".format(run_columns=_RUN_COLUMNS)
_TAKEOVER_SQL = """
SELECT {run_columns} FROM deer_runtime.takeover_runtime_run(%s, %s, %s, %s, %s, %s)
""".format(run_columns=_RUN_COLUMNS)
_AUTHORIZE_SQL = """
SELECT {run_columns} FROM deer_runtime.authorize_runtime_run(%s, %s, %s, %s)
""".format(run_columns=_RUN_COLUMNS)
_AUTHORIZE_CANCELLATION_SQL = """
SELECT {authority_columns}
FROM deer_runtime.authorize_runtime_run_cancellation(%s, %s, %s, %s)
""".format(authority_columns=_CANCELLATION_AUTHORITY_COLUMNS)
_LOAD_EXECUTION_AUTHORITY_SQL = """
SELECT {authority_columns}
FROM deer_runtime.load_runtime_execution_authority(%s, %s, %s, %s)
""".format(authority_columns=_EXECUTION_AUTHORITY_COLUMNS)
_ISSUE_EXTERNAL_PERMIT_SQL = """
SELECT {permit_columns}
FROM deer_runtime.issue_runtime_external_permit(
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
""".format(permit_columns=_EXTERNAL_PERMIT_COLUMNS)
_CONSUME_AND_AUTHORIZE_EXTERNAL_PERMIT_SQL = """
SELECT {permit_columns}
FROM deer_runtime.consume_and_authorize_runtime_external_permit(
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
""".format(permit_columns=_EXTERNAL_PERMIT_COLUMNS)
_CONSUME_AND_ARM_EXTERNAL_DISPATCH_SQL = """
SELECT dispatch_decision, {attempt_columns}
FROM deer_runtime.consume_and_arm_runtime_external_dispatch(
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
""".format(attempt_columns=_EXTERNAL_OPERATION_ATTEMPT_COLUMNS)
_RECORD_EXTERNAL_OPERATION_OUTCOME_SQL = """
SELECT {attempt_columns}
FROM deer_runtime.record_runtime_external_operation_outcome(
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s
)
""".format(attempt_columns=_EXTERNAL_OPERATION_ATTEMPT_COLUMNS)
_RECONCILE_EXTERNAL_OPERATION_OUTCOME_SQL = """
SELECT {attempt_columns}
FROM deer_runtime.reconcile_runtime_external_operation_outcome(
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s, %s
)
""".format(attempt_columns=_EXTERNAL_OPERATION_ATTEMPT_COLUMNS)
_LOAD_EXTERNAL_OPERATION_BARRIER_SQL = """
SELECT {barrier_columns}
FROM deer_runtime.load_runtime_external_operation_barrier(%s, %s, %s, %s, %s)
""".format(barrier_columns=_EXTERNAL_OPERATION_BARRIER_COLUMNS)
_APPEND_EVENT_SQL = """
SELECT {event_columns} FROM deer_runtime.append_runtime_run_event(
    %s, %s, %s, %s, %s, %s, %s, %s
)
""".format(event_columns=_EVENT_COLUMNS)
_RECORD_CHECKPOINT_SQL = """
SELECT {checkpoint_columns} FROM deer_runtime.record_runtime_checkpoint_ref(
    %s, %s, %s, %s, %s, %s, %s, %s, %s
)
""".format(checkpoint_columns=_CHECKPOINT_COLUMNS)
_REQUEST_CANCEL_SQL = """
SELECT {control_columns} FROM deer_runtime.request_runtime_run_cancel(
    %s, %s, %s, %s, %s, %s, %s, %s, %s
)
""".format(control_columns=_CONTROL_COLUMNS)
_BEGIN_CANCELLATION_SQL = """
SELECT {run_columns} FROM deer_runtime.begin_runtime_run_cancellation(%s, %s, %s, %s, %s, %s)
""".format(run_columns=_RUN_COLUMNS)
_COMPLETE_SQL = """
SELECT {run_columns} FROM deer_runtime.complete_runtime_run(%s, %s, %s, %s, %s, %s, %s)
""".format(run_columns=_RUN_COLUMNS)
_FAIL_SQL = """
SELECT {run_columns} FROM deer_runtime.fail_runtime_run(%s, %s, %s, %s, %s, %s, %s, %s)
""".format(run_columns=_RUN_COLUMNS)
_FINISH_CANCELLATION_SQL = """
SELECT {run_columns} FROM deer_runtime.finish_runtime_run_cancellation(
    %s, %s, %s, %s, %s, %s, %s, %s
)
""".format(run_columns=_RUN_COLUMNS)


FactT = TypeVar("FactT")
ConnectionFactory = Callable[[], Connection[dict[str, Any]]]
RowMapper = Callable[[Mapping[str, Any]], FactT]


class PostgresRunSupervisorRepository:
    """Dormant primitive adapter owning and closing one idle connection per call."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        if not callable(connection_factory):
            raise TypeError("connection_factory must be callable")
        self._connection_factory = connection_factory

    def select_next_candidate(
        self,
        request: SelectNextRuntimeRunCandidateRequest,
    ) -> PrimitiveResult[RuntimeRunCandidateFact]:
        return self._execute_read_one(
            SupervisorPrimitive.SELECT_CANDIDATE,
            _SELECT_CANDIDATE_SQL,
            (
                request.runtime_version,
                request.agent_name,
                request.admission_contract_version,
            ),
            _map_runtime_run_candidate,
        )

    def admit(
        self,
        request: AdmitRuntimeRunRequest,
    ) -> PrimitiveResult[RuntimeRunFact]:
        return self._execute_one(
            SupervisorPrimitive.ADMIT,
            _ADMIT_SQL,
            (
                request.tenant_id,
                request.runtime_thread_id,
                request.task_run_id,
                request.task_step_id,
                request.agent_instance_id,
                request.user_id,
                request.conversation_id,
                request.source_message_id,
                request.runtime_thread_revision,
                request.runtime_type,
                request.runtime_agent_name,
                request.capability_version_id,
                request.prompt_version_id,
                request.model_policy_id,
                request.budget_reservation_id,
                Jsonb(request.input_artifact_ids.to_builtin()),
                request.runtime_run_id,
                request.task_execution_generation,
                request.operation_kind.value,
                request.multitask_strategy.value,
                request.request_hash,
                request.idempotency_key,
                request.predecessor_runtime_run_id,
                request.expected_checkpoint_id,
                request.runtime_version,
                request.agent_name,
                request.admission_contract_version,
                request.admission_snapshot_id,
                request.admission_snapshot_hash,
                request.accepted_event_id,
                Jsonb(request.accepted_event_payload.to_builtin()),
            ),
            _map_runtime_run,
        )

    def claim(
        self,
        request: ClaimRuntimeRunRequest,
    ) -> PrimitiveResult[RuntimeRunFact]:
        return self._execute_one(
            SupervisorPrimitive.CLAIM,
            _CLAIM_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.lease_owner,
                request.lease_seconds,
                request.started_event_id,
                Jsonb(request.event_payload.to_builtin()),
            ),
            _map_runtime_run,
        )

    def renew_lease(
        self,
        request: RenewRuntimeRunLeaseRequest,
    ) -> PrimitiveResult[RuntimeRunFact]:
        return self._execute_one(
            SupervisorPrimitive.RENEW_LEASE,
            _RENEW_LEASE_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.lease_owner,
                request.lease_epoch,
                request.lease_seconds,
            ),
            _map_runtime_run,
        )

    def takeover(
        self,
        request: TakeoverRuntimeRunRequest,
    ) -> PrimitiveResult[RuntimeRunFact]:
        return self._execute_one(
            SupervisorPrimitive.TAKEOVER,
            _TAKEOVER_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.new_lease_owner,
                request.lease_seconds,
                request.takeover_event_id,
                Jsonb(request.event_payload.to_builtin()),
            ),
            _map_runtime_run,
        )

    def authorize(
        self,
        request: AuthorizeRuntimeRunRequest,
    ) -> PrimitiveResult[RuntimeRunFact]:
        return self._execute_read_one(
            SupervisorPrimitive.AUTHORIZE,
            _AUTHORIZE_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.lease_owner,
                request.lease_epoch,
            ),
            _map_runtime_run,
        )

    def authorize_cancellation(
        self,
        request: AuthorizeRuntimeRunCancellationRequest,
    ) -> PrimitiveResult[RuntimeCancellationAuthorityFact]:
        return self._execute_read_one(
            SupervisorPrimitive.AUTHORIZE_CANCELLATION,
            _AUTHORIZE_CANCELLATION_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.lease_owner,
                request.lease_epoch,
            ),
            _map_runtime_cancellation_authority,
        )

    def load_execution_authority(
        self,
        request: LoadRuntimeExecutionAuthorityRequest,
    ) -> PrimitiveResult[RuntimeExecutionAuthorityFact]:
        return self._execute_read_one(
            SupervisorPrimitive.LOAD_EXECUTION_AUTHORITY,
            _LOAD_EXECUTION_AUTHORITY_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.lease_owner,
                request.lease_epoch,
            ),
            _map_runtime_execution_authority,
        )

    def issue_external_permit(
        self,
        request: IssueRuntimeExternalPermitRequest,
    ) -> PrimitiveResult[RuntimeExternalPermitFact]:
        return self._execute_one(
            SupervisorPrimitive.ISSUE_EXTERNAL_PERMIT,
            _ISSUE_EXTERNAL_PERMIT_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.lease_owner,
                request.lease_epoch,
                request.runtime_external_permit_id,
                request.operation_kind.value,
                request.intent_id,
                request.request_hash,
                request.requested_ttl_seconds,
                request.issue_event_id,
            ),
            _map_runtime_external_permit,
        )

    def consume_and_authorize_external_permit(
        self,
        request: ConsumeRuntimeExternalPermitRequest,
    ) -> PrimitiveResult[RuntimeExternalPermitFact]:
        """Consume a permit and prove its Run fence is still current atomically."""
        return self._execute_one(
            SupervisorPrimitive.CONSUME_AND_AUTHORIZE_EXTERNAL_PERMIT,
            _CONSUME_AND_AUTHORIZE_EXTERNAL_PERMIT_SQL,
            _consume_external_permit_parameters(request),
            _map_runtime_external_permit,
        )

    def consume_and_arm_external_dispatch(
        self,
        request: ConsumeAndArmRuntimeExternalDispatchRequest,
    ) -> RuntimeExternalDispatchArmResult:
        result = self._execute_one(
            SupervisorPrimitive.CONSUME_AND_ARM_EXTERNAL_DISPATCH,
            _CONSUME_AND_ARM_EXTERNAL_DISPATCH_SQL,
            _external_dispatch_binding_parameters(request)
            + (request.arm_event_id, request.armed_by),
            _map_runtime_external_dispatch_arm,
        )
        if result.fact is None:
            return RuntimeExternalDispatchArmResult(
                outcome=PrimitiveOutcome.NOT_APPLIED,
                decision=None,
                fact=None,
            )
        return result.fact

    def record_external_operation_outcome(
        self,
        request: RecordRuntimeExternalOperationOutcomeRequest,
    ) -> PrimitiveResult[RuntimeExternalOperationAttemptFact]:
        return self._execute_one(
            SupervisorPrimitive.RECORD_EXTERNAL_OPERATION_OUTCOME,
            _RECORD_EXTERNAL_OPERATION_OUTCOME_SQL,
            _external_dispatch_binding_parameters(request)
            + (
                request.outcome_event_id,
                request.outcome_status.value,
                request.source_fact_id,
                request.source_fact_version,
                request.source_fact_hash,
                request.outcome_code,
                request.evidence_kind.value,
                request.result_hash,
                request.recorded_by,
            ),
            _map_runtime_external_operation_attempt,
        )

    def reconcile_external_operation_outcome(
        self,
        request: ReconcileRuntimeExternalOperationOutcomeRequest,
    ) -> PrimitiveResult[RuntimeExternalOperationAttemptFact]:
        return self._execute_one(
            SupervisorPrimitive.RECONCILE_EXTERNAL_OPERATION_OUTCOME,
            _RECONCILE_EXTERNAL_OPERATION_OUTCOME_SQL,
            _external_dispatch_binding_parameters(request)
            + (
                request.expected_unknown_event_id,
                request.reconcile_event_id,
                request.outcome_status.value,
                request.source_fact_id,
                request.source_fact_version,
                request.source_fact_hash,
                request.outcome_code,
                request.evidence_kind.value,
                request.result_hash,
                request.recorded_by,
            ),
            _map_runtime_external_operation_attempt,
        )

    def load_external_operation_barrier(
        self,
        request: LoadRuntimeExternalOperationBarrierRequest,
    ) -> PrimitiveResult[RuntimeExternalOperationBarrierFact]:
        return self._execute_read_one(
            SupervisorPrimitive.LOAD_EXTERNAL_OPERATION_BARRIER,
            _LOAD_EXTERNAL_OPERATION_BARRIER_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.task_execution_generation,
                request.lease_owner,
                request.lease_epoch,
            ),
            _map_runtime_external_operation_barrier,
        )

    def append_event(
        self,
        request: AppendRuntimeRunEventRequest,
    ) -> PrimitiveResult[RuntimeRunEventFact]:
        return self._execute_one(
            SupervisorPrimitive.APPEND_EVENT,
            _APPEND_EVENT_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.lease_owner,
                request.lease_epoch,
                request.event_id,
                request.event_type.value,
                request.event_version,
                Jsonb(request.payload.to_builtin()),
            ),
            _map_runtime_event,
        )

    def record_checkpoint(
        self,
        request: RecordRuntimeCheckpointRequest,
    ) -> PrimitiveResult[RuntimeCheckpointFact]:
        return self._execute_one(
            SupervisorPrimitive.RECORD_CHECKPOINT,
            _RECORD_CHECKPOINT_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.lease_owner,
                request.lease_epoch,
                request.event_id,
                request.checkpoint_id,
                request.checkpoint_namespace,
                request.checkpoint_schema_version,
                Jsonb(request.event_payload.to_builtin()),
            ),
            _map_runtime_checkpoint,
        )

    def request_cancel(
        self,
        request: RequestRuntimeRunCancelRequest,
    ) -> PrimitiveResult[RuntimeRunControlFact]:
        return self._execute_one(
            SupervisorPrimitive.REQUEST_CANCEL,
            _REQUEST_CANCEL_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.cancel_request_id,
                request.actor_id,
                request.reason_code,
                request.expected_run_version,
                request.idempotency_key,
                request.request_hash,
                Jsonb(request.event_payload.to_builtin()),
            ),
            _map_runtime_control,
        )

    def begin_cancellation(
        self,
        request: BeginRuntimeRunCancellationRequest,
    ) -> PrimitiveResult[RuntimeRunFact]:
        return self._execute_one(
            SupervisorPrimitive.BEGIN_CANCELLATION,
            _BEGIN_CANCELLATION_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.lease_owner,
                request.lease_epoch,
                request.event_id,
                Jsonb(request.event_payload.to_builtin()),
            ),
            _map_runtime_run,
        )

    def complete(
        self,
        request: CompleteRuntimeRunRequest,
    ) -> PrimitiveResult[RuntimeRunFact]:
        return self._execute_one(
            SupervisorPrimitive.COMPLETE,
            _COMPLETE_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.lease_owner,
                request.lease_epoch,
                request.event_id,
                request.terminal_reason,
                Jsonb(request.event_payload.to_builtin()),
            ),
            _map_runtime_run,
        )

    def fail(
        self,
        request: FailRuntimeRunRequest,
    ) -> PrimitiveResult[RuntimeRunFact]:
        return self._execute_one(
            SupervisorPrimitive.FAIL,
            _FAIL_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.lease_owner,
                request.lease_epoch,
                request.event_id,
                request.terminal_reason,
                request.failure_code,
                Jsonb(request.event_payload.to_builtin()),
            ),
            _map_runtime_run,
        )

    def finish_cancellation(
        self,
        request: FinishRuntimeRunCancellationRequest,
    ) -> PrimitiveResult[RuntimeRunFact]:
        return self._execute_one(
            SupervisorPrimitive.FINISH_CANCELLATION,
            _FINISH_CANCELLATION_SQL,
            (
                request.tenant_id,
                request.runtime_run_id,
                request.lease_owner,
                request.lease_epoch,
                request.terminal_status.value,
                request.event_id,
                request.terminal_reason,
                Jsonb(request.event_payload.to_builtin()),
            ),
            _map_runtime_run,
        )

    def _execute_one(
        self,
        primitive: SupervisorPrimitive,
        statement: str,
        parameters: Sequence[object],
        mapper: RowMapper[FactT],
        *,
        connection_loss_has_unknown_outcome: bool = True,
    ) -> PrimitiveResult[FactT]:
        try:
            connection = self._connection_factory()
        except Exception as exception:
            raise SupervisorUnavailable(
                SupervisorErrorCode.UNAVAILABLE,
                primitive,
                _sqlstate(exception),
                f"Supervisor database is unavailable for {primitive.value}",
            ) from exception

        try:
            if connection.closed or (
                connection.info.transaction_status != TransactionStatus.IDLE
            ):
                raise SupervisorIntegrityOrContractViolation(
                    SupervisorErrorCode.INTEGRITY_OR_CONTRACT_VIOLATION,
                    primitive,
                    "",
                    "Supervisor connection factory must provide a new idle connection",
                )
        except SupervisorRepositoryError:
            try:
                connection.close()
            except Exception:
                pass
            raise
        except Exception as exception:
            try:
                connection.close()
            except Exception:
                pass
            raise SupervisorUnavailable(
                SupervisorErrorCode.UNAVAILABLE,
                primitive,
                _sqlstate(exception),
                f"Supervisor database is unavailable for {primitive.value}",
            ) from exception

        stage = "BEGIN"
        try:
            with connection.transaction():
                stage = "EXECUTE"
                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(statement, parameters)
                    rows = cursor.fetchall()
                    if len(rows) > 1:
                        raise SupervisorIntegrityOrContractViolation(
                            SupervisorErrorCode.INTEGRITY_OR_CONTRACT_VIOLATION,
                            primitive,
                            "",
                            f"Supervisor primitive {primitive.value} returned multiple facts",
                        )
                    row = rows[0] if rows else None
                    fact = (
                        mapper(cast(Mapping[str, Any], row))
                        if row is not None
                        else None
                    )
                stage = "COMMIT"
            return PrimitiveResult(
                outcome=(
                    PrimitiveOutcome.FACT_RETURNED
                    if fact is not None
                    else PrimitiveOutcome.NOT_APPLIED
                ),
                fact=fact,
            )
        except SupervisorRepositoryError:
            raise
        except psycopg.Error as exception:
            mapped = _map_database_error(primitive, exception)
            if mapped is not None:
                raise mapped from exception
            if (
                stage != "BEGIN"
                and _is_connection_error(exception)
                and connection_loss_has_unknown_outcome
            ):
                raise SupervisorOutcomeUnknown(
                    SupervisorErrorCode.OUTCOME_UNKNOWN,
                    primitive,
                    _sqlstate(exception),
                    f"Supervisor primitive {primitive.value} outcome is unknown",
                ) from exception
            if _is_connection_error(exception):
                raise SupervisorUnavailable(
                    SupervisorErrorCode.UNAVAILABLE,
                    primitive,
                    _sqlstate(exception),
                    f"Supervisor database is unavailable for {primitive.value}",
                ) from exception
            raise SupervisorIntegrityOrContractViolation(
                SupervisorErrorCode.INTEGRITY_OR_CONTRACT_VIOLATION,
                primitive,
                _sqlstate(exception),
                f"Supervisor primitive {primitive.value} failed outside its SQL contract",
            ) from exception
        except Exception as exception:
            if stage != "BEGIN":
                raise SupervisorIntegrityOrContractViolation(
                    SupervisorErrorCode.INTEGRITY_OR_CONTRACT_VIOLATION,
                    primitive,
                    "",
                    f"Supervisor primitive {primitive.value} broke its result contract",
                ) from exception
            raise
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def _execute_read_one(
        self,
        primitive: SupervisorPrimitive,
        statement: str,
        parameters: Sequence[object],
        mapper: RowMapper[FactT],
    ) -> PrimitiveResult[FactT]:
        """Execute a pure read whose connection loss never hides a durable write."""
        return self._execute_one(
            primitive,
            statement,
            parameters,
            mapper,
            connection_loss_has_unknown_outcome=False,
        )


def _map_database_error(
    primitive: SupervisorPrimitive,
    exception: psycopg.Error,
) -> SupervisorRepositoryError | None:
    sqlstate = exception.sqlstate
    if sqlstate is None:
        return None
    if sqlstate == "23505":
        return SupervisorCommandConflict(
            SupervisorErrorCode.COMMAND_CONFLICT,
            primitive,
            sqlstate,
            f"Supervisor primitive {primitive.value} rejected a conflicting command",
        )
    if sqlstate == "22023":
        return SupervisorInvalidCommand(
            SupervisorErrorCode.INVALID_COMMAND,
            primitive,
            sqlstate,
            f"Supervisor primitive {primitive.value} rejected invalid arguments",
        )
    if sqlstate.startswith("22"):
        return SupervisorInvalidCommand(
            SupervisorErrorCode.INVALID_COMMAND,
            primitive,
            sqlstate,
            f"Supervisor primitive {primitive.value} rejected invalid data",
        )
    if sqlstate == "0A000":
        return SupervisorUnsupportedCommand(
            SupervisorErrorCode.UNSUPPORTED_COMMAND,
            primitive,
            sqlstate,
            f"Supervisor primitive {primitive.value} is not supported for this request",
        )
    if sqlstate == "42501":
        return SupervisorPermissionBoundaryMisconfigured(
            SupervisorErrorCode.PERMISSION_BOUNDARY_MISCONFIGURED,
            primitive,
            sqlstate,
            f"Supervisor primitive {primitive.value} is not permitted or configured",
        )
    if sqlstate == "55000":
        return SupervisorIntegrityOrContractViolation(
            SupervisorErrorCode.INTEGRITY_OR_CONTRACT_VIOLATION,
            primitive,
            sqlstate,
            f"Supervisor primitive {primitive.value} violated a durable invariant",
        )
    if sqlstate.startswith("23"):
        return SupervisorIntegrityOrContractViolation(
            SupervisorErrorCode.INTEGRITY_OR_CONTRACT_VIOLATION,
            primitive,
            sqlstate,
            f"Supervisor primitive {primitive.value} violated database integrity",
        )
    if sqlstate in {"40001", "40P01"}:
        return SupervisorTransientConflict(
            SupervisorErrorCode.TRANSIENT_CONFLICT,
            primitive,
            sqlstate,
            f"Supervisor primitive {primitive.value} encountered a transient conflict",
        )
    return None


def _consume_external_permit_parameters(
    request: ConsumeRuntimeExternalPermitRequest,
) -> tuple[object, ...]:
    return (
        request.tenant_id,
        request.runtime_external_permit_id,
        request.runtime_run_id,
        request.task_execution_generation,
        request.lease_owner,
        request.lease_epoch,
        request.admission_snapshot_id,
        request.admission_snapshot_hash,
        request.operation_kind.value,
        request.intent_id,
        request.request_hash,
        request.consume_event_id,
        request.consumed_by,
    )


def _external_dispatch_binding_parameters(
    request: (
        ConsumeAndArmRuntimeExternalDispatchRequest
        | RecordRuntimeExternalOperationOutcomeRequest
        | ReconcileRuntimeExternalOperationOutcomeRequest
    ),
) -> tuple[object, ...]:
    return (
        request.tenant_id,
        request.runtime_external_permit_id,
        request.runtime_run_id,
        request.task_execution_generation,
        request.lease_owner,
        request.lease_epoch,
        request.admission_snapshot_id,
        request.admission_snapshot_hash,
        request.operation_kind.value,
        request.intent_id,
        request.request_hash,
    )


def _sqlstate(exception: object) -> str:
    value = getattr(exception, "sqlstate", None)
    return value if isinstance(value, str) else ""


def _is_connection_error(exception: psycopg.Error) -> bool:
    return isinstance(exception, (psycopg.OperationalError, psycopg.InterfaceError)) or (
        exception.sqlstate is not None and exception.sqlstate.startswith("08")
    )


def _map_runtime_run(row: Mapping[str, Any]) -> RuntimeRunFact:
    return RuntimeRunFact(
        tenant_id=_uuid(row, "tenant_id"),
        runtime_run_id=_uuid(row, "runtime_run_id"),
        runtime_thread_id=_uuid(row, "runtime_thread_id"),
        task_step_id=_uuid(row, "task_step_id"),
        task_execution_generation=_integer(row, "task_execution_generation"),
        status=RuntimeStatus(_text(row, "status")),
        operation_kind=OperationKind(_text(row, "operation_kind")),
        multitask_strategy=MultitaskStrategy(_text(row, "multitask_strategy")),
        request_hash=_text(row, "request_hash"),
        idempotency_key=_text(row, "idempotency_key"),
        predecessor_runtime_run_id=_optional_uuid(row, "predecessor_runtime_run_id"),
        expected_checkpoint_id=_optional_text(row, "expected_checkpoint_id"),
        current_checkpoint_id=_optional_text(row, "current_checkpoint_id"),
        current_checkpoint_sequence_no=_optional_integer(
            row,
            "current_checkpoint_sequence_no",
        ),
        next_event_sequence_no=_integer(row, "next_event_sequence_no"),
        event_retention_floor_sequence=_integer(
            row,
            "event_retention_floor_sequence",
        ),
        run_version=_integer(row, "run_version"),
        terminal_reason=_optional_text(row, "terminal_reason"),
        terminal_event_id=_optional_uuid(row, "terminal_event_id"),
        lease_owner=_optional_text(row, "lease_owner"),
        lease_until=_optional_utc_datetime(row, "lease_until"),
        lease_epoch=_integer(row, "lease_epoch"),
        heartbeat_at=_optional_utc_datetime(row, "heartbeat_at"),
        attempt=_integer(row, "attempt"),
        runtime_version=_text(row, "runtime_version"),
        agent_name=_text(row, "agent_name"),
        failure_code=_optional_text(row, "failure_code"),
        cancel_requested_at=_optional_utc_datetime(row, "cancel_requested_at"),
        started_at=_optional_utc_datetime(row, "started_at"),
        terminal_at=_optional_utc_datetime(row, "terminal_at"),
        created_at=_utc_datetime(row, "created_at"),
        updated_at=_utc_datetime(row, "updated_at"),
    )


def _map_runtime_run_candidate(row: Mapping[str, Any]) -> RuntimeRunCandidateFact:
    return RuntimeRunCandidateFact(
        tenant_id=_uuid(row, "tenant_id"),
        runtime_run_id=_uuid(row, "runtime_run_id"),
    )


def _map_runtime_cancellation_authority(
    row: Mapping[str, Any],
) -> RuntimeCancellationAuthorityFact:
    return RuntimeCancellationAuthorityFact(
        tenant_id=_uuid(row, "tenant_id"),
        runtime_run_id=_uuid(row, "runtime_run_id"),
        runtime_thread_id=_uuid(row, "runtime_thread_id"),
        task_step_id=_uuid(row, "task_step_id"),
        task_execution_generation=_integer(row, "task_execution_generation"),
        status=RuntimeStatus(_text(row, "status")),
        lease_owner=_text(row, "lease_owner"),
        lease_epoch=_integer(row, "lease_epoch"),
        run_version=_integer(row, "run_version"),
        cancel_requested_at=_utc_datetime(row, "cancel_requested_at"),
    )


def _map_runtime_execution_authority(
    row: Mapping[str, Any],
) -> RuntimeExecutionAuthorityFact:
    return RuntimeExecutionAuthorityFact(
        tenant_id=_uuid(row, "tenant_id"),
        runtime_run_id=_uuid(row, "runtime_run_id"),
        runtime_thread_id=_uuid(row, "runtime_thread_id"),
        task_run_id=_uuid(row, "task_run_id"),
        task_step_id=_uuid(row, "task_step_id"),
        task_execution_generation=_integer(row, "task_execution_generation"),
        agent_instance_id=_uuid(row, "agent_instance_id"),
        user_id=_uuid(row, "user_id"),
        conversation_id=_uuid(row, "conversation_id"),
        source_message_id=_optional_uuid(row, "source_message_id"),
        runtime_thread_revision=_integer(row, "runtime_thread_revision"),
        runtime_type=_text(row, "runtime_type"),
        runtime_agent_name=_text(row, "runtime_agent_name"),
        capability_version_id=_uuid(row, "capability_version_id"),
        prompt_version_id=_uuid(row, "prompt_version_id"),
        model_policy_id=_uuid(row, "model_policy_id"),
        budget_reservation_id=_uuid(row, "budget_reservation_id"),
        operation_kind=OperationKind(_text(row, "operation_kind")),
        multitask_strategy=MultitaskStrategy(_text(row, "multitask_strategy")),
        request_hash=_text(row, "request_hash"),
        idempotency_key=_text(row, "idempotency_key"),
        predecessor_runtime_run_id=_optional_uuid(row, "predecessor_runtime_run_id"),
        expected_checkpoint_id=_optional_text(row, "expected_checkpoint_id"),
        runtime_version=_text(row, "runtime_version"),
        agent_name=_text(row, "agent_name"),
        lease_owner=_text(row, "lease_owner"),
        lease_epoch=_integer(row, "lease_epoch"),
        admission_contract_version=_text(row, "admission_contract_version"),
        admission_snapshot_id=_uuid(row, "admission_snapshot_id"),
        admission_snapshot_hash=_text(row, "admission_snapshot_hash"),
    )


def _map_runtime_external_permit(
    row: Mapping[str, Any],
) -> RuntimeExternalPermitFact:
    return RuntimeExternalPermitFact(
        tenant_id=_uuid(row, "tenant_id"),
        runtime_external_permit_id=_uuid(row, "runtime_external_permit_id"),
        runtime_run_id=_uuid(row, "runtime_run_id"),
        runtime_thread_id=_uuid(row, "runtime_thread_id"),
        task_step_id=_uuid(row, "task_step_id"),
        task_execution_generation=_integer(row, "task_execution_generation"),
        admission_contract_version=_text(row, "admission_contract_version"),
        admission_snapshot_id=_uuid(row, "admission_snapshot_id"),
        admission_snapshot_hash=_text(row, "admission_snapshot_hash"),
        operation_kind=ExternalOperation(_text(row, "operation_kind")),
        intent_id=_uuid(row, "intent_id"),
        request_hash=_text(row, "request_hash"),
        lease_owner=_text(row, "lease_owner"),
        lease_epoch=_integer(row, "lease_epoch"),
        permit_attempt=_integer(row, "permit_attempt"),
        status=ExternalPermitStatus(_text(row, "status")),
        requested_ttl_seconds=_integer(row, "requested_ttl_seconds"),
        issued_at=_utc_datetime(row, "issued_at"),
        expires_at=_utc_datetime(row, "expires_at"),
        issue_event_id=_uuid(row, "issue_event_id"),
        consume_event_id=_optional_uuid(row, "consume_event_id"),
        consumed_by=_optional_text(row, "consumed_by"),
        consumed_at=_optional_utc_datetime(row, "consumed_at"),
        updated_at=_utc_datetime(row, "updated_at"),
    )


def _map_runtime_external_dispatch_arm(
    row: Mapping[str, Any],
) -> RuntimeExternalDispatchArmResult:
    return RuntimeExternalDispatchArmResult(
        outcome=PrimitiveOutcome.FACT_RETURNED,
        decision=ExternalDispatchArmDecision(_text(row, "dispatch_decision")),
        fact=_map_runtime_external_operation_attempt(row),
    )


def _map_runtime_external_operation_attempt(
    row: Mapping[str, Any],
) -> RuntimeExternalOperationAttemptFact:
    evidence_kind = _optional_text(row, "evidence_kind")
    return RuntimeExternalOperationAttemptFact(
        tenant_id=_uuid(row, "tenant_id"),
        runtime_external_permit_id=_uuid(row, "runtime_external_permit_id"),
        runtime_run_id=_uuid(row, "runtime_run_id"),
        operation_kind=ExternalOperation(_text(row, "operation_kind")),
        intent_id=_uuid(row, "intent_id"),
        permit_attempt=_integer(row, "permit_attempt"),
        task_execution_generation=_integer(row, "task_execution_generation"),
        admission_snapshot_id=_uuid(row, "admission_snapshot_id"),
        admission_snapshot_hash=_text(row, "admission_snapshot_hash"),
        request_hash=_text(row, "request_hash"),
        lease_owner=_text(row, "lease_owner"),
        lease_epoch=_integer(row, "lease_epoch"),
        arm_event_id=_uuid(row, "arm_event_id"),
        armed_by=_text(row, "armed_by"),
        armed_at=_utc_datetime(row, "armed_at"),
        status=ExternalOperationAttemptStatus(_text(row, "status")),
        last_event_id=_uuid(row, "last_event_id"),
        source_fact_id=_optional_uuid(row, "source_fact_id"),
        source_fact_version=_optional_integer(row, "source_fact_version"),
        source_fact_hash=_optional_text(row, "source_fact_hash"),
        outcome_code=_optional_text(row, "outcome_code"),
        evidence_kind=(
            ExternalOutcomeEvidenceKind(evidence_kind)
            if evidence_kind is not None
            else None
        ),
        result_hash=_optional_text(row, "result_hash"),
        recorded_by=_optional_text(row, "recorded_by"),
        outcome_recorded_at=_optional_utc_datetime(row, "outcome_recorded_at"),
        updated_at=_utc_datetime(row, "updated_at"),
    )


def _map_runtime_external_operation_barrier(
    row: Mapping[str, Any],
) -> RuntimeExternalOperationBarrierFact:
    return RuntimeExternalOperationBarrierFact(
        tenant_id=_uuid(row, "tenant_id"),
        runtime_run_id=_uuid(row, "runtime_run_id"),
        task_execution_generation=_integer(row, "task_execution_generation"),
        lease_owner=_text(row, "lease_owner"),
        lease_epoch=_integer(row, "lease_epoch"),
        dispatch_armed_count=_integer(row, "dispatch_armed_count"),
        outcome_unknown_count=_integer(row, "outcome_unknown_count"),
        blocking=_boolean(row, "blocking"),
        oldest_blocking_at=_optional_utc_datetime(row, "oldest_blocking_at"),
    )


def _map_runtime_event(row: Mapping[str, Any]) -> RuntimeRunEventFact:
    return RuntimeRunEventFact(
        tenant_id=_uuid(row, "tenant_id"),
        runtime_run_id=_uuid(row, "runtime_run_id"),
        runtime_thread_id=_uuid(row, "runtime_thread_id"),
        event_id=_uuid(row, "event_id"),
        sequence_no=_integer(row, "sequence_no"),
        event_type=_text(row, "event_type"),
        event_version=_integer(row, "event_version"),
        run_version=_integer(row, "run_version"),
        lease_owner=_optional_text(row, "lease_owner"),
        lease_epoch=_integer(row, "lease_epoch"),
        checkpoint_id=_optional_text(row, "checkpoint_id"),
        payload=FrozenJsonObject(_mapping(row, "payload")),
        occurred_at=_utc_datetime(row, "occurred_at"),
        created_at=_utc_datetime(row, "created_at"),
    )


def _map_runtime_checkpoint(row: Mapping[str, Any]) -> RuntimeCheckpointFact:
    return RuntimeCheckpointFact(
        tenant_id=_uuid(row, "tenant_id"),
        runtime_run_id=_uuid(row, "runtime_run_id"),
        runtime_thread_id=_uuid(row, "runtime_thread_id"),
        checkpoint_id=_text(row, "checkpoint_id"),
        checkpoint_namespace=_text(row, "checkpoint_namespace"),
        sequence_no=_integer(row, "sequence_no"),
        event_id=_uuid(row, "event_id"),
        run_version=_integer(row, "run_version"),
        lease_epoch=_integer(row, "lease_epoch"),
        checkpoint_schema_version=_text(row, "checkpoint_schema_version"),
        created_at=_utc_datetime(row, "created_at"),
    )


def _map_runtime_control(row: Mapping[str, Any]) -> RuntimeRunControlFact:
    return RuntimeRunControlFact(
        tenant_id=_uuid(row, "tenant_id"),
        control_id=_uuid(row, "control_id"),
        runtime_run_id=_uuid(row, "runtime_run_id"),
        runtime_thread_id=_uuid(row, "runtime_thread_id"),
        control_type=_text(row, "control_type"),
        actor_id=_uuid(row, "actor_id"),
        reason_code=_text(row, "reason_code"),
        expected_run_version=_integer(row, "expected_run_version"),
        idempotency_key=_text(row, "idempotency_key"),
        request_hash=_text(row, "request_hash"),
        created_at=_utc_datetime(row, "created_at"),
    )


def _value(row: Mapping[str, Any], name: str) -> Any:
    if name not in row:
        raise RuntimeError(f"Supervisor primitive result is missing {name}")
    return row[name]


def _uuid(row: Mapping[str, Any], name: str) -> UUID:
    value = _value(row, name)
    if not isinstance(value, UUID):
        raise TypeError(f"Supervisor primitive result {name} must be a UUID")
    return value


def _optional_uuid(row: Mapping[str, Any], name: str) -> UUID | None:
    value = _value(row, name)
    if value is None:
        return None
    if not isinstance(value, UUID):
        raise TypeError(f"Supervisor primitive result {name} must be a UUID or null")
    return value


def _integer(row: Mapping[str, Any], name: str) -> int:
    value = _value(row, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"Supervisor primitive result {name} must be an integer")
    return value


def _optional_integer(row: Mapping[str, Any], name: str) -> int | None:
    value = _value(row, name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"Supervisor primitive result {name} must be an integer or null")
    return value


def _boolean(row: Mapping[str, Any], name: str) -> bool:
    value = _value(row, name)
    if not isinstance(value, bool):
        raise TypeError(f"Supervisor primitive result {name} must be a boolean")
    return value


def _text(row: Mapping[str, Any], name: str) -> str:
    value = _value(row, name)
    if not isinstance(value, str):
        raise TypeError(f"Supervisor primitive result {name} must be text")
    return value


def _optional_text(row: Mapping[str, Any], name: str) -> str | None:
    value = _value(row, name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"Supervisor primitive result {name} must be text or null")
    return value


def _mapping(row: Mapping[str, Any], name: str) -> Mapping[str, object]:
    value = _value(row, name)
    if not isinstance(value, Mapping):
        raise TypeError(f"Supervisor primitive result {name} must be a JSON object")
    return cast(Mapping[str, object], value)


def _utc_datetime(row: Mapping[str, Any], name: str) -> datetime:
    value = _value(row, name)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(f"Supervisor primitive result {name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _optional_utc_datetime(row: Mapping[str, Any], name: str) -> datetime | None:
    value = _value(row, name)
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TypeError(
            f"Supervisor primitive result {name} must be timezone-aware or null"
        )
    return value.astimezone(timezone.utc)

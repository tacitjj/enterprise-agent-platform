from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from dianlian_runtime.app import create_app
from dianlian_runtime.auth import InternalServicePrincipal, InternalServiceScope
from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.supervisor.authorizer_contracts import (
    ExternalOperationOutcomeApiResult,
    ExternalOperationOutcomeRecordRequest,
    ExternalOperationOutcomeReconcileRequest,
)
from dianlian_runtime.supervisor.contracts import (
    ExternalOperationAttemptStatus,
    ExternalOutcomeEvidenceKind,
    PrimitiveOutcome,
    PrimitiveResult,
    RuntimeExternalOperationAttemptFact,
    SupervisorCommandConflict,
    SupervisorErrorCode,
    SupervisorPrimitive,
    SupervisorUnavailable,
)
from dianlian_runtime.supervisor.outcome_reconciler import (
    ExternalOperationOutcomeConflict,
    ExternalOperationOutcomeUnavailable,
    PostgresExternalOperationOutcomeService,
    create_postgres_external_operation_outcome_service,
)


RECORD_ROUTE = "/internal/v1/runtime-supervisor/external-operation-outcomes/record"
RECONCILE_ROUTE = (
    "/internal/v1/runtime-supervisor/external-operation-outcomes/reconcile"
)
HASH = "a" * 64
TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
PERMIT_ID = UUID("00000000-0000-4000-8000-000000000002")
RUN_ID = UUID("00000000-0000-4000-8000-000000000003")
SNAPSHOT_ID = UUID("00000000-0000-4000-8000-000000000004")
INTENT_ID = UUID("00000000-0000-4000-8000-000000000005")
ARM_EVENT_ID = UUID("00000000-0000-4000-8000-000000000006")
OUTCOME_EVENT_ID = UUID("00000000-0000-4000-8000-000000000007")
SOURCE_FACT_ID = UUID("00000000-0000-4000-8000-000000000008")
RECONCILE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000009")
NOW = datetime(2026, 8, 13, tzinfo=timezone.utc)


def _settings(*, enabled: bool = True) -> RuntimeSettings:
    return RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="runtime-api",
        context_enabled=False,
        agent_enabled=False,
        supervisor_enabled=False,
        outcome_reconciler_enabled=enabled,
    )


def _record_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "tenantId": str(TENANT_ID),
        "runtimeExternalPermitId": str(PERMIT_ID),
        "runtimeRunId": str(RUN_ID),
        "taskExecutionGeneration": 1,
        "leaseOwner": "worker-1",
        "leaseEpoch": 1,
        "admissionSnapshotId": str(SNAPSHOT_ID),
        "admissionSnapshotHash": HASH,
        "operationKind": "MODEL_INVOKE",
        "intentId": str(INTENT_ID),
        "requestHash": HASH,
        "outcomeEventId": str(OUTCOME_EVENT_ID),
        "outcomeStatus": "OUTCOME_UNKNOWN",
        "sourceFactId": str(SOURCE_FACT_ID),
        "sourceFactVersion": 1,
        "sourceFactHash": HASH,
        "outcomeCode": "JAVA_OUTCOME_UNKNOWN",
        "resultHash": None,
    }
    payload.update(changes)
    return payload


def _reconcile_payload(**changes: object) -> dict[str, object]:
    payload = _record_payload(
        expectedUnknownEventId=str(OUTCOME_EVENT_ID),
        reconcileEventId=str(RECONCILE_EVENT_ID),
        outcomeStatus="SUCCEEDED",
        sourceFactVersion=2,
        outcomeCode="JAVA_SUCCEEDED_CONFIRMED",
        resultHash=HASH,
    )
    payload.pop("outcomeEventId")
    payload.update(changes)
    return payload


class ExactAuthenticator:
    ready = True

    def authorize(self, token: str, required_scope: InternalServiceScope):
        if token != "valid":
            raise AssertionError("unexpected token")
        return InternalServicePrincipal(
            subject="dianlian-platform",
            token_id=UUID("00000000-0000-4000-8000-000000000010"),
            scopes=frozenset({required_scope}),
            issued_at=1,
            expires_at=2,
        )


class RecordingService:
    ready = True

    def __init__(self, result: ExternalOperationOutcomeApiResult):
        self.result = result
        self.calls: list[tuple[str, object, str]] = []

    def record(self, request, *, recorded_by: str):
        self.calls.append(("record", request, recorded_by))
        return self.result

    def reconcile(self, request, *, recorded_by: str):
        self.calls.append(("reconcile", request, recorded_by))
        return self.result


def _client(
    service: object,
    *,
    enabled: bool = True,
    authenticator: object | None = None,
) -> TestClient:
    return TestClient(
        create_app(
            _settings(enabled=enabled),
            internal_service_authenticator=authenticator or ExactAuthenticator(),
            external_operation_outcome_service=service,  # type: ignore[arg-type]
        )
    )


def test_routes_are_hidden_when_disabled_and_derive_recorded_by() -> None:
    service = RecordingService(ExternalOperationOutcomeApiResult.APPLIED)
    disabled = _client(service, enabled=False)
    assert disabled.post(RECORD_ROUTE, json=_record_payload()).status_code == 404
    assert disabled.post(RECONCILE_ROUTE, json=_reconcile_payload()).status_code == 404
    assert disabled.post(RECORD_ROUTE, content=b"{" + b" " * 9000).status_code == 404

    with _client(service) as client:
        record = client.post(
            RECORD_ROUTE,
            json=_record_payload(),
            headers={"Authorization": "Bearer valid"},
        )
        reconcile = client.post(
            RECONCILE_ROUTE,
            json=_reconcile_payload(),
            headers={"Authorization": "Bearer valid"},
        )
    assert record.status_code == reconcile.status_code == 200
    assert record.json() == reconcile.json() == {"outcome": "APPLIED"}
    assert [call[0] for call in service.calls] == ["record", "reconcile"]
    assert all(call[2] == "dianlian-platform" for call in service.calls)


@pytest.mark.parametrize("route", [RECORD_ROUTE, RECONCILE_ROUTE])
def test_not_applied_response_remains_single_field(route: str) -> None:
    service = RecordingService(ExternalOperationOutcomeApiResult.NOT_APPLIED)
    payload = _record_payload() if route == RECORD_ROUTE else _reconcile_payload()
    with _client(service) as client:
        response = client.post(
            route,
            json=payload,
            headers={"Authorization": "Bearer valid"},
        )
    assert response.status_code == 200
    assert response.json() == {"outcome": "NOT_APPLIED"}


@pytest.mark.parametrize("forbidden", ["recordedBy", "evidenceKind"])
def test_body_cannot_override_authority_fields(forbidden: str) -> None:
    payload = _record_payload(**{forbidden: "untrusted"})
    with _client(RecordingService(ExternalOperationOutcomeApiResult.APPLIED)) as client:
        response = client.post(
            RECORD_ROUTE,
            json=payload,
            headers={"Authorization": "Bearer valid"},
        )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("route", "payload"),
    [
        (RECORD_ROUTE, _record_payload(resultHash=HASH)),
        (RECORD_ROUTE, _record_payload(outcomeStatus="SUCCEEDED", resultHash=None)),
        (RECONCILE_ROUTE, _reconcile_payload(outcomeStatus="OUTCOME_UNKNOWN", resultHash=None)),
        (RECONCILE_ROUTE, _reconcile_payload(sourceFactVersion=1.0)),
    ],
)
def test_strict_outcome_contract_rejects_invalid_version_status_and_hash(
    route: str,
    payload: dict[str, object],
) -> None:
    with _client(RecordingService(ExternalOperationOutcomeApiResult.APPLIED)) as client:
        response = client.post(
            route,
            json=payload,
            headers={"Authorization": "Bearer valid"},
        )
    assert response.status_code == 422


@pytest.mark.parametrize("route", [RECORD_ROUTE, RECONCILE_ROUTE])
def test_enabled_body_guard_rejects_duplicate_keys_and_large_bodies(route: str) -> None:
    payload = _record_payload() if route == RECORD_ROUTE else _reconcile_payload()
    body = json.dumps(payload)
    duplicate = body[:-1] + ',"tenantId":"00000000-0000-4000-8000-000000000099"}'
    with _client(RecordingService(ExternalOperationOutcomeApiResult.APPLIED)) as client:
        duplicate_response = client.post(
            route,
            content=duplicate,
            headers={
                "Authorization": "Bearer valid",
                "Content-Type": "application/json",
            },
        )
        large_response = client.post(
            route,
            content=b"{" + b" " * 9000 + b"}",
            headers={
                "Authorization": "Bearer valid",
                "Content-Type": "application/json",
            },
        )
    assert duplicate_response.status_code == 422
    assert large_response.status_code == 413


def test_routes_require_separate_exact_scopes_and_openapi_declares_413() -> None:
    class MultiScopeAuthenticator(ExactAuthenticator):
        def authorize(self, token: str, required_scope: InternalServiceScope):
            principal = super().authorize(token, required_scope)
            return replace(
                principal,
                scopes=frozenset(
                    {
                        InternalServiceScope.RUNTIME_EXTERNAL_OUTCOME_RECORD,
                        InternalServiceScope.RUNTIME_EXTERNAL_OUTCOME_RECONCILE,
                    }
                ),
            )

    with _client(
        service := RecordingService(ExternalOperationOutcomeApiResult.APPLIED),
        authenticator=MultiScopeAuthenticator(),
    ) as client:
        assert client.post(
            RECORD_ROUTE,
            json=_record_payload(),
            headers={"Authorization": "Bearer valid"},
        ).status_code == 403
        assert client.post(
            RECONCILE_ROUTE,
            json=_reconcile_payload(),
            headers={"Authorization": "Bearer valid"},
        ).status_code == 403
        schema = client.get("/internal/v1/openapi.json").json()
    assert service.calls == []
    assert schema["paths"][RECORD_ROUTE]["post"]["x-required-scopes"] == [
        "runtime.external-outcome.record"
    ]
    assert schema["paths"][RECONCILE_ROUTE]["post"]["x-required-scopes"] == [
        "runtime.external-outcome.reconcile"
    ]
    assert "413" in schema["paths"][RECORD_ROUTE]["post"]["responses"]
    assert "413" in schema["paths"][RECONCILE_ROUTE]["post"]["responses"]


@pytest.mark.parametrize(
    ("route", "payload", "wrong_scope"),
    [
        (
            RECORD_ROUTE,
            _record_payload(),
            InternalServiceScope.RUNTIME_EXTERNAL_OUTCOME_RECONCILE,
        ),
        (
            RECONCILE_ROUTE,
            _reconcile_payload(),
            InternalServiceScope.RUNTIME_EXTERNAL_OUTCOME_RECORD,
        ),
    ],
)
def test_record_and_reconcile_scopes_are_not_interchangeable(
    route: str,
    payload: dict[str, object],
    wrong_scope: InternalServiceScope,
) -> None:
    class WrongScopeAuthenticator(ExactAuthenticator):
        def authorize(self, token: str, required_scope: InternalServiceScope):
            principal = super().authorize(token, required_scope)
            return replace(principal, scopes=frozenset({wrong_scope}))

    service = RecordingService(ExternalOperationOutcomeApiResult.APPLIED)
    with _client(service, authenticator=WrongScopeAuthenticator()) as client:
        response = client.post(
            route,
            json=payload,
            headers={"Authorization": "Bearer valid"},
        )
    assert response.status_code == 403
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ExternalOperationOutcomeConflict("must-not-leak"), 409),
        (ExternalOperationOutcomeUnavailable("must-not-leak"), 503),
    ],
)
def test_api_maps_service_errors_without_leaking_details(
    error: Exception,
    expected_status: int,
) -> None:
    class FailingService(RecordingService):
        def record(self, request, *, recorded_by: str):
            raise error

    with _client(FailingService(ExternalOperationOutcomeApiResult.APPLIED)) as client:
        response = client.post(
            RECORD_ROUTE,
            json=_record_payload(),
            headers={"Authorization": "Bearer valid"},
        )
    assert response.status_code == expected_status
    assert "must-not-leak" not in response.text


def _record_model() -> ExternalOperationOutcomeRecordRequest:
    return ExternalOperationOutcomeRecordRequest.model_validate(_record_payload())


def _reconcile_model() -> ExternalOperationOutcomeReconcileRequest:
    return ExternalOperationOutcomeReconcileRequest.model_validate(_reconcile_payload())


def _fact(command: object, *, reconciled: bool = False) -> RuntimeExternalOperationAttemptFact:
    outcome_status = getattr(command, "outcome_status")
    event_id = getattr(command, "outcome_event_id", None) or getattr(
        command, "reconcile_event_id"
    )
    return RuntimeExternalOperationAttemptFact(
        tenant_id=getattr(command, "tenant_id"),
        runtime_external_permit_id=getattr(command, "runtime_external_permit_id"),
        runtime_run_id=getattr(command, "runtime_run_id"),
        operation_kind=getattr(command, "operation_kind"),
        intent_id=getattr(command, "intent_id"),
        permit_attempt=1,
        task_execution_generation=getattr(command, "task_execution_generation"),
        admission_snapshot_id=getattr(command, "admission_snapshot_id"),
        admission_snapshot_hash=getattr(command, "admission_snapshot_hash"),
        request_hash=getattr(command, "request_hash"),
        lease_owner=getattr(command, "lease_owner"),
        lease_epoch=getattr(command, "lease_epoch"),
        arm_event_id=ARM_EVENT_ID,
        armed_by="dispatch-authorizer",
        armed_at=NOW,
        status=outcome_status,
        last_event_id=event_id,
        source_fact_id=getattr(command, "source_fact_id"),
        source_fact_version=getattr(command, "source_fact_version"),
        source_fact_hash=getattr(command, "source_fact_hash"),
        outcome_code=getattr(command, "outcome_code"),
        evidence_kind=ExternalOutcomeEvidenceKind.JAVA_CANONICAL_FACT,
        result_hash=getattr(command, "result_hash"),
        recorded_by=getattr(command, "recorded_by"),
        outcome_recorded_at=NOW,
        updated_at=NOW,
    )


def _valid_probe_row() -> dict[str, object]:
    return {
        "login_name": "outcome-login",
        "login_can_login": True,
        "login_inherits": True,
        "login_is_restricted": True,
        "has_exact_membership_count": True,
        "has_exact_outcome_reconciler_membership": True,
        "outcome_reconciler_role_is_sealed": True,
        "is_outcome_reconciler": True,
        "is_permit_authorizer": False,
        "is_dispatch_authorizer": False,
        "is_executor": False,
        "has_schema_usage": True,
        "has_schema_create": False,
        "record_wrapper_exists": True,
        "reconcile_wrapper_exists": True,
        "can_execute_record_wrapper": True,
        "can_execute_reconcile_wrapper": True,
        "has_no_other_function_execute": True,
        "has_no_relation_privileges": True,
        "has_no_column_privileges": True,
        "has_no_sequence_privileges": True,
    }


class ProbeConnection:
    def __init__(self, row: dict[str, object]):
        self.row = row
        self.statement = ""
        self.parameters: tuple[object, ...] = ()
        self.closed = False

    def execute(self, statement: str, parameters: tuple[object, ...]):
        self.statement = statement
        self.parameters = parameters
        return SimpleNamespace(fetchone=lambda: self.row)

    def close(self) -> None:
        self.closed = True


def _started_service(repository: object):
    connection = ProbeConnection(_valid_probe_row())
    service = PostgresExternalOperationOutcomeService(
        repository,  # type: ignore[arg-type]
        lambda: connection,  # type: ignore[arg-type,return-value]
    )
    service.start()
    assert service.ready is True
    return service, connection


def test_service_derives_fixed_evidence_and_accepts_idempotent_facts() -> None:
    class Repository:
        commands: list[object] = []

        def record_external_operation_outcome(self, command):
            self.commands.append(command)
            return PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, _fact(command))

        def reconcile_external_operation_outcome(self, command):
            self.commands.append(command)
            return PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, _fact(command))

    repository = Repository()
    service, _ = _started_service(repository)
    assert service.record(
        _record_model(), recorded_by="dianlian-platform"
    ) == ExternalOperationOutcomeApiResult.APPLIED
    assert service.reconcile(
        _reconcile_model(), recorded_by="dianlian-platform"
    ) == ExternalOperationOutcomeApiResult.APPLIED
    assert all(
        command.evidence_kind == ExternalOutcomeEvidenceKind.JAVA_CANONICAL_FACT
        for command in repository.commands
    )
    assert all(command.recorded_by == "dianlian-platform" for command in repository.commands)


def test_record_replay_after_reconcile_accepts_safe_newer_projection() -> None:
    class Repository:
        def record_external_operation_outcome(self, command):
            reconciled = replace(
                _fact(command),
                status=ExternalOperationAttemptStatus.SUCCEEDED,
                last_event_id=RECONCILE_EVENT_ID,
                source_fact_version=command.source_fact_version + 1,
                source_fact_hash="b" * 64,
                outcome_code="JAVA_SUCCEEDED_CONFIRMED",
                result_hash="c" * 64,
                recorded_by=command.recorded_by,
            )
            return PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, reconciled)

        def reconcile_external_operation_outcome(self, command):
            raise AssertionError

    repository = Repository()
    service, _ = _started_service(repository)
    assert service.record(
        _record_model(), recorded_by="dianlian-platform"
    ) == ExternalOperationOutcomeApiResult.APPLIED



@pytest.mark.parametrize(
    "mutate",
    [
        lambda fact, command: replace(fact, recorded_by="other-actor"),
        lambda fact, command: replace(
            fact,
            source_fact_id=UUID("00000000-0000-4000-8000-000000000099"),
        ),
        lambda fact, command: replace(
            fact,
            source_fact_version=command.source_fact_version,
        ),
        lambda fact, command: replace(fact, lease_epoch=command.lease_epoch + 1),
        lambda fact, command: replace(
            fact,
            status=ExternalOperationAttemptStatus.OUTCOME_UNKNOWN,
            last_event_id=RECONCILE_EVENT_ID,
            result_hash=None,
        ),
    ],
)
def test_record_replay_after_reconcile_rejects_unsafe_current_projection(
    mutate,
) -> None:
    class Repository:
        def record_external_operation_outcome(self, command):
            safe = replace(
                _fact(command),
                status=ExternalOperationAttemptStatus.SUCCEEDED,
                last_event_id=RECONCILE_EVENT_ID,
                source_fact_version=command.source_fact_version + 1,
                source_fact_hash="b" * 64,
                outcome_code="JAVA_SUCCEEDED_CONFIRMED",
                result_hash="c" * 64,
            )
            return PrimitiveResult(
                PrimitiveOutcome.FACT_RETURNED,
                mutate(safe, command),
            )

        def reconcile_external_operation_outcome(self, command):
            raise AssertionError

    service, _ = _started_service(Repository())
    with pytest.raises(ExternalOperationOutcomeUnavailable):
        service.record(_record_model(), recorded_by="dianlian-platform")
    assert service.ready is False


def test_not_applied_and_conflicts_do_not_demote_readiness() -> None:
    class Repository:
        conflict = False

        def record_external_operation_outcome(self, command):
            if self.conflict:
                raise SupervisorCommandConflict(
                    SupervisorErrorCode.COMMAND_CONFLICT,
                    SupervisorPrimitive.RECORD_EXTERNAL_OPERATION_OUTCOME,
                    "23505",
                    "must not escape",
                )
            return PrimitiveResult(PrimitiveOutcome.NOT_APPLIED, None)

        def reconcile_external_operation_outcome(self, command):
            raise AssertionError

    repository = Repository()
    service, _ = _started_service(repository)
    assert service.record(
        _record_model(), recorded_by="dianlian-platform"
    ) == ExternalOperationOutcomeApiResult.NOT_APPLIED
    repository.conflict = True
    with pytest.raises(ExternalOperationOutcomeConflict):
        service.record(_record_model(), recorded_by="dianlian-platform")
    assert service.ready is True


@pytest.mark.parametrize("method", ["record", "reconcile"])
def test_wrong_repository_fact_type_fails_closed(method: str) -> None:
    class Repository:
        def record_external_operation_outcome(self, command):
            return PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, object())

        def reconcile_external_operation_outcome(self, command):
            return PrimitiveResult(PrimitiveOutcome.FACT_RETURNED, object())

    service, _ = _started_service(Repository())
    with pytest.raises(ExternalOperationOutcomeUnavailable):
        if method == "record":
            service.record(_record_model(), recorded_by="dianlian-platform")
        else:
            service.reconcile(_reconcile_model(), recorded_by="dianlian-platform")
    assert service.ready is False


def test_unavailable_demotes_readiness_and_readiness_is_exact() -> None:
    class Repository:
        def record_external_operation_outcome(self, command):
            raise SupervisorUnavailable(
                SupervisorErrorCode.UNAVAILABLE,
                SupervisorPrimitive.RECORD_EXTERNAL_OPERATION_OUTCOME,
                "08006",
                "must not escape",
            )

        def reconcile_external_operation_outcome(self, command):
            raise AssertionError

    service, connection = _started_service(Repository())
    assert len(connection.parameters) == 6
    assert sum("record_runtime_external_operation_outcome" in str(p) for p in connection.parameters) == 3
    assert sum("reconcile_runtime_external_operation_outcome" in str(p) for p in connection.parameters) == 3
    assert "has_column_privilege" in connection.statement
    with pytest.raises(ExternalOperationOutcomeUnavailable):
        service.record(_record_model(), recorded_by="dianlian-platform")
    assert service.ready is False

    unsafe = _valid_probe_row()
    unsafe["is_dispatch_authorizer"] = True
    unsafe_service = PostgresExternalOperationOutcomeService(
        Repository(),
        lambda: ProbeConnection(unsafe),  # type: ignore[arg-type,return-value]
    )
    unsafe_service.start()
    assert unsafe_service.ready is False


def test_settings_and_factory_are_independent_and_dsn_is_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DIANLIAN_OUTCOME_RECONCILER_ENABLED", "true")
    monkeypatch.setenv(
        "DIANLIAN_OUTCOME_RECONCILER_DATABASE_DSN",
        "postgresql://outcome.invalid/runtime",
    )
    settings = RuntimeSettings.from_environment()
    assert settings.outcome_reconciler_enabled is True
    assert "outcome.invalid" not in repr(settings)

    connection = ProbeConnection(_valid_probe_row())
    captured: dict[str, object] = {}

    def connect(dsn: str, **kwargs: object):
        captured["dsn"] = dsn
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(
        "dianlian_runtime.supervisor.outcome_reconciler.psycopg.connect",
        connect,
    )
    service = create_postgres_external_operation_outcome_service(
        "postgresql://outcome.invalid/runtime",
        connect_timeout_seconds=4,
        statement_timeout_seconds=5,
        lock_timeout_seconds=3,
    )
    service.start()
    assert captured["connect_timeout"] == 4
    assert captured["options"] == "-c statement_timeout=5000 -c lock_timeout=3000"


def test_enabled_without_dsn_registers_routes_but_fails_readiness_closed() -> None:
    app = create_app(
        _settings(enabled=True),
        internal_service_authenticator=ExactAuthenticator(),
    )
    with TestClient(app) as client:
        response = client.post(
            RECORD_ROUTE,
            json=_record_payload(),
            headers={"Authorization": "Bearer valid"},
        )
        readiness = client.get("/internal/v1/health/readiness")
    assert response.status_code == 503
    assert readiness.status_code == 503


@pytest.mark.parametrize(
    "changes",
    [
        {
            "role": "agent-worker",
            "agent_enabled": True,
            "supervisor_enabled": True,
            "outcome_reconciler_enabled": True,
        },
        {
            "outcome_reconciler_database_statement_timeout_seconds": 2,
            "outcome_reconciler_database_lock_timeout_seconds": 3,
        },
    ],
)
def test_settings_reject_wrong_role_and_unbounded_timeout_relationship(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "service_name": "dianlian-ai-runtime",
        "service_version": "test",
        "role": "runtime-api",
        "context_enabled": False,
        "agent_enabled": False,
        "supervisor_enabled": False,
    }
    values.update(changes)
    with pytest.raises(ValueError):
        RuntimeSettings(**values)  # type: ignore[arg-type]

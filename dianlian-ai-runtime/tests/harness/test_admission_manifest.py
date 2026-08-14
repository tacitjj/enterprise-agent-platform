from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import gzip
import json
from typing import AsyncIterator, Callable
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

from dianlian_runtime.harness.admission_manifest import (
    AdmissionManifestFailedSafe,
    AdmissionManifestOutcomeUnknown,
    JavaAdmissionManifestClient,
    JavaAdmissionManifestResolveRequest,
)
from dianlian_runtime.harness.model_gateway import IssuedRuntimeModelJwt
from dianlian_runtime.supervisor.contracts import (
    ExternalOperation,
    ExternalPermitStatus,
    MultitaskStrategy,
    OperationKind,
    RuntimeExecutionAuthorityFact,
    RuntimeExternalPermitFact,
)
from dianlian_runtime.supervisor.driver import (
    DriverExecutionRequest,
    DriverFence,
    DriverFenceRevoked,
)


RUN_ID = UUID("22000000-0000-4000-8000-000000000001")
TASK_ID = UUID("22000000-0000-4000-8000-000000000003")
STEP_ID = UUID("22000000-0000-4000-8000-000000000004")
ADMISSION_ID = UUID("22000000-0000-4000-8000-000000000005")
TENANT_ID = UUID("22000000-0000-4000-8000-000000000006")
THREAD_ID = UUID("22000000-0000-4000-8000-000000000007")
PERMIT_ID = UUID("22000000-0000-4000-8000-000000000008")
INTENT_ID = UUID("22000000-0000-4000-8000-000000000009")
ISSUE_EVENT_ID = UUID("22000000-0000-4000-8000-00000000000a")
CONSUME_EVENT_ID = UUID("22000000-0000-4000-8000-00000000000b")
NOW = datetime(2026, 8, 13, tzinfo=UTC)
ADMISSION_HASH = "b" * 64
REQUEST_HASH = "a" * 64
PERMIT_REQUEST_HASH = "9" * 64
POLICY_HASH_100000 = "6cf57e7fa121d4edaeb1c379df87fb5ae08e693d40c1639d3fad8ae964c9b66c"
OVERSIZED_RESPONSE = b"x" * (256 * 1024 + 1)
NIL_UUID = "00000000-0000-0000-0000-000000000000"


class ChunkedResponseStream(httpx.AsyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class RecordingIssuer:
    def __init__(self, *, fail: bool = False) -> None:
        self.scopes: list[str] = []
        self._fail = fail

    def issue(self, *, scope: str, now: datetime | None = None) -> IssuedRuntimeModelJwt:
        del now
        if self._fail:
            raise RuntimeError("sensitive signing details")
        self.scopes.append(scope)
        return IssuedRuntimeModelJwt(
            f"token-{len(self.scopes)}",
            NOW,
            NOW + timedelta(seconds=30),
        )


class RecordingGate:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def revoked(self) -> bool:
        return False

    async def authorize_execution(self) -> None:
        self.calls += 1


class RevokingGate(RecordingGate):
    async def authorize_execution(self) -> None:
        await super().authorize_execution()
        if self.calls == 2:
            raise DriverFenceRevoked("takeover won during manifest fetch")


def execution_request(*, lease_owner: str = "worker-a", lease_epoch: int = 1) -> DriverExecutionRequest:
    authority = RuntimeExecutionAuthorityFact(
        tenant_id=TENANT_ID,
        runtime_run_id=RUN_ID,
        runtime_thread_id=THREAD_ID,
        task_run_id=TASK_ID,
        task_step_id=STEP_ID,
        task_execution_generation=1,
        agent_instance_id=UUID("22000000-0000-4000-8000-000000000010"),
        user_id=UUID("22000000-0000-4000-8000-000000000011"),
        conversation_id=UUID("22000000-0000-4000-8000-000000000012"),
        source_message_id=None,
        runtime_thread_revision=1,
        runtime_type="DEERFLOW",
        runtime_agent_name="runtime-agent",
        capability_version_id=UUID("22000000-0000-4000-8000-000000000013"),
        prompt_version_id=UUID("22000000-0000-4000-8000-000000000014"),
        model_policy_id=UUID("22000000-0000-4000-8000-000000000015"),
        budget_reservation_id=UUID("22000000-0000-4000-8000-000000000016"),
        operation_kind=OperationKind.START,
        multitask_strategy=MultitaskStrategy.REJECT,
        request_hash=REQUEST_HASH,
        idempotency_key="h12-create",
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
    return DriverExecutionRequest(
        authority=authority,
        fence=DriverFence(
            tenant_id=authority.tenant_id,
            runtime_run_id=authority.runtime_run_id,
            task_execution_generation=authority.task_execution_generation,
            lease_owner=authority.lease_owner,
            lease_epoch=authority.lease_epoch,
            admission_contract_version=authority.admission_contract_version,
            admission_snapshot_id=authority.admission_snapshot_id,
            admission_snapshot_hash=authority.admission_snapshot_hash,
        ),
    )


def issued_permit() -> RuntimeExternalPermitFact:
    return RuntimeExternalPermitFact(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=PERMIT_ID,
        runtime_run_id=RUN_ID,
        runtime_thread_id=THREAD_ID,
        task_step_id=STEP_ID,
        task_execution_generation=1,
        admission_contract_version="2.2",
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=ADMISSION_HASH,
        operation_kind=ExternalOperation.ADMISSION_RESOLVE,
        intent_id=INTENT_ID,
        request_hash=PERMIT_REQUEST_HASH,
        lease_owner="worker-a",
        lease_epoch=1,
        permit_attempt=1,
        status=ExternalPermitStatus.ISSUED,
        requested_ttl_seconds=30,
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
        issue_event_id=ISSUE_EVENT_ID,
        consume_event_id=None,
        consumed_by=None,
        consumed_at=None,
        updated_at=NOW,
    )


def historical_consumed_permit() -> RuntimeExternalPermitFact:
    return replace(
        issued_permit(),
        status=ExternalPermitStatus.CONSUMED,
        consume_event_id=CONSUME_EVENT_ID,
        consumed_by="dianlian-ai-runtime",
        consumed_at=NOW + timedelta(seconds=1),
        updated_at=NOW + timedelta(seconds=1),
    )


def manifest_payload() -> dict[str, object]:
    return {
        "runtimeRunId": str(RUN_ID),
        "tenantId": str(TENANT_ID),
        "taskId": str(TASK_ID),
        "taskStepId": str(STEP_ID),
        "executionGeneration": 1,
        "admissionContractVersion": "2.2",
        "runtimeProfile": "DEERFLOW_H1_TEXT",
        "admissionSnapshotId": str(ADMISSION_ID),
        "admissionSnapshotHash": ADMISSION_HASH,
        "requestHash": REQUEST_HASH,
        "idempotencyKey": "h12-create",
        "actorUserId": "22000000-0000-4000-8000-000000000011",
        "inputSnapshotId": "22000000-0000-4000-8000-000000000017",
        "enterpriseAgentId": "22000000-0000-4000-8000-000000000010",
        "agentVersionId": "22000000-0000-4000-8000-000000000019",
        "configurationVersionId": "22000000-0000-4000-8000-00000000001a",
        "pointReservationId": "22000000-0000-4000-8000-000000000016",
        "modelRoute": {
            "routeBindingId": "22000000-0000-4000-8000-00000000001c",
            "routeStateVersion": 1,
            "modelDefinitionId": "22000000-0000-4000-8000-00000000001d",
            "modelConfigurationVersion": 1,
            "reservationCeilingMicroCredit": 100000,
        },
        "prompt": {
            "promptSnapshotId": "22000000-0000-4000-8000-00000000001e",
            "hash": "2" * 64,
        },
        "context": {
            "contextSnapshotId": "22000000-0000-4000-8000-00000000001f",
            "hash": "3" * 64,
        },
        "toolPolicy": {
            "toolPolicySnapshotId": "22000000-0000-4000-8000-000000000011",
            "hash": "34e2623c8fa2c67dd3c346a6086e741c6a685d258a3c289fa5b43b250013f3b8",
        },
        "orchestrationPolicy": {
            "orchestrationPolicySnapshotId": "22000000-0000-4000-8000-000000000022",
            "maxModelCalls": 2,
            "maxToolCalls": 1,
            "modelCallReservationCeiling": 100000,
            "totalModelReservationCeiling": 200000,
            "hash": POLICY_HASH_100000,
        },
    }


async def call_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    execution: DriverExecutionRequest | None = None,
    permit: RuntimeExternalPermitFact | None = None,
    issuer: RecordingIssuer | None = None,
    gate: RecordingGate | None = None,
) -> tuple[object, RecordingIssuer, RecordingGate]:
    active_issuer = issuer or RecordingIssuer()
    active_gate = gate or RecordingGate()
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = JavaAdmissionManifestClient(
        base_url="https://platform.internal",
        jwt_issuer=active_issuer,
        timeout_seconds=10,
        client=http_client,
    )
    try:
        result = await client.resolve(
            execution or execution_request(),
            permit or issued_permit(),
            gate=active_gate,
        )
    finally:
        await http_client.aclose()
    return result, active_issuer, active_gate


@pytest.mark.parametrize(
    "field_name",
    [
        "tenant_id",
        "task_step_id",
        "admission_snapshot_id",
        "runtime_external_permit_id",
        "permit_intent_id",
    ],
)
def test_resolve_request_rejects_nil_uuid(field_name: str) -> None:
    values: dict[str, object] = {
        "tenant_id": TENANT_ID,
        "task_step_id": STEP_ID,
        "execution_generation": 1,
        "admission_snapshot_id": ADMISSION_ID,
        "admission_snapshot_hash": ADMISSION_HASH,
        "runtime_external_permit_id": PERMIT_ID,
        "permit_intent_id": INTENT_ID,
        "permit_request_hash": PERMIT_REQUEST_HASH,
        "lease_owner": "worker-a",
        "lease_epoch": 1,
    }
    values[field_name] = UUID(int=0)

    with pytest.raises(ValidationError, match="nil UUID"):
        JavaAdmissionManifestResolveRequest(**values)


@pytest.mark.parametrize(
    "path",
    [
        ("runtimeRunId",),
        ("tenantId",),
        ("taskId",),
        ("taskStepId",),
        ("admissionSnapshotId",),
        ("actorUserId",),
        ("inputSnapshotId",),
        ("enterpriseAgentId",),
        ("agentVersionId",),
        ("configurationVersionId",),
        ("pointReservationId",),
        ("modelRoute", "routeBindingId"),
        ("modelRoute", "modelDefinitionId"),
        ("prompt", "promptSnapshotId"),
        ("context", "contextSnapshotId"),
        ("toolPolicy", "toolPolicySnapshotId"),
        ("orchestrationPolicy", "orchestrationPolicySnapshotId"),
    ],
)
def test_manifest_rejects_nil_uuid_before_binding(
    path: tuple[str, ...],
) -> None:
    async def verify() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            del request
            calls += 1
            payload = manifest_payload()
            target = payload
            for segment in path[:-1]:
                nested = target[segment]
                assert isinstance(nested, dict)
                target = nested
            target[path[-1]] = NIL_UUID
            return httpx.Response(200, json=payload)

        with pytest.raises(AdmissionManifestOutcomeUnknown) as raised:
            await call_client(handler)
        assert raised.value.code == "ADMISSION_MANIFEST_RESPONSE_INVALID"
        assert calls == 1

    asyncio.run(verify())


def test_manifest_resolve_uses_exact_scope_permit_and_fenced_identity() -> None:
    async def verify() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json=manifest_payload())

        manifest, issuer, gate = await call_client(handler)
        assert manifest.runtime_run_id == RUN_ID
        assert manifest.runtime_profile == "DEERFLOW_H1_TEXT"
        assert manifest.prompt.model_dump(mode="json", by_alias=True) == {
            "promptSnapshotId": "22000000-0000-4000-8000-00000000001e",
            "hash": "2" * 64,
        }
        assert manifest.context.model_dump(mode="json", by_alias=True) == {
            "contextSnapshotId": "22000000-0000-4000-8000-00000000001f",
            "hash": "3" * 64,
        }
        assert set(manifest.tool_policy.model_dump(by_alias=True)) == {
            "toolPolicySnapshotId",
            "hash",
        }
        assert set(manifest.orchestration_policy.model_dump(by_alias=True)) == {
            "orchestrationPolicySnapshotId",
            "maxModelCalls",
            "maxToolCalls",
            "modelCallReservationCeiling",
            "totalModelReservationCeiling",
            "hash",
        }
        assert set(manifest.model_route.model_dump(by_alias=True)) == {
            "routeBindingId",
            "routeStateVersion",
            "modelDefinitionId",
            "modelConfigurationVersion",
            "reservationCeilingMicroCredit",
        }
        assert issuer.scopes == ["admission.resolve"]
        assert gate.calls == 2
        assert len(requests) == 1
        request = requests[0]
        assert request.url.path == (
            f"/internal/v1/agent-runtime/runs/{RUN_ID}/admission-manifest"
        )
        assert request.headers["Authorization"] == "Bearer token-1"
        body = json.loads(request.content)
        assert body == {
            "tenantId": str(TENANT_ID),
            "taskStepId": str(STEP_ID),
            "executionGeneration": 1,
            "admissionContractVersion": "2.2",
            "admissionSnapshotId": str(ADMISSION_ID),
            "admissionSnapshotHash": ADMISSION_HASH,
            "runtimeExternalPermitId": str(PERMIT_ID),
            "permitIntentId": str(INTENT_ID),
            "permitRequestHash": PERMIT_REQUEST_HASH,
            "leaseOwner": "worker-a",
            "leaseEpoch": 1,
        }
        assert set(body).isdisjoint({"executionId", "consumeEventId", "consumedBy"})

    asyncio.run(verify())


def test_consumed_permit_replay_still_requires_current_gate_each_request() -> None:
    async def verify() -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(
                    401,
                    json={"code": "INTERNAL_SERVICE_AUTHENTICATION_REQUIRED"},
                )
            return httpx.Response(200, json=manifest_payload())

        manifest, issuer, gate = await call_client(
            handler,
            permit=historical_consumed_permit(),
        )
        assert manifest.runtime_run_id == RUN_ID
        assert issuer.scopes == ["admission.resolve", "admission.resolve"]
        assert gate.calls == 3
        assert len(requests) == 2
        assert requests[0].content == requests[1].content
        assert requests[0].url == requests[1].url
        assert requests[0].headers["Authorization"] != requests[1].headers["Authorization"]
        replay_body = json.loads(requests[1].content)
        assert replay_body["leaseOwner"] == "worker-a"
        assert replay_body["leaseEpoch"] == 1

    asyncio.run(verify())


def test_takeover_during_manifest_fetch_revokes_result_after_java_read() -> None:
    async def verify() -> None:
        calls = 0
        gate = RevokingGate()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            del request
            calls += 1
            return httpx.Response(200, json=manifest_payload())

        with pytest.raises(DriverFenceRevoked):
            await call_client(handler, gate=gate)
        assert calls == 1
        assert gate.calls == 2

    asyncio.run(verify())


@pytest.mark.parametrize(
    "permit",
    [
        replace(issued_permit(), operation_kind=ExternalOperation.MODEL_INVOKE),
        replace(issued_permit(), tenant_id=UUID("22000000-0000-4000-8000-000000000099")),
        replace(issued_permit(), lease_owner="stale-worker"),
        historical_consumed_permit(),
    ],
)
def test_invalid_permit_binding_fails_before_gate_or_http(
    permit: RuntimeExternalPermitFact,
) -> None:
    async def verify() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            del request
            calls += 1
            return httpx.Response(200, json=manifest_payload())

        with pytest.raises(AdmissionManifestFailedSafe) as raised:
            execution = (
                execution_request(lease_owner="worker-b", lease_epoch=2)
                if permit.status == ExternalPermitStatus.CONSUMED
                else execution_request()
            )
            await call_client(handler, execution=execution, permit=permit)
        assert raised.value.code == "ADMISSION_MANIFEST_BINDING_INVALID"
        assert calls == 0

    asyncio.run(verify())


@pytest.mark.parametrize(
    "scenario",
    [
        "bad_json",
        "duplicate",
        "extra",
        "secret",
        "wrong_run",
        "wrong_hash",
        "wrong_actor",
        "wrong_agent",
        "wrong_budget",
        "coerced_nested_integer",
        "wrong_runtime_profile",
        "missing_runtime_profile",
        "legacy_prompt_payload",
        "legacy_context_payload",
        "legacy_tool_policy_payload",
        "legacy_orchestration_schema",
        "wrong_component_hash_format",
        "wrong_orchestration_limits",
        "wrong_orchestration_total",
        "wrong_orchestration_hash",
        "wrong_route_ceiling",
    ],
)
def test_invalid_200_manifest_fails_closed_without_retry(scenario: str) -> None:
    async def verify() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            del request
            calls += 1
            if scenario == "bad_json":
                return httpx.Response(
                    200,
                    headers={"Content-Type": "application/json"},
                    content=b"{",
                )
            if scenario == "duplicate":
                return httpx.Response(
                    200,
                    headers={"Content-Type": "application/json"},
                    content=(
                        b'{"runtimeRunId":"'
                        + str(RUN_ID).encode()
                        + b'","runtimeRunId":"'
                        + str(RUN_ID).encode()
                        + b'"}'
                    ),
                )
            payload = manifest_payload()
            if scenario == "extra":
                payload["unexpected"] = True
            elif scenario == "secret":
                payload["context"] = {
                    **payload["context"],  # type: ignore[arg-type]
                    "secret": "must-not-enter-runtime",
                }
            elif scenario == "wrong_run":
                payload["runtimeRunId"] = "22000000-0000-4000-8000-000000000099"
            elif scenario == "wrong_hash":
                payload["admissionSnapshotHash"] = "c" * 64
            elif scenario == "wrong_actor":
                payload["actorUserId"] = "22000000-0000-4000-8000-000000000099"
            elif scenario == "wrong_agent":
                payload["enterpriseAgentId"] = "22000000-0000-4000-8000-000000000099"
            elif scenario == "wrong_budget":
                payload["pointReservationId"] = "22000000-0000-4000-8000-000000000099"
            elif scenario == "coerced_nested_integer":
                payload["modelRoute"] = {
                    **payload["modelRoute"],  # type: ignore[arg-type]
                    "routeStateVersion": "1",
                }
            elif scenario == "wrong_runtime_profile":
                payload["runtimeProfile"] = "H0_DUMMY"
            elif scenario == "missing_runtime_profile":
                payload.pop("runtimeProfile")
            elif scenario == "legacy_prompt_payload":
                prompt = payload["prompt"]
                assert isinstance(prompt, dict)
                prompt["systemInstruction"] = "must-not-cross-receipt-boundary"
            elif scenario == "legacy_context_payload":
                context = payload["context"]
                assert isinstance(context, dict)
                context["mode"] = "EMPTY"
            elif scenario == "legacy_tool_policy_payload":
                tool_policy = payload["toolPolicy"]
                assert isinstance(tool_policy, dict)
                tool_policy["allowedTools"] = []
            elif scenario == "legacy_orchestration_schema":
                orchestration = payload["orchestrationPolicy"]
                assert isinstance(orchestration, dict)
                orchestration["schemaVersion"] = "runtime-orchestration-policy-v1"
            elif scenario == "wrong_component_hash_format":
                context = payload["context"]
                assert isinstance(context, dict)
                context["hash"] = "ABC"
            elif scenario == "wrong_orchestration_limits":
                orchestration = payload["orchestrationPolicy"]
                assert isinstance(orchestration, dict)
                orchestration["maxToolCalls"] = 2
            elif scenario == "wrong_orchestration_total":
                orchestration = payload["orchestrationPolicy"]
                assert isinstance(orchestration, dict)
                orchestration["totalModelReservationCeiling"] = 200001
            elif scenario == "wrong_orchestration_hash":
                orchestration = payload["orchestrationPolicy"]
                assert isinstance(orchestration, dict)
                orchestration["hash"] = "0" * 64
            elif scenario == "wrong_route_ceiling":
                model_route = payload["modelRoute"]
                assert isinstance(model_route, dict)
                model_route["reservationCeilingMicroCredit"] = 99999
            return httpx.Response(200, json=payload)

        with pytest.raises(AdmissionManifestOutcomeUnknown) as raised:
            await call_client(handler)
        assert raised.value.code in {
            "ADMISSION_MANIFEST_RESPONSE_INVALID",
            "ADMISSION_MANIFEST_BINDING_INVALID",
        }
        assert calls == 1

    asyncio.run(verify())


@pytest.mark.parametrize(
    "scenario",
    [
        "chunked_without_length",
        "false_small_content_length",
        "gzip_decoded_body",
    ],
)
def test_oversized_response_is_bounded_after_decoding_without_retry(
    scenario: str,
) -> None:
    async def verify() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            del request
            calls += 1
            headers = {"Content-Type": "application/json"}
            body = OVERSIZED_RESPONSE
            if scenario == "false_small_content_length":
                headers["Content-Length"] = "2"
            elif scenario == "gzip_decoded_body":
                headers["Content-Encoding"] = "gzip"
                body = gzip.compress(body)
            return httpx.Response(
                200,
                headers=headers,
                stream=ChunkedResponseStream(body[:7], body[7:]),
            )

        with pytest.raises(AdmissionManifestOutcomeUnknown) as raised:
            await call_client(handler)
        assert raised.value.code == "ADMISSION_MANIFEST_RESPONSE_TOO_LARGE"
        assert calls == 1

    asyncio.run(verify())


def test_oversized_401_still_enters_only_the_single_exact_replay() -> None:
    async def verify() -> None:
        calls = 0
        issuer = RecordingIssuer()
        gate = RecordingGate()

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            del request
            calls += 1
            return httpx.Response(
                401,
                headers={"Content-Type": "application/json"},
                stream=ChunkedResponseStream(OVERSIZED_RESPONSE),
            )

        with pytest.raises(AdmissionManifestFailedSafe) as raised:
            await call_client(handler, issuer=issuer, gate=gate)
        assert raised.value.code == "ADMISSION_MANIFEST_REJECTED"
        assert calls == 2
        assert issuer.scopes == ["admission.resolve", "admission.resolve"]
        assert gate.calls == 2

    asyncio.run(verify())


@pytest.mark.parametrize("status", [403, 409])
def test_oversized_explicit_4xx_is_failed_safe_without_retry(status: int) -> None:
    async def verify() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            del request
            calls += 1
            return httpx.Response(
                status,
                headers={"Content-Type": "application/json"},
                stream=ChunkedResponseStream(OVERSIZED_RESPONSE),
            )

        with pytest.raises(AdmissionManifestFailedSafe) as raised:
            await call_client(handler)
        assert raised.value.code == "ADMISSION_MANIFEST_REJECTED"
        assert calls == 1

    asyncio.run(verify())


@pytest.mark.parametrize("content_type", [None, "text/html"])
def test_200_requires_json_media_type(content_type: str | None) -> None:
    async def verify() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            del request
            calls += 1
            headers = {} if content_type is None else {"Content-Type": content_type}
            return httpx.Response(
                200,
                headers=headers,
                content=json.dumps(manifest_payload()).encode(),
            )

        with pytest.raises(AdmissionManifestOutcomeUnknown) as raised:
            await call_client(handler)
        assert raised.value.code == "ADMISSION_MANIFEST_RESPONSE_INVALID"
        assert calls == 1

    asyncio.run(verify())


def test_200_allows_json_media_type_with_charset() -> None:
    async def verify() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(
                200,
                headers={"Content-Type": "application/json; charset=utf-8"},
                content=json.dumps(manifest_payload()).encode(),
            )

        manifest, _, gate = await call_client(handler)
        assert manifest.runtime_run_id == RUN_ID
        assert gate.calls == 2

    asyncio.run(verify())


@pytest.mark.parametrize(
    ("status", "code", "failure_type", "attempts"),
    [
        (401, "INTERNAL_SERVICE_AUTHENTICATION_REQUIRED", AdmissionManifestFailedSafe, 2),
        (403, "INTERNAL_SERVICE_SCOPE_DENIED", AdmissionManifestFailedSafe, 1),
        (404, "ADMISSION_MANIFEST_NOT_FOUND", AdmissionManifestFailedSafe, 1),
        (409, "ADMISSION_MANIFEST_CONFLICT", AdmissionManifestFailedSafe, 1),
        (302, "ADMISSION_MANIFEST_REDIRECTED", AdmissionManifestOutcomeUnknown, 1),
        (503, "ADMISSION_MANIFEST_AUTHORIZATION_UNAVAILABLE", AdmissionManifestOutcomeUnknown, 1),
    ],
)
def test_http_failures_retry_only_one_exact_401(
    status: int,
    code: str,
    failure_type: type[Exception],
    attempts: int,
) -> None:
    async def verify() -> None:
        bodies: list[bytes] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(request.content)
            return httpx.Response(status, json={"code": code})

        with pytest.raises(failure_type) as raised:
            await call_client(handler)
        assert getattr(raised.value, "code") == (
            "ADMISSION_MANIFEST_OUTCOME_UNKNOWN"
            if status in {302, 503}
            else code
        )
        assert len(bodies) == attempts
        assert len(set(bodies)) == 1

    asyncio.run(verify())


def test_transport_and_token_failures_do_not_expose_details_or_blind_retry() -> None:
    async def verify_transport() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("sensitive transport details", request=request)

        with pytest.raises(AdmissionManifestOutcomeUnknown) as raised:
            await call_client(handler)
        assert raised.value.code == "ADMISSION_MANIFEST_OUTCOME_UNKNOWN"
        assert "sensitive" not in str(raised.value)
        assert calls == 1

    async def verify_token() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            del request
            calls += 1
            return httpx.Response(200, json=manifest_payload())

        with pytest.raises(AdmissionManifestFailedSafe) as raised:
            await call_client(handler, issuer=RecordingIssuer(fail=True))
        assert raised.value.code == "ADMISSION_MANIFEST_SERVICE_TOKEN_UNAVAILABLE"
        assert "sensitive" not in str(raised.value)
        assert calls == 0

    asyncio.run(verify_transport())
    asyncio.run(verify_token())

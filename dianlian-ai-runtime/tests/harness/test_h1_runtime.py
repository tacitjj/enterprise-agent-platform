from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import httpx
import jwt
import pytest

from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.harness.h1_contracts import CreateH1ExecutionRequest
from dianlian_runtime.harness.h1_runtime import DeerFlowH1Runtime, H1IdempotencyConflict
from dianlian_runtime.harness.model_gateway import (
    JavaModelGatewayChatModel,
    RuntimeModelServiceJwtIssuer,
    build_model_call_request,
)


UPSTREAM_ROOT = Path("/private/tmp/dianlian-deer-flow-upstream")


def _payload() -> dict[str, object]:
    return {
        "contractVersion": "2.0",
        "runtimeProfile": "DEERFLOW_H1_TEXT",
        "executionId": "20000000-0000-4000-8000-000000000001",
        "taskId": "20000000-0000-4000-8000-000000000002",
        "taskStepId": "20000000-0000-4000-8000-000000000003",
        "executionGeneration": 1,
        "admissionSnapshotId": "20000000-0000-4000-8000-000000000004",
        "idempotencyKey": "h1-create-001",
        "requestHash": "1" * 64,
        "tenantId": "20000000-0000-4000-8000-000000000005",
        "actorUserId": "20000000-0000-4000-8000-000000000006",
        "inputSnapshotId": "20000000-0000-4000-8000-000000000007",
        "enterpriseAgentId": "20000000-0000-4000-8000-000000000008",
        "agentVersionId": "20000000-0000-4000-8000-000000000009",
        "configurationVersionId": "20000000-0000-4000-8000-000000000010",
        "pointReservationId": "20000000-0000-4000-8000-000000000011",
        "modelRoute": {
            "routeBindingId": "20000000-0000-4000-8000-000000000012",
            "routeStateVersion": 3,
            "modelDefinitionId": "20000000-0000-4000-8000-000000000013",
            "modelConfigurationVersion": 4,
            "reservationCeilingMicroCredit": 500,
        },
        "prompt": {
            "promptSnapshotId": "20000000-0000-4000-8000-000000000014",
            "systemInstruction": "只输出纯文本报价摘要",
            "messages": [{"role": "HUMAN", "text": "生成一份报价摘要"}],
            "hash": "2" * 64,
        },
        "context": {
            "contextSnapshotId": "20000000-0000-4000-8000-000000000015",
            "mode": "EMPTY",
            "hash": "3" * 64,
        },
        "toolPolicy": {
            "toolPolicySnapshotId": "20000000-0000-4000-8000-000000000016",
            "allowedTools": [],
            "hash": "4" * 64,
        },
        "snapshotHash": "5" * 64,
    }


def _issuer(tmp_path: Path) -> tuple[RuntimeModelServiceJwtIssuer, object]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path = tmp_path / "runtime-model-private.pem"
    path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return (
        RuntimeModelServiceJwtIssuer(
            key_id="runtime-model-kid",
            private_key_path=path,
            ttl_seconds=30,
        ),
        private_key.public_key(),
    )


def _v21_payload() -> dict[str, object]:
    payload = _payload()
    payload["contractVersion"] = "2.1"
    payload["toolPolicy"] = {
        "toolPolicySnapshotId": "20000000-0000-4000-8000-000000000016",
        "schemaVersion": "runtime-tool-policy-v1",
        "mode": "ALLOW_LIST",
        "configurationPolicyId": "20000000-0000-4000-8000-000000000017",
        "configurationPolicyHash": "6" * 64,
        "allowedTools": [
            {
                "ordinal": 1,
                "toolDefinitionId": "20000000-0000-4000-8000-000000000018",
                "toolKey": "CALENDAR.READ",
                "definitionVersion": 1,
                "sideEffectMode": "NO_SIDE_EFFECT",
            }
        ],
        "hash": "d0d5114635fdd8cd424a8a28e4a5fe49d8c128aa65912712d8a6c7499b0c633f",
    }
    return payload


def test_h1_contract_accepts_a_java_fenced_context_without_context_payload() -> None:
    payload = _payload()
    payload["context"] = {
        "contextSnapshotId": "20000000-0000-4000-8000-000000000015",
        "mode": "FENCED",
        "hash": "3" * 64,
    }

    admission = CreateH1ExecutionRequest.model_validate(payload)

    assert admission.context.mode == "FENCED"
    assert "evidence" not in admission.context.model_dump()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda policy: policy.update({"unexpected": True}),
            "Extra inputs are not permitted",
        ),
        (
            lambda policy: policy["allowedTools"][0].update({"ordinal": 2}),
            "ordinals must be ordered",
        ),
        (
            lambda policy: policy["allowedTools"][0].update(
                {"sideEffectMode": "WRITES_EXTERNAL_STATE"}
            ),
            "Input should be 'NO_SIDE_EFFECT'",
        ),
        (
            lambda policy: policy.update({"mode": "DENY_ALL"}),
            "DENY_ALL tool policy must not allow tools",
        ),
        (
            lambda policy: policy["allowedTools"].clear(),
            "ALLOW_LIST tool policy must allow at least one tool",
        ),
        (
            lambda policy: policy["allowedTools"].append(
                {
                    **policy["allowedTools"][0],
                    "ordinal": 2,
                    "toolDefinitionId": "20000000-0000-4000-8000-000000000019",
                }
            ),
            "unique keys and definitions",
        ),
        (
            lambda policy: policy["allowedTools"].append(
                {
                    **policy["allowedTools"][0],
                    "ordinal": 2,
                    "toolKey": "DOCUMENT.READ",
                }
            ),
            "unique keys and definitions",
        ),
    ],
)
def test_h1_v21_tool_policy_is_strict(mutate, message: str) -> None:
    payload = _v21_payload()
    mutate(payload["toolPolicy"])

    with pytest.raises(ValueError, match=message):
        CreateH1ExecutionRequest.model_validate(payload)


def test_h1_v21_tool_policy_hash_matches_the_v28_fixed_vector() -> None:
    admission = CreateH1ExecutionRequest.model_validate(_v21_payload())

    assert admission.tool_policy.hash == (
        "d0d5114635fdd8cd424a8a28e4a5fe49d8c128aa65912712d8a6c7499b0c633f"
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda policy: policy.update({"hash": "0" * 64}),
        lambda policy: policy["allowedTools"][0].update(
            {"toolKey": "CALENDAR.SEARCH"}
        ),
    ],
)
def test_h1_v21_rejects_a_tampered_policy_hash(mutate) -> None:
    payload = _v21_payload()
    mutate(payload["toolPolicy"])

    with pytest.raises(ValueError, match="hash does not match the frozen payload"):
        CreateH1ExecutionRequest.model_validate(payload)


def test_h1_v20_rejects_the_v21_tool_policy_contract() -> None:
    payload = _v21_payload()
    payload["contractVersion"] = "2.0"

    with pytest.raises(ValueError, match="2.0 requires the deny-all"):
        CreateH1ExecutionRequest.model_validate(payload)


def test_h1_v21_rejects_the_legacy_tool_policy_contract() -> None:
    payload = _payload()
    payload["contractVersion"] = "2.1"

    with pytest.raises(ValueError, match="2.1 requires the frozen"):
        CreateH1ExecutionRequest.model_validate(payload)


def test_h1_v21_accepts_an_explicit_deny_all_policy() -> None:
    payload = _v21_payload()
    payload["toolPolicy"]["mode"] = "DENY_ALL"
    payload["toolPolicy"]["allowedTools"] = []
    payload["toolPolicy"]["hash"] = (
        "060218893171b84ce61b56e3fd12608140de377bf51517399a37bb874c0ecb6d"
    )

    admission = CreateH1ExecutionRequest.model_validate(payload)

    assert admission.tool_policy.mode == "DENY_ALL"
    assert admission.tool_policy.allowed_tools == []


@pytest.mark.skipif(not UPSTREAM_ROOT.is_dir(), reason="pinned DeerFlow checkout missing")
def test_h1_uses_pinned_harness_and_calls_java_once_with_service_identity(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        admission = CreateH1ExecutionRequest.model_validate(_v21_payload())
        expected_call = build_model_call_request(admission)
        issuer, public_key = _issuer(tmp_path)
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            token = request.headers["Authorization"].removeprefix("Bearer ")
            header = jwt.get_unverified_header(token)
            claims = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience="dianlian-platform",
                issuer="dianlian-ai-runtime",
            )
            assert header == {"alg": "RS256", "kid": "runtime-model-kid", "typ": "JWT"}
            assert claims["sub"] == "dianlian-ai-runtime"
            assert claims["scope"] == "model.invoke"
            body = request.read().decode()
            assert "credentialRef" not in body
            assert "baseUrl" not in body
            assert "allowedTools" not in body
            assert "CALENDAR.READ" not in body
            assert request.url.path == (
                "/internal/v1/agent-runtime/executions/"
                f"{admission.execution_id}/model-calls"
            )
            return httpx.Response(
                200,
                json={
                    "contractVersion": "1.0",
                    "modelCallId": str(expected_call.model_call_id),
                    "status": "RESPONSE_RECEIVED",
                    "assistantText": "报价摘要完成",
                    "providerRequestId": "provider-request-1",
                    "finishReason": "stop",
                    "inputTokens": 9,
                    "outputTokens": 4,
                    "usageConfirmed": True,
                    "capturedAmount": 13,
                    "failureCode": None,
                    "replayed": False,
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        model = JavaModelGatewayChatModel(
            base_url="https://platform.internal",
            jwt_issuer=issuer,
            timeout_seconds=10,
            client=client,
        )
        async with DeerFlowH1Runtime(
            data_dir=tmp_path / "runtime-data",
            upstream_root=UPSTREAM_ROOT,
            model=model,
        ) as runtime:
            completed = await runtime.start_execution(admission)
            replayed = await runtime.start_execution(admission)
            events = await runtime.stream_events(admission.execution_id)

        await client.aclose()
        assert completed.state == "SUCCEEDED"
        assert completed.contract_version == "2.1"
        assert completed.output == "报价摘要完成"
        assert replayed.contract_version == "2.1"
        assert replayed.output == "报价摘要完成"
        assert len(calls) == 1
        assert [event.event_type for event in events] == [
            "dianlian.h1.started",
            "dianlian.h1.model.completed",
        ]

    asyncio.run(verify())


@pytest.mark.skipif(not UPSTREAM_ROOT.is_dir(), reason="pinned DeerFlow checkout missing")
def test_h1_outcome_unknown_is_terminal_and_never_retried(tmp_path: Path) -> None:
    async def verify() -> None:
        admission = CreateH1ExecutionRequest.model_validate(_payload())
        issuer, _ = _issuer(tmp_path)
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            del request
            call_count += 1
            raise httpx.ReadTimeout("outcome unknown")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        model = JavaModelGatewayChatModel(
            base_url="https://platform.internal",
            jwt_issuer=issuer,
            timeout_seconds=10,
            client=client,
        )
        data_dir = tmp_path / "runtime-data"
        async with DeerFlowH1Runtime(
            data_dir=data_dir,
            upstream_root=UPSTREAM_ROOT,
            model=model,
        ) as runtime:
            failed = await runtime.start_execution(admission)
            replayed = await runtime.start_execution(admission)
        await client.aclose()

        assert failed.state == "FAILED"
        assert failed.failure_code == "MODEL_GATEWAY_OUTCOME_UNKNOWN"
        assert replayed.failure_code == "MODEL_GATEWAY_OUTCOME_UNKNOWN"
        assert call_count == 1

    asyncio.run(verify())


@pytest.mark.skipif(not UPSTREAM_ROOT.is_dir(), reason="pinned DeerFlow checkout missing")
def test_h1_java_unknown_response_preserves_code_and_never_retries(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        admission = CreateH1ExecutionRequest.model_validate(_payload())
        expected_call = build_model_call_request(admission)
        issuer, _ = _issuer(tmp_path)
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            del request
            call_count += 1
            return httpx.Response(
                200,
                json={
                    "contractVersion": "1.0",
                    "modelCallId": str(expected_call.model_call_id),
                    "status": "OUTCOME_UNKNOWN",
                    "assistantText": None,
                    "providerRequestId": None,
                    "finishReason": None,
                    "inputTokens": 0,
                    "outputTokens": 0,
                    "usageConfirmed": False,
                    "capturedAmount": 0,
                    "failureCode": "MODEL_PROVIDER_OUTCOME_UNKNOWN",
                    "replayed": False,
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        model = JavaModelGatewayChatModel(
            base_url="https://platform.internal",
            jwt_issuer=issuer,
            timeout_seconds=10,
            client=client,
        )
        async with DeerFlowH1Runtime(
            data_dir=tmp_path / "runtime-data",
            upstream_root=UPSTREAM_ROOT,
            model=model,
        ) as runtime:
            failed = await runtime.start_execution(admission)
            replayed = await runtime.start_execution(admission)
        await client.aclose()

        assert failed.state == "FAILED"
        assert failed.failure_code == "MODEL_PROVIDER_OUTCOME_UNKNOWN"
        assert replayed.failure_code == "MODEL_PROVIDER_OUTCOME_UNKNOWN"
        assert call_count == 1

    asyncio.run(verify())


@pytest.mark.skipif(not UPSTREAM_ROOT.is_dir(), reason="pinned DeerFlow checkout missing")
def test_h1_does_not_publish_success_when_deerflow_status_is_not_persisted(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        admission = CreateH1ExecutionRequest.model_validate(_payload())
        expected_call = build_model_call_request(admission)
        issuer, _ = _issuer(tmp_path)

        async def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(
                200,
                json={
                    "contractVersion": "1.0",
                    "modelCallId": str(expected_call.model_call_id),
                    "status": "RESPONSE_RECEIVED",
                    "assistantText": "不得静默发布",
                    "providerRequestId": "provider-request-2",
                    "finishReason": "stop",
                    "inputTokens": 2,
                    "outputTokens": 2,
                    "usageConfirmed": True,
                    "capturedAmount": 4,
                    "failureCode": None,
                    "replayed": False,
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        model = JavaModelGatewayChatModel(
            base_url="https://platform.internal",
            jwt_issuer=issuer,
            timeout_seconds=10,
            client=client,
        )
        async with DeerFlowH1Runtime(
            data_dir=tmp_path / "runtime-data",
            upstream_root=UPSTREAM_ROOT,
            model=model,
        ) as runtime:
            original = runtime._run_manager.set_status  # noqa: SLF001

            async def discard_status(*args, **kwargs):
                del args, kwargs
                return None

            runtime._run_manager.set_status = discard_status  # noqa: SLF001
            with pytest.raises(
                RuntimeError,
                match="terminal status was not persisted",
            ):
                await runtime.start_execution(admission)
            runtime._run_manager.set_status = original  # noqa: SLF001
            snapshot = await runtime.get_execution(admission.execution_id)
        await client.aclose()

        assert snapshot.state == "RUNNING"
        assert snapshot.output is None

    asyncio.run(verify())


@pytest.mark.skipif(not UPSTREAM_ROOT.is_dir(), reason="pinned DeerFlow checkout missing")
def test_h1_restart_converts_inflight_call_to_unknown_without_redispatch(
    tmp_path: Path,
) -> None:
    async def verify() -> None:
        admission = CreateH1ExecutionRequest.model_validate(_payload())
        model_call = build_model_call_request(admission)
        issuer, _ = _issuer(tmp_path)
        data_dir = tmp_path / "runtime-data"
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: None))
        model = JavaModelGatewayChatModel(
            base_url="https://platform.internal",
            jwt_issuer=issuer,
            timeout_seconds=10,
            client=client,
        )
        first = DeerFlowH1Runtime(
            data_dir=data_dir,
            upstream_root=UPSTREAM_ROOT,
            model=model,
        )
        await first.__aenter__()
        run = await first._run_manager.create_or_reject(  # noqa: SLF001
            str(admission.execution_id),
            metadata={"runtime_profile": "DEERFLOW_H1_TEXT"},
            user_id=str(admission.execution_id),
        )
        await first._run_manager.try_start(run.run_id)  # noqa: SLF001
        now = datetime.now(UTC).isoformat()
        await first._database.execute(  # noqa: SLF001
            """
            INSERT INTO h1_execution (
                execution_id, admission_snapshot_id, idempotency_key,
                request_hash, snapshot_hash, admission_payload, model_call_id,
                deerflow_run_id, state, accepted_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'RUNNING', ?, ?)
            """,
            (
                str(admission.execution_id),
                str(admission.admission_snapshot_id),
                admission.idempotency_key,
                admission.request_hash,
                admission.snapshot_hash,
                admission.model_dump_json(by_alias=True),
                str(model_call.model_call_id),
                run.run_id,
                now,
                now,
            ),
        )
        await first._database.commit()  # noqa: SLF001
        await first.__aexit__(None, None, None)

        replacement_client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: pytest.fail("restart must not redispatch model call")
            )
        )
        replacement = JavaModelGatewayChatModel(
            base_url="https://platform.internal",
            jwt_issuer=issuer,
            timeout_seconds=10,
            client=replacement_client,
        )
        async with DeerFlowH1Runtime(
            data_dir=data_dir,
            upstream_root=UPSTREAM_ROOT,
            model=replacement,
        ) as restarted:
            recovered = await restarted.get_execution(admission.execution_id)
        await client.aclose()
        await replacement_client.aclose()

        assert recovered.state == "FAILED"
        assert recovered.failure_code == "MODEL_GATEWAY_OUTCOME_UNKNOWN"

    asyncio.run(verify())


def test_h1_config_is_default_off_and_only_allows_explicit_loopback_http(
    tmp_path: Path,
) -> None:
    disabled = RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="runtime-api",
        context_enabled=False,
        agent_enabled=False,
        supervisor_enabled=False,
    )
    assert disabled.deerflow_h1_enabled is False

    kwargs = dict(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="runtime-api",
        context_enabled=False,
        agent_enabled=False,
        supervisor_enabled=False,
        deerflow_h1_enabled=True,
        deerflow_h1_data_dir=tmp_path / "data",
        deerflow_source_root=UPSTREAM_ROOT,
        runtime_model_service_base_url="http://127.0.0.1:8080",
        runtime_model_service_jwt_key_id="kid",
        runtime_model_service_jwt_private_key_path=tmp_path / "private.pem",
    )
    with pytest.raises(ValueError, match="base URL"):
        RuntimeSettings(**kwargs)
    allowed = RuntimeSettings(
        **kwargs,
        runtime_model_service_allow_insecure_loopback=True,
    )
    assert "127.0.0.1" not in repr(allowed)

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import jwt
from pydantic import ValidationError
import pytest

from dianlian_runtime.harness.h12_gateway import (
    H12GatewayFailedSafe,
    H12GatewayOutcomeUnknown,
    H12RuntimeServiceJwtIssuer,
    JavaH12GatewayClient,
    JavaModelCall11Request,
    JavaToolCall11Request,
)
from dianlian_runtime.harness.model_gateway import IssuedRuntimeModelJwt


EXECUTION_ID = UUID("22000000-0000-4000-8000-000000000001")
MODEL_CALL_ID = UUID("098aa8f7-d949-5f2f-ab85-e7b30265b759")
TOOL_INVOCATION_ID = UUID("c65dafff-c002-52bd-a135-63d2edc900c6")
SELECTION_ID = UUID("33000000-0000-4000-8000-000000000001")
ADMISSION_ID = UUID("33000000-0000-4000-8000-000000000002")
PROMPT_ID = UUID("33000000-0000-4000-8000-000000000003")
CONTEXT_ID = UUID("33000000-0000-4000-8000-000000000004")
TOOL_POLICY_ID = UUID("33000000-0000-4000-8000-000000000005")
ORCHESTRATION_ID = UUID("33000000-0000-4000-8000-000000000006")
ROUTE_ID = UUID("33000000-0000-4000-8000-000000000007")
MODEL_ID = UUID("33000000-0000-4000-8000-000000000008")
NOW = datetime(2026, 8, 13, tzinfo=UTC)


class RecordingIssuer:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def issue(self, *, scope: str, now: datetime | None = None) -> IssuedRuntimeModelJwt:
        del now
        self.scopes.append(scope)
        sequence = len(self.scopes)
        return IssuedRuntimeModelJwt(
            f"token-{scope}-{sequence}",
            NOW,
            NOW + timedelta(seconds=30),
        )


def model_request() -> JavaModelCall11Request:
    return JavaModelCall11Request(
        model_call_id=MODEL_CALL_ID,
        call_index=1,
        call_phase="INITIAL",
        execution_generation=1,
        idempotency_key="h12-model-1",
        request_hash="a" * 64,
        admission_snapshot_id=ADMISSION_ID,
        prompt_snapshot_id=PROMPT_ID,
        context_snapshot_id=CONTEXT_ID,
        tool_policy_snapshot_id=TOOL_POLICY_ID,
        orchestration_policy_snapshot_id=ORCHESTRATION_ID,
        model_route_binding_id=ROUTE_ID,
        model_route_state_version=2,
        model_definition_id=MODEL_ID,
        model_configuration_version=3,
    )


def tool_request() -> JavaToolCall11Request:
    return JavaToolCall11Request(
        tool_invocation_id=TOOL_INVOCATION_ID,
        execution_generation=1,
        admission_snapshot_id=ADMISSION_ID,
        tool_policy_snapshot_id=TOOL_POLICY_ID,
        model_tool_selection_id=SELECTION_ID,
        idempotency_key="h12-tool-1",
        request_hash="b" * 64,
    )


def final_model_response(*, model_call_id: UUID = MODEL_CALL_ID) -> dict[str, object]:
    return {
        "contractVersion": "1.1",
        "modelCallId": str(model_call_id),
        "status": "RESPONSE_RECEIVED",
        "responseKind": "FINAL_TEXT",
        "modelToolSelectionId": None,
        "assistantText": "结果为 42",
        "providerRequestId": "provider-request-1",
        "providerModelName": "provider-model-1",
        "finishReason": "stop",
        "inputTokens": 8,
        "outputTokens": 3,
        "usageConfirmed": True,
        "capturedAmount": 11,
        "failureCode": None,
        "replayed": False,
    }


def selected_model_response() -> dict[str, object]:
    payload = final_model_response()
    payload.update(
        {
            "responseKind": "TOOL_SELECTION",
            "modelToolSelectionId": str(SELECTION_ID),
            "assistantText": None,
            "finishReason": "tool_calls",
        }
    )
    return payload


def successful_tool_response(
    *, tool_invocation_id: UUID = TOOL_INVOCATION_ID
) -> dict[str, object]:
    return {
        "contractVersion": "1.1",
        "toolInvocationId": str(tool_invocation_id),
        "status": "SUCCEEDED",
        "output": {"value": 42},
        "failureCode": None,
        "replayed": False,
    }


def test_h12_request_contracts_exclude_java_reconstructed_and_sensitive_fields() -> None:
    model_payload = model_request().model_dump(mode="json", by_alias=True)
    tool_payload = tool_request().model_dump(mode="json", by_alias=True)

    assert "systemInstruction" not in model_payload
    assert "messages" not in model_payload
    assert "continuation" not in model_payload
    assert "tool" not in tool_payload
    assert "input" not in tool_payload
    assert tool_payload["selectionMode"] == "MODEL_SELECTED"
    assert set(model_payload).isdisjoint(
        {"key", "apiKey", "baseUrl", "credentialRef", "Authorization"}
    )
    assert set(tool_payload).isdisjoint(
        {"key", "apiKey", "baseUrl", "credentialRef", "Authorization"}
    )

    with pytest.raises(ValidationError):
        JavaModelCall11Request(**{**model_request().model_dump(), "messages": []})
    with pytest.raises(ValidationError):
        JavaToolCall11Request(**{**tool_request().model_dump(), "input": {}})


def test_model_and_tool_calls_use_only_their_exact_service_scope() -> None:
    async def verify() -> None:
        issuer = RecordingIssuer()
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            body = json.loads(request.content)
            assert "Authorization" not in body
            if request.url.path.endswith("/model-calls"):
                assert request.headers["Authorization"] == "Bearer token-model.invoke-1"
                assert body["modelCallId"] == str(MODEL_CALL_ID)
                return httpx.Response(200, json=selected_model_response())
            assert request.headers["Authorization"] == "Bearer token-tool.invoke-2"
            assert body["toolInvocationId"] == str(TOOL_INVOCATION_ID)
            return httpx.Response(200, json=successful_tool_response())

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = JavaH12GatewayClient(
            base_url="https://platform.internal",
            jwt_issuer=issuer,
            timeout_seconds=10,
            client=http_client,
        )
        model = await gateway.invoke_model(EXECUTION_ID, model_request())
        tool = await gateway.invoke_tool(EXECUTION_ID, tool_request())
        await http_client.aclose()

        assert model.model_tool_selection_id == SELECTION_ID
        assert tool.output == {"value": 42}
        assert issuer.scopes == ["model.invoke", "tool.invoke"]
        assert [request.url.path for request in requests] == [
            f"/internal/v1/agent-runtime/executions/{EXECUTION_ID}/model-calls",
            f"/internal/v1/agent-runtime/executions/{EXECUTION_ID}/tool-calls",
        ]

    asyncio.run(verify())


def test_401_refreshes_one_token_and_replays_the_exact_same_model_intent_once() -> None:
    async def verify() -> None:
        issuer = RecordingIssuer()
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(
                    401,
                    json={"code": "INTERNAL_SERVICE_AUTHENTICATION_REQUIRED"},
                )
            return httpx.Response(200, json=final_model_response())

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = JavaH12GatewayClient(
            base_url="https://platform.internal",
            jwt_issuer=issuer,
            timeout_seconds=10,
            client=http_client,
        )
        result = await gateway.invoke_model(EXECUTION_ID, model_request())
        await http_client.aclose()

        assert result.assistant_text == "结果为 42"
        assert issuer.scopes == ["model.invoke", "model.invoke"]
        assert len(requests) == 2
        assert requests[0].content == requests[1].content
        assert requests[0].url == requests[1].url
        assert requests[0].headers["Authorization"] != requests[1].headers["Authorization"]

    asyncio.run(verify())


@pytest.mark.parametrize(
    ("status_code", "problem_code", "expected_attempts"),
    [
        (401, "INTERNAL_SERVICE_AUTHENTICATION_REQUIRED", 2),
        (403, "INTERNAL_SERVICE_SCOPE_DENIED", 1),
        (404, "MODEL_CALL_ADMISSION_MISMATCH", 1),
        (409, "MODEL_CALL_ALREADY_TERMINAL", 1),
    ],
)
def test_safe_http_rejections_never_change_identity_or_retry_except_one_401(
    status_code: int,
    problem_code: str,
    expected_attempts: int,
) -> None:
    async def verify() -> None:
        issuer = RecordingIssuer()
        bodies: list[bytes] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(request.content)
            return httpx.Response(status_code, json={"code": problem_code})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = JavaH12GatewayClient(
            base_url="https://platform.internal",
            jwt_issuer=issuer,
            timeout_seconds=10,
            client=http_client,
        )
        with pytest.raises(H12GatewayFailedSafe) as raised:
            await gateway.invoke_model(EXECUTION_ID, model_request())
        await http_client.aclose()

        assert raised.value.code == problem_code
        assert len(bodies) == expected_attempts
        assert all(json.loads(body)["modelCallId"] == str(MODEL_CALL_ID) for body in bodies)
        assert len(set(bodies)) == 1

    asyncio.run(verify())


@pytest.mark.parametrize(
    ("kind", "problem_code"),
    [
        ("model", "MODEL_CALL_IN_FLIGHT"),
        ("tool", "TOOL_INVOCATION_IN_FLIGHT"),
    ],
)
def test_409_in_flight_is_outcome_unknown_without_retry_or_identity_change(
    kind: str,
    problem_code: str,
) -> None:
    async def verify() -> None:
        issuer = RecordingIssuer()
        bodies: list[bytes] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(request.content)
            return httpx.Response(409, json={"code": problem_code})

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = JavaH12GatewayClient(
            base_url="https://platform.internal",
            jwt_issuer=issuer,
            timeout_seconds=10,
            client=http_client,
        )
        with pytest.raises(H12GatewayOutcomeUnknown) as raised:
            if kind == "model":
                await gateway.invoke_model(EXECUTION_ID, model_request())
            else:
                await gateway.invoke_tool(EXECUTION_ID, tool_request())
        await http_client.aclose()

        assert raised.value.code == problem_code
        assert len(bodies) == 1
        body = json.loads(bodies[0])
        identity = body.get("modelCallId") or body.get("toolInvocationId")
        assert identity == str(MODEL_CALL_ID if kind == "model" else TOOL_INVOCATION_ID)

    asyncio.run(verify())


@pytest.mark.parametrize(
    "scenario",
    [
        "transport",
        "server",
        "bad_json",
        "wrong_contract",
        "wrong_status",
        "wrong_id",
        "unconfirmed_tokens",
    ],
)
def test_ambiguous_or_invalid_model_responses_are_outcome_unknown_without_retry(
    scenario: str,
) -> None:
    async def verify() -> None:
        issuer = RecordingIssuer()
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if scenario == "transport":
                raise httpx.ReadTimeout("ambiguous dispatch", request=request)
            if scenario == "server":
                return httpx.Response(503, json={"code": "MODEL_GATEWAY_UNAVAILABLE"})
            if scenario == "bad_json":
                return httpx.Response(200, content=b"{")
            payload = final_model_response(
                model_call_id=UUID("33000000-0000-4000-8000-000000000099")
                if scenario == "wrong_id"
                else MODEL_CALL_ID
            )
            if scenario == "wrong_contract":
                payload["contractVersion"] = "1.0"
            if scenario == "wrong_status":
                payload["status"] = "COMPLETED"
            if scenario == "unconfirmed_tokens":
                payload.update(
                    {
                        "status": "USAGE_PENDING",
                        "usageConfirmed": False,
                        "capturedAmount": 0,
                    }
                )
            return httpx.Response(200, json=payload)

        http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        gateway = JavaH12GatewayClient(
            base_url="https://platform.internal",
            jwt_issuer=issuer,
            timeout_seconds=10,
            client=http_client,
        )
        with pytest.raises(H12GatewayOutcomeUnknown):
            await gateway.invoke_model(EXECUTION_ID, model_request())
        await http_client.aclose()

        assert call_count == 1
        assert issuer.scopes == ["model.invoke"]

    asyncio.run(verify())


def test_wrong_tool_id_and_sensitive_tool_output_are_response_invalid() -> None:
    async def verify(response_payload: dict[str, object]) -> None:
        issuer = RecordingIssuer()
        http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=response_payload)
            )
        )
        gateway = JavaH12GatewayClient(
            base_url="https://platform.internal",
            jwt_issuer=issuer,
            timeout_seconds=10,
            client=http_client,
        )
        with pytest.raises(H12GatewayOutcomeUnknown) as raised:
            await gateway.invoke_tool(EXECUTION_ID, tool_request())
        await http_client.aclose()
        assert raised.value.code == "H12_GATEWAY_RESPONSE_INVALID"

    wrong_id = successful_tool_response(
        tool_invocation_id=UUID("33000000-0000-4000-8000-000000000099")
    )
    sensitive_output = successful_tool_response()
    sensitive_output["output"] = {"Authorization": "must-not-persist"}
    asyncio.run(verify(wrong_id))
    asyncio.run(verify(sensitive_output))


def test_scoped_issuer_signs_one_exact_scope_per_token(tmp_path: Path) -> None:
    private_key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    private_key_path = tmp_path / "runtime-service-private.pem"
    private_key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    issuer = H12RuntimeServiceJwtIssuer(
        key_id="runtime-service-kid",
        private_key_path=private_key_path,
        ttl_seconds=30,
    )

    issued_at = datetime.now(UTC).replace(microsecond=0)
    for scope, token in (
        ("model.invoke", issuer.issue(now=issued_at)),
        ("tool.invoke", issuer.issue(scope="tool.invoke", now=issued_at)),
        (
            "admission.resolve",
            issuer.issue(scope="admission.resolve", now=issued_at),
        ),
        (
            "model.invoke.structured",
            issuer.issue(scope="model.invoke.structured", now=issued_at),
        ),
    ):
        claims = jwt.decode(
            token.value,
            private_key.public_key(),
            algorithms=["RS256"],
            audience="dianlian-platform",
            issuer="dianlian-ai-runtime",
        )
        assert claims["scope"] == scope
        assert " " not in claims["scope"]

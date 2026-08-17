from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest

from dianlian_runtime.harness.governed_tool_gateway import (
    GovernedToolGatewayClient,
    GovernedToolGatewayOutcomeUnknown,
)
from dianlian_runtime.harness.governed_tool_receipt import (
    GovernedToolIntent,
    GovernedToolRequestReceipt,
)
from dianlian_runtime.harness.h12_durable import (
    canonical_intent,
    stable_model_call_id,
    stable_tool_call_id,
)
from dianlian_runtime.harness.model_gateway import IssuedRuntimeModelJwt
from dianlian_runtime.supervisor.contracts import ExternalOperation
from dianlian_runtime.supervisor.tool_permit_issuer import ToolPermitReceipt


EXECUTION_ID = UUID("d1000000-0000-4000-8000-000000000001")
TENANT_ID = UUID("d1000000-0000-4000-8000-000000000002")
ADMISSION_ID = UUID("d1000000-0000-4000-8000-000000000003")
PERMIT_ID = UUID("d1000000-0000-4000-8000-000000000004")
ARM_EVENT_ID = UUID("d1000000-0000-4000-8000-000000000005")
NOW = datetime(2026, 8, 14, tzinfo=UTC)


class RecordingIssuer:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def issue(self, *, scope: str, now: datetime | None = None) -> IssuedRuntimeModelJwt:
        del now
        self.scopes.append(scope)
        return IssuedRuntimeModelJwt("governed-tool-token", NOW, NOW + timedelta(seconds=30))


def test_client_sends_exact_receipt_once_with_the_governed_tool_scope() -> None:
    async def verify() -> None:
        receipt = _receipt()
        issuer = RecordingIssuer()
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(202, json=_response(receipt, pending=True))

        client = GovernedToolGatewayClient(
            base_url="https://java.internal",
            jwt_issuer=issuer,
            timeout_seconds=5,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        result = await client.invoke(receipt)

        assert result.disposition == "CANONICAL_OUTCOME_PENDING"
        assert result.provider_retry_allowed is False
        assert issuer.scopes == ["tool.invoke.governed"]
        assert len(requests) == 1
        assert requests[0].content == receipt.exact_body
        assert requests[0].url.path.endswith(
            f"/{EXECUTION_ID}/governed-tool-calls/model-selected"
        )

    asyncio.run(verify())


def test_client_accepts_only_applied_canonical_fact_on_http_200() -> None:
    async def verify() -> None:
        receipt = _receipt()

        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(200, json=_response(receipt, pending=False))

        client = GovernedToolGatewayClient(
            base_url="https://java.internal",
            jwt_issuer=RecordingIssuer(),
            timeout_seconds=5,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        result = await client.invoke(receipt)

        assert result.disposition == "CANONICAL_OUTCOME_APPLIED"
        assert result.canonical_fact is not None
        assert result.canonical_fact.outcome_status == "SUCCEEDED"

    asyncio.run(verify())


def test_client_rejects_another_attempt_without_retrying() -> None:
    async def verify() -> None:
        receipt = _receipt()
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            del request
            calls += 1
            payload = _response(receipt, pending=True)
            payload["attemptedDispatch"] = {
                **payload["attemptedDispatch"],
                "runtimeExternalPermitId": "d1000000-0000-4000-8000-000000000099",
            }
            return httpx.Response(202, json=payload)

        client = GovernedToolGatewayClient(
            base_url="https://java.internal",
            jwt_issuer=RecordingIssuer(),
            timeout_seconds=5,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        with pytest.raises(GovernedToolGatewayOutcomeUnknown):
            await client.invoke(receipt)
        assert calls == 1

    asyncio.run(verify())


def test_client_does_not_retry_a_transport_unknown() -> None:
    async def verify() -> None:
        receipt = _receipt()
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ConnectError("connection lost", request=request)

        client = GovernedToolGatewayClient(
            base_url="https://java.internal",
            jwt_issuer=RecordingIssuer(),
            timeout_seconds=5,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        with pytest.raises(GovernedToolGatewayOutcomeUnknown):
            await client.invoke(receipt)
        assert calls == 1

    asyncio.run(verify())


def _receipt() -> GovernedToolRequestReceipt:
    intent = GovernedToolIntent.model_validate(
        {
            "contractVersion": "1.2",
            "selectionMode": "MODEL_SELECTED",
            "toolInvocationId": stable_tool_call_id(EXECUTION_ID),
            "sourceModelCallId": stable_model_call_id(EXECUTION_ID, 1),
            "executionGeneration": 3,
            "admissionSnapshotId": ADMISSION_ID,
            "toolPolicySnapshotId": UUID("d1000000-0000-4000-8000-000000000006"),
            "modelToolSelectionId": UUID("d1000000-0000-4000-8000-000000000007"),
            "toolCallSlot": 1,
            "idempotencyKey": f"h12:{EXECUTION_ID}:tool:1",
        },
        strict=True,
    )
    _, request_hash = canonical_intent(intent.durable_payload())
    permit = ToolPermitReceipt(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=PERMIT_ID,
        runtime_run_id=EXECUTION_ID,
        task_execution_generation=3,
        lease_owner="worker-3",
        lease_epoch=3,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash="a" * 64,
        operation_kind=ExternalOperation.TOOL_INVOKE,
        intent_id=intent.tool_invocation_id,
        request_hash=request_hash,
        issue_event_id=UUID("d1000000-0000-4000-8000-000000000008"),
        arm_event_id=ARM_EVENT_ID,
        permit_attempt=1,
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    return GovernedToolRequestReceipt.create(EXECUTION_ID, intent, permit)


def _response(
    receipt: GovernedToolRequestReceipt,
    *,
    pending: bool,
) -> dict[str, object]:
    dispatch = {
        "runtimeExternalPermitId": str(PERMIT_ID),
        "leaseOwner": "worker-3",
        "leaseEpoch": 3,
        "armEventId": str(ARM_EVENT_ID),
    }
    return {
        "contractVersion": "1.2",
        "toolInvocationId": str(receipt.request.tool_invocation_id),
        "requestHash": receipt.request.request_hash,
        "disposition": (
            "CANONICAL_OUTCOME_PENDING"
            if pending
            else "CANONICAL_OUTCOME_APPLIED"
        ),
        "action": "REDELIVER_SAME_CANONICAL_FACT" if pending else "NONE",
        "providerRetryAllowed": False,
        "persistedDispatch": dispatch,
        "attemptedDispatch": dispatch,
        "canonicalFact": {
            "outcomeEventId": "d1000000-0000-4000-8000-000000000009",
            "outcomeStatus": "SUCCEEDED",
            "sourceFactId": "d1000000-0000-4000-8000-00000000000a",
            "sourceFactVersion": 1,
            "sourceFactHash": "b" * 64,
            "outcomeCode": "TOOL_SUCCEEDED",
            "resultHash": "c" * 64,
        },
    }

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
from uuid import UUID

import httpx
import pytest

from dianlian_runtime.harness.governed_model_gateway import (
    GovernedInitialModelGatewayClient,
    GovernedModelGatewayOutcomeUnknown,
)
from dianlian_runtime.harness.governed_model_intent import (
    GovernedInitialModelIntent,
)
from dianlian_runtime.harness.governed_model_receipt import (
    GovernedInitialModelRequestReceipt,
)
from dianlian_runtime.harness.h12_durable import (
    canonical_intent,
    stable_model_call_id,
)
from dianlian_runtime.harness.model_gateway import IssuedRuntimeModelJwt
from dianlian_runtime.supervisor.contracts import ExternalOperation
from dianlian_runtime.supervisor.model_permit_issuer import ModelPermitReceipt


EXECUTION_ID = UUID("62000000-0000-4000-8000-000000000001")
TENANT_ID = UUID("62000000-0000-4000-8000-000000000002")
ADMISSION_ID = UUID("62000000-0000-4000-8000-000000000003")
PERMIT_ID = UUID("62000000-0000-4000-8000-000000000004")
ARM_EVENT_ID = UUID("62000000-0000-4000-8000-000000000005")
NOW = datetime(2026, 8, 14, tzinfo=UTC)


class RecordingIssuer:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def issue(self, *, scope: str, now: datetime | None = None) -> IssuedRuntimeModelJwt:
        del now
        self.scopes.append(scope)
        return IssuedRuntimeModelJwt(
            "governed-token",
            NOW,
            NOW + timedelta(seconds=30),
        )


def test_client_sendsTheExactReceiptOnceAndKeepsPendingResultHidden() -> None:
    async def verify() -> None:
        receipt = _receipt()
        issuer = RecordingIssuer()
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(202, json=_response(receipt, pending=True))

        client = GovernedInitialModelGatewayClient(
            base_url="https://java.internal",
            jwt_issuer=issuer,
            timeout_seconds=5,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        result = await client.invoke_initial(receipt)

        assert result.disposition == "CANONICAL_OUTCOME_PENDING"
        assert result.terminal_result is None
        assert result.provider_retry_allowed is False
        assert issuer.scopes == ["model.invoke.governed"]
        assert len(requests) == 1
        assert requests[0].content == receipt.exact_body
        assert requests[0].headers["authorization"] == "Bearer governed-token"
        assert requests[0].url.path.endswith(
            f"/{EXECUTION_ID}/governed-model-calls/initial"
        )

    asyncio.run(verify())


def test_clientAcceptsOnlyAppliedFinalTextOnHttp200() -> None:
    async def verify() -> None:
        receipt = _receipt()

        def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(200, json=_response(receipt, pending=False))

        client = GovernedInitialModelGatewayClient(
            base_url="https://java.internal",
            jwt_issuer=RecordingIssuer(),
            timeout_seconds=5,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        result = await client.invoke_initial(receipt)

        assert result.disposition == "CANONICAL_OUTCOME_APPLIED"
        assert result.terminal_result is not None
        assert result.terminal_result.assistant_text == "answer"

    asyncio.run(verify())


def test_clientRejectsAResponseForAnotherAttemptAndDoesNotRetry() -> None:
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
                "runtimeExternalPermitId": str(
                    UUID("62000000-0000-4000-8000-000000000099")
                ),
            }
            return httpx.Response(202, json=payload)

        client = GovernedInitialModelGatewayClient(
            base_url="https://java.internal",
            jwt_issuer=RecordingIssuer(),
            timeout_seconds=5,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        with pytest.raises(
            GovernedModelGatewayOutcomeUnknown,
            match="governed Java model gateway call failed",
        ):
            await client.invoke_initial(receipt)
        assert calls == 1

    asyncio.run(verify())


def test_clientDoesNotRetryTransportOrServerUnknowns() -> None:
    async def verify() -> None:
        receipt = _receipt()
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.ConnectError("connection lost", request=request)

        client = GovernedInitialModelGatewayClient(
            base_url="https://java.internal",
            jwt_issuer=RecordingIssuer(),
            timeout_seconds=5,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        with pytest.raises(GovernedModelGatewayOutcomeUnknown):
            await client.invoke_initial(receipt)
        assert calls == 1

    asyncio.run(verify())


def _receipt() -> GovernedInitialModelRequestReceipt:
    intent = _intent()
    _, request_hash = canonical_intent(intent.durable_payload())
    permit = ModelPermitReceipt(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=PERMIT_ID,
        runtime_run_id=EXECUTION_ID,
        task_execution_generation=3,
        lease_owner="worker-3",
        lease_epoch=3,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash="a" * 64,
        operation_kind=ExternalOperation.MODEL_INVOKE,
        intent_id=intent.model_call_id,
        request_hash=request_hash,
        issue_event_id=UUID("62000000-0000-4000-8000-000000000006"),
        arm_event_id=ARM_EVENT_ID,
        permit_attempt=1,
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    return GovernedInitialModelRequestReceipt.create(EXECUTION_ID, intent, permit)


def _intent() -> GovernedInitialModelIntent:
    return GovernedInitialModelIntent.model_validate(
        {
            "contractVersion": "1.2",
            "modelCallId": stable_model_call_id(EXECUTION_ID, 1),
            "callIndex": 1,
            "callPhase": "INITIAL",
            "executionGeneration": 3,
            "idempotencyKey": "governed-model-1",
            "admissionSnapshotId": ADMISSION_ID,
            "promptSnapshotId": UUID(
                "62000000-0000-4000-8000-000000000007"
            ),
            "contextSnapshotId": UUID(
                "62000000-0000-4000-8000-000000000008"
            ),
            "toolPolicySnapshotId": UUID(
                "62000000-0000-4000-8000-000000000009"
            ),
            "orchestrationPolicySnapshotId": UUID(
                "62000000-0000-4000-8000-00000000000a"
            ),
            "modelRouteBindingId": UUID(
                "62000000-0000-4000-8000-00000000000b"
            ),
            "modelRouteStateVersion": 5,
            "modelDefinitionId": UUID(
                "62000000-0000-4000-8000-00000000000c"
            ),
            "modelConfigurationVersion": 7,
        },
        strict=True,
    )


def _response(
    receipt: GovernedInitialModelRequestReceipt,
    *,
    pending: bool,
) -> dict[str, object]:
    dispatch = {
        "runtimeExternalPermitId": str(PERMIT_ID),
        "leaseOwner": "worker-3",
        "leaseEpoch": 3,
        "armEventId": str(ARM_EVENT_ID),
    }
    fact = {
        "outcomeEventId": "62000000-0000-4000-8000-00000000000d",
        "outcomeStatus": "SUCCEEDED",
        "sourceFactId": "62000000-0000-4000-8000-00000000000e",
        "sourceFactVersion": 1,
        "sourceFactHash": "b" * 64,
        "outcomeCode": "MODEL_RESPONSE_RECEIVED",
        "resultHash": "c" * 64,
    }
    result = None
    if not pending:
        result = {
            "status": "RESPONSE_RECEIVED",
            "responseKind": "FINAL_TEXT",
            "assistantText": "answer",
            "providerRequestId": "provider-request-1",
            "providerModelName": "model-a",
            "finishReason": "stop",
            "inputTokens": 2,
            "outputTokens": 3,
            "usageConfirmed": True,
            "capturedAmount": 0,
            "failureCode": None,
        }
    return {
        "contractVersion": "1.2",
        "modelCallId": str(receipt.request.model_call_id),
        "requestHash": receipt.request.request_hash,
        "disposition": (
            "CANONICAL_OUTCOME_PENDING"
            if pending
            else "CANONICAL_OUTCOME_APPLIED"
        ),
        "modelCallStatus": "RESPONSE_RECEIVED",
        "failureCode": None,
        "action": "REDELIVER_SAME_CANONICAL_FACT" if pending else "NONE",
        "providerRetryAllowed": False,
        "persistedDispatch": dispatch,
        "attemptedDispatch": dispatch,
        "canonicalFact": fact,
        "terminalResult": result,
    }

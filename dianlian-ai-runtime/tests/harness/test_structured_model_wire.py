from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
from uuid import UUID

import httpx
from pydantic import ValidationError
import pytest

from dianlian_runtime.harness.model_gateway import IssuedRuntimeModelJwt
from dianlian_runtime.harness.structured_admission_manifest import (
    JavaCapabilityStructuredAdmissionManifest,
    structured_one_call_policy_hash,
)
from dianlian_runtime.harness.structured_model_gateway import (
    StructuredModelGatewayClient,
    StructuredModelGatewayOutcomeUnknown,
)
from dianlian_runtime.harness.structured_model_receipt import (
    StructuredModelRequestReceipt,
    stable_structured_model_call_id,
    structured_model_idempotency_key,
    structured_model_request_hash,
)
from dianlian_runtime.supervisor.contracts import ExternalOperation
from dianlian_runtime.supervisor.model_permit_issuer import ModelPermitReceipt


EXECUTION_ID = UUID("61000000-0000-4000-8000-000000000001")
TENANT_ID = UUID("61000000-0000-4000-8000-000000000002")
ADMISSION_ID = UUID("61000000-0000-4000-8000-000000000006")
PERMIT_ID = UUID("61000000-0000-4000-8000-00000000001e")
ARM_EVENT_ID = UUID("61000000-0000-4000-8000-00000000001f")
NOW = datetime(2026, 8, 16, tzinfo=UTC)


class RecordingIssuer:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def issue(self, *, scope: str, now: datetime | None = None) -> IssuedRuntimeModelJwt:
        del now
        self.scopes.append(scope)
        return IssuedRuntimeModelJwt("structured-token", NOW, NOW + timedelta(seconds=30))


def test_cross_language_identity_vectors_and_manifest_contract_are_frozen() -> None:
    manifest = _manifest()

    assert str(stable_structured_model_call_id(EXECUTION_ID)) == (
        "13345505-012e-5209-9ca5-a4f3482f5c9f"
    )
    assert structured_model_idempotency_key(EXECUTION_ID) == (
        "structured-model-call:13345505-012e-5209-9ca5-a4f3482f5c9f"
    )
    assert structured_model_request_hash(EXECUTION_ID, ADMISSION_ID, "1" * 64) == (
        "c7388e234073100fd2e4837e565ac6c495b36c889dd0c4be8868d01f90375bd1"
    )
    assert manifest.one_call_policy.hash == (
        "3d08b7df1c8938db21ee13482e27987705f20bc6556a3184032e748d6e4291b8"
    )
    assert manifest.model_requirement.required_feature_codes == [
        "JSON_SCHEMA_STRUCTURED_OUTPUT"
    ]


def test_manifest_rejects_unknown_or_cross_contract_drift() -> None:
    payload = _manifest_payload()
    with pytest.raises(ValidationError):
        JavaCapabilityStructuredAdmissionManifest.model_validate(
            {**payload, "apiKey": "must-not-enter-admission"},
            strict=True,
        )

    drifted = dict(payload)
    drifted["candidateSchemaVersion"] = "2.0.0"
    with pytest.raises(ValidationError):
        JavaCapabilityStructuredAdmissionManifest.model_validate(
            drifted,
            strict=True,
        )

    overflow = dict(payload)
    overflow["executionGeneration"] = 2**63
    with pytest.raises(ValidationError):
        JavaCapabilityStructuredAdmissionManifest.model_validate(
            overflow,
            strict=True,
        )


def test_receipt_contains_exact_java_body_and_rejects_replacement() -> None:
    receipt = _receipt()
    body = json.loads(receipt.exact_body)

    assert body["contractVersion"] == "1.0"
    assert body["modelCallId"] == str(stable_structured_model_call_id(EXECUTION_ID))
    assert set(body["dispatchArm"]) == {
        "runtimeExternalPermitId",
        "leaseOwner",
        "leaseEpoch",
        "armEventId",
    }
    assert set(body).isdisjoint({"apiKey", "baseUrl", "providerModelName"})
    assert StructuredModelRequestReceipt.restore(
        EXECUTION_ID,
        receipt.exact_body,
        receipt.body_sha256,
    ) == receipt

    duplicate = receipt.exact_body.replace(
        b'"contractVersion":"1.0"',
        b'"contractVersion":"1.0","contractVersion":"1.0"',
        1,
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        StructuredModelRequestReceipt.restore(
            EXECUTION_ID,
            duplicate,
            receipt.body_sha256,
        )


def test_gateway_sends_exact_receipt_once_and_keeps_pending_body_hidden() -> None:
    async def verify() -> None:
        receipt = _receipt()
        issuer = RecordingIssuer()
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(202, json=_response(receipt, "pending"))

        client = StructuredModelGatewayClient(
            base_url="https://java.internal",
            jwt_issuer=issuer,
            timeout_seconds=5,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        result = await client.invoke(receipt)

        assert result.disposition == "CANONICAL_OUTCOME_PENDING"
        assert result.candidate_receipt is None
        assert issuer.scopes == ["model.invoke.structured"]
        assert len(requests) == 1
        assert requests[0].content == receipt.exact_body
        assert requests[0].url.path.endswith(
            f"/{EXECUTION_ID}/structured-model-calls/capability"
        )

    asyncio.run(verify())


def test_gateway_accepts_only_exact_projected_receipt_and_never_retries_invalid() -> None:
    async def verify(mode: str) -> None:
        receipt = _receipt()
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            del request
            calls += 1
            if mode == "projected":
                return httpx.Response(200, json=_response(receipt, mode))
            payload = _response(receipt, "pending")
            payload["attemptedDispatch"] = {
                **payload["attemptedDispatch"],
                "runtimeExternalPermitId": str(
                    UUID("61000000-0000-4000-8000-000000000099")
                ),
            }
            return httpx.Response(202, json=payload)

        client = StructuredModelGatewayClient(
            base_url="https://java.internal",
            jwt_issuer=RecordingIssuer(),
            timeout_seconds=5,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        if mode == "projected":
            result = await client.invoke(receipt)
            assert result.disposition == "CANDIDATE_PROJECTED"
            assert result.candidate_receipt is not None
        else:
            with pytest.raises(StructuredModelGatewayOutcomeUnknown):
                await client.invoke(receipt)
        assert calls == 1

    asyncio.run(verify("projected"))
    asyncio.run(verify("mismatch"))


def _manifest() -> JavaCapabilityStructuredAdmissionManifest:
    return JavaCapabilityStructuredAdmissionManifest.model_validate(
        _manifest_payload(),
        strict=True,
    )


def _manifest_payload() -> dict[str, object]:
    ceiling = 100
    return {
        "runtimeRunId": EXECUTION_ID,
        "tenantId": TENANT_ID,
        "taskId": UUID("61000000-0000-4000-8000-000000000003"),
        "taskStepId": UUID("61000000-0000-4000-8000-000000000004"),
        "executionGeneration": 1,
        "actorUserId": UUID("61000000-0000-4000-8000-000000000005"),
        "admissionContractVersion": "3.0",
        "runtimeProfile": "JAVA_CAPABILITY_STRUCTURED",
        "admissionSnapshotId": ADMISSION_ID,
        "admissionSnapshotHash": "1" * 64,
        "requestHash": "2" * 64,
        "idempotencyKey": "structured-model-admission-0001",
        "inputSnapshotId": UUID("61000000-0000-4000-8000-000000000007"),
        "enterpriseAgentId": UUID("61000000-0000-4000-8000-000000000008"),
        "agentVersionId": UUID("61000000-0000-4000-8000-000000000009"),
        "configurationVersionId": UUID("61000000-0000-4000-8000-00000000000a"),
        "pointReservationId": UUID("61000000-0000-4000-8000-00000000000b"),
        "capabilityPack": {
            "packCode": "QUOTATION",
            "packVersion": "1.3.0",
            "manifestHash": "3" * 64,
        },
        "modelRequirement": {
            "requiredCapabilityCodes": ["TEXT_CHAT"],
            "requiredFeatureCodes": ["JSON_SCHEMA_STRUCTURED_OUTPUT"],
            "responseContractCode": "quotation.model-candidate-drafts",
            "responseContractVersion": "1.0.0",
        },
        "modelResponseContract": {
            "reference": {
                "kind": "MODEL_RESPONSE_SCHEMA",
                "contractCode": "QUOTATION.MODEL-CANDIDATE-DRAFTS",
                "version": "1.0.0",
                "contractHash": "5" * 64,
            },
            "providerSchemaName": "quotation_candidate_drafts",
            "jsonSchema": '{"type":"object"}',
        },
        "candidateOutputContract": {
            "kind": "OUTPUT_SCHEMA",
            "contractCode": "QUOTATION.CANDIDATES",
            "version": "1.0.0",
            "contractHash": "4" * 64,
        },
        "candidateSchemaId": "quotation.candidates",
        "candidateSchemaVersion": "1.0.0",
        "modelRoute": {
            "routeBindingId": UUID("61000000-0000-4000-8000-00000000000c"),
            "routeStateVersion": 1,
            "modelDefinitionId": UUID("61000000-0000-4000-8000-00000000000d"),
            "modelConfigurationVersion": 1,
            "reservationCeilingMicroCredit": ceiling,
        },
        "modelQualification": {
            "policyId": UUID("61000000-0000-4000-8000-00000000000e"),
            "policyVersion": 1,
            "policyHash": "8" * 64,
            "dataSensitivityCode": "SENSITIVE",
            "selectionReasonCode": "QUALIFIED_EXACT_ROUTE",
            "sensitivityEvidenceHash": "9" * 64,
        },
        "prompt": {
            "snapshotId": UUID("61000000-0000-4000-8000-00000000000f"),
            "hash": "6" * 64,
        },
        "context": {
            "snapshotId": UUID("61000000-0000-4000-8000-000000000010"),
            "hash": "7" * 64,
        },
        "oneCallPolicy": {
            "policySnapshotId": UUID("61000000-0000-4000-8000-000000000011"),
            "maxModelCalls": 1,
            "maxToolCalls": 0,
            "modelCallReservationCeiling": ceiling,
            "totalModelReservationCeiling": ceiling,
            "hash": structured_one_call_policy_hash(ceiling),
        },
    }


def _receipt() -> StructuredModelRequestReceipt:
    manifest = _manifest()
    request_hash = structured_model_request_hash(
        EXECUTION_ID,
        ADMISSION_ID,
        manifest.admission_snapshot_hash,
    )
    permit = ModelPermitReceipt(
        tenant_id=TENANT_ID,
        runtime_external_permit_id=PERMIT_ID,
        runtime_run_id=EXECUTION_ID,
        task_execution_generation=1,
        lease_owner="worker-1",
        lease_epoch=1,
        admission_snapshot_id=ADMISSION_ID,
        admission_snapshot_hash=manifest.admission_snapshot_hash,
        operation_kind=ExternalOperation.MODEL_INVOKE,
        intent_id=stable_structured_model_call_id(EXECUTION_ID),
        request_hash=request_hash,
        issue_event_id=UUID("61000000-0000-4000-8000-00000000001d"),
        arm_event_id=ARM_EVENT_ID,
        permit_attempt=1,
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=30),
    )
    return StructuredModelRequestReceipt.create(EXECUTION_ID, manifest, permit)


def _response(
    receipt: StructuredModelRequestReceipt,
    mode: str,
) -> dict[str, object]:
    dispatch = {
        "runtimeExternalPermitId": str(PERMIT_ID),
        "leaseOwner": "worker-1",
        "leaseEpoch": 1,
        "armEventId": str(ARM_EVENT_ID),
    }
    fact = {
        "outcomeEventId": "61000000-0000-4000-8000-000000000020",
        "outcomeStatus": "SUCCEEDED",
        "sourceFactId": "61000000-0000-4000-8000-000000000021",
        "sourceFactVersion": 1,
        "sourceFactHash": "a" * 64,
        "outcomeCode": "STRUCTURED_MODEL_RESPONSE_RECEIVED",
        "resultHash": "b" * 64,
    }
    projected = mode == "projected"
    return {
        "contractVersion": "1.0",
        "modelCallId": str(receipt.request.model_call_id),
        "modelRequestHash": receipt.request.model_request_hash,
        "disposition": (
            "CANDIDATE_PROJECTED" if projected else "CANONICAL_OUTCOME_PENDING"
        ),
        "modelCallStatus": "RESPONSE_RECEIVED",
        "action": "NONE" if projected else "REDELIVER_SAME_CANONICAL_FACT",
        "providerRetryAllowed": False,
        "persistedDispatch": dispatch,
        "attemptedDispatch": dispatch,
        "canonicalFact": fact,
        "candidateReceipt": (
            {
                "documentId": "61000000-0000-4000-8000-000000000022",
                "documentKind": "EXTRACTION_CANDIDATE_BATCH",
                "documentVersion": 1,
                "documentHash": "c" * 64,
            }
            if projected
            else None
        ),
    }

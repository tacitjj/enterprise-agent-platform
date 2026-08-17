from __future__ import annotations

import hashlib
from uuid import UUID

import pytest

from dianlian_runtime.harness.admission_manifest import JavaAdmissionManifest
from dianlian_runtime.harness.governed_model_intent import (
    build_governed_after_tool_model_intent,
    build_governed_initial_model_intent,
)
from dianlian_runtime.harness.h12_durable import (
    canonical_intent,
    stable_model_call_id,
)


RUN_ID = UUID("51000000-0000-4000-8000-000000000001")
ADMISSION_ID = UUID("51000000-0000-4000-8000-000000000002")
PROMPT_ID = UUID("51000000-0000-4000-8000-000000000003")
CONTEXT_ID = UUID("51000000-0000-4000-8000-000000000004")
TOOL_POLICY_ID = UUID("51000000-0000-4000-8000-000000000005")
ORCHESTRATION_ID = UUID("51000000-0000-4000-8000-000000000006")
ROUTE_ID = UUID("51000000-0000-4000-8000-000000000007")
MODEL_ID = UUID("51000000-0000-4000-8000-000000000008")
HASH = "a" * 64


def manifest() -> JavaAdmissionManifest:
    ceiling = 100_000
    orchestration_canonical = (
        '{"schemaVersion":"runtime-orchestration-policy-v1",'
        '"maxModelCalls":2,'
        '"maxToolCalls":1,'
        f'"modelCallReservationCeiling":{ceiling},'
        f'"totalModelReservationCeiling":{ceiling * 2}}}'
    )
    return JavaAdmissionManifest.model_validate(
        {
            "runtimeRunId": RUN_ID,
            "tenantId": UUID("51000000-0000-4000-8000-000000000009"),
            "taskId": UUID("51000000-0000-4000-8000-000000000010"),
            "taskStepId": UUID("51000000-0000-4000-8000-000000000011"),
            "executionGeneration": 3,
            "admissionContractVersion": "2.2",
            "runtimeProfile": "DEERFLOW_H1_TEXT",
            "admissionSnapshotId": ADMISSION_ID,
            "admissionSnapshotHash": HASH,
            "requestHash": "b" * 64,
            "idempotencyKey": "run-idempotency",
            "actorUserId": UUID("51000000-0000-4000-8000-000000000012"),
            "inputSnapshotId": UUID("51000000-0000-4000-8000-000000000013"),
            "enterpriseAgentId": UUID("51000000-0000-4000-8000-000000000014"),
            "agentVersionId": UUID("51000000-0000-4000-8000-000000000015"),
            "configurationVersionId": UUID(
                "51000000-0000-4000-8000-000000000016"
            ),
            "pointReservationId": UUID("51000000-0000-4000-8000-000000000017"),
            "modelRoute": {
                "routeBindingId": ROUTE_ID,
                "routeStateVersion": 5,
                "modelDefinitionId": MODEL_ID,
                "modelConfigurationVersion": 7,
                "reservationCeilingMicroCredit": ceiling,
            },
            "prompt": {"promptSnapshotId": PROMPT_ID, "hash": "c" * 64},
            "context": {"contextSnapshotId": CONTEXT_ID, "hash": "d" * 64},
            "toolPolicy": {
                "toolPolicySnapshotId": TOOL_POLICY_ID,
                "hash": "e" * 64,
            },
            "orchestrationPolicy": {
                "orchestrationPolicySnapshotId": ORCHESTRATION_ID,
                "maxModelCalls": 2,
                "maxToolCalls": 1,
                "modelCallReservationCeiling": ceiling,
                "totalModelReservationCeiling": ceiling * 2,
                "hash": hashlib.sha256(
                    orchestration_canonical.encode("utf-8")
                ).hexdigest(),
            },
        },
        strict=True,
    )


def test_builds_exact_receipt_only_initial_intent() -> None:
    source = manifest()

    intent = build_governed_initial_model_intent(source)

    assert intent.model_call_id == stable_model_call_id(RUN_ID, 1)
    assert intent.contract_version == "1.2"
    assert intent.call_index == 1
    assert intent.call_phase == "INITIAL"
    assert intent.execution_generation == 3
    assert intent.admission_snapshot_id == ADMISSION_ID
    assert intent.prompt_snapshot_id == PROMPT_ID
    assert intent.context_snapshot_id == CONTEXT_ID
    assert intent.tool_policy_snapshot_id == TOOL_POLICY_ID
    assert intent.orchestration_policy_snapshot_id == ORCHESTRATION_ID
    assert intent.model_route_binding_id == ROUTE_ID
    assert intent.model_route_state_version == 5
    assert intent.model_definition_id == MODEL_ID
    assert intent.model_configuration_version == 7


def test_canonical_intent_excludes_authority_and_permit_envelope() -> None:
    intent = build_governed_initial_model_intent(manifest())

    canonical, request_hash = canonical_intent(intent.durable_payload())

    assert request_hash == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert set(intent.durable_payload()) == {
        "contractVersion",
        "modelCallId",
        "callIndex",
        "callPhase",
        "executionGeneration",
        "idempotencyKey",
        "admissionSnapshotId",
        "promptSnapshotId",
        "contextSnapshotId",
        "toolPolicySnapshotId",
        "orchestrationPolicySnapshotId",
        "modelRouteBindingId",
        "modelRouteStateVersion",
        "modelDefinitionId",
        "modelConfigurationVersion",
    }
    assert all(
        forbidden not in canonical
        for forbidden in (
            "tenantId",
            "runtimeExternalPermitId",
            "leaseOwner",
            "leaseEpoch",
            "armEventId",
            "issueEventId",
            "secret",
            "token",
        )
    )


def test_builds_after_tool_intent_from_the_same_frozen_admission() -> None:
    intent = build_governed_after_tool_model_intent(manifest())

    assert intent.model_call_id == stable_model_call_id(RUN_ID, 2)
    assert intent.call_index == 2
    assert intent.call_phase == "AFTER_TOOL"
    assert intent.idempotency_key == f"h12:{RUN_ID}:model:2"
    assert intent.admission_snapshot_id == ADMISSION_ID
    assert intent.tool_policy_snapshot_id == TOOL_POLICY_ID
    assert set(intent.durable_payload()) == set(
        build_governed_initial_model_intent(manifest()).durable_payload()
    )


def test_rejects_non_manifest_input() -> None:
    with pytest.raises(TypeError, match="manifest must be a JavaAdmissionManifest"):
        build_governed_initial_model_intent(object())  # type: ignore[arg-type]

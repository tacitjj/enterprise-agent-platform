from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from dianlian_runtime.config import RuntimeSettings
from tests.internal_auth_testkit import create_test_app


def _settings(*, context_enabled: bool) -> RuntimeSettings:
    return RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="runtime-api",
        context_enabled=context_enabled,
        agent_enabled=False,
        supervisor_enabled=False,
    )


def _request() -> dict:
    return {
        "contractVersion": "1.0",
        "requestId": "10000000-0000-0000-0000-000000000001",
        "traceId": "20000000-0000-0000-0000-000000000001",
        "deadlineAt": "2026-08-12T12:00:00Z",
        "tenantId": "30000000-0000-0000-0000-000000000001",
        "actorUserId": "40000000-0000-0000-0000-000000000001",
        "enterpriseAgentId": "50000000-0000-0000-0000-000000000001",
        "conversationId": "60000000-0000-0000-0000-000000000001",
        "query": "查找已经确认的相关企业资料",
        "audienceUserIds": ["40000000-0000-0000-0000-000000000001"],
        "authorizedKnowledgeResources": [
            {
                "tenantId": "30000000-0000-0000-0000-000000000001",
                "resourceId": "70000000-0000-0000-0000-000000000001",
                "resourceVersionId": "80000000-0000-0000-0000-000000000001",
            }
        ],
        "allowedMemoryScopes": [],
        "requestedSources": ["KNOWLEDGE"],
        "policy": {
            "lexicalTopK": 20,
            "vectorTopK": 20,
            "rerankTopK": 10,
            "maxEvidence": 5,
            "maxContextTokens": 4000,
        },
        "authorizationSnapshotHash": "a" * 64,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update({"unexpected": True}),
        lambda body: body["policy"].update({"maxEvidence": "5"}),
    ],
)
def test_retrieval_contract_is_strict_and_forbids_extra_fields(mutate) -> None:
    body = deepcopy(_request())
    mutate(body)

    response = TestClient(create_test_app(_settings(context_enabled=False))).post(
        "/internal/v1/retrieval/search",
        json=body,
    )

    assert response.status_code == 422


def test_requested_source_requires_an_explicit_authorization_allowlist() -> None:
    body = _request()
    body["authorizedKnowledgeResources"] = []

    response = TestClient(create_test_app(_settings(context_enabled=False))).post(
        "/internal/v1/retrieval/search",
        json=body,
    )

    assert response.status_code == 422
    assert "explicit resource allowlist" in response.text


def test_memory_source_requires_an_explicit_scope_allowlist() -> None:
    body = _request()
    body["requestedSources"] = ["MEMORY"]
    body["authorizedKnowledgeResources"] = []

    response = TestClient(create_test_app(_settings(context_enabled=False))).post(
        "/internal/v1/retrieval/search",
        json=body,
    )

    assert response.status_code == 422
    assert "explicit scope allowlist" in response.text


def test_disabled_context_feature_fails_closed() -> None:
    response = TestClient(create_test_app(_settings(context_enabled=False))).post(
        "/internal/v1/retrieval/search",
        json=_request(),
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "CONTEXT_FEATURE_DISABLED",
        "message": "Context retrieval is disabled",
    }


def test_enabled_context_without_a_real_retriever_fails_closed() -> None:
    response = TestClient(create_test_app(_settings(context_enabled=True))).post(
        "/internal/v1/retrieval/search",
        json=_request(),
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "CONTEXT_RETRIEVER_NOT_CONNECTED",
        "message": "No production context retriever is configured",
    }

    runtime_status = TestClient(create_test_app(_settings(context_enabled=True))).get(
        "/internal/v1/runtime/status"
    )
    assert runtime_status.json()["context"] == {"enabled": True, "ready": False}


@pytest.mark.parametrize("scope_type", ["TENANT", "PROJECT"])
def test_unimplemented_memory_scopes_are_rejected(scope_type: str) -> None:
    payload = _request()
    payload["requestedSources"] = ["MEMORY"]
    payload["authorizedKnowledgeResources"] = []
    payload["allowedMemoryScopes"] = [
        {
            "tenantId": payload["tenantId"],
            "scopeType": scope_type,
            "scopeId": payload["enterpriseAgentId"],
            "enterpriseAgentId": payload["enterpriseAgentId"],
            "historyFloorSequenceNo": 0,
        }
    ]

    response = TestClient(create_test_app(_settings(context_enabled=False))).post(
        "/internal/v1/retrieval/search",
        json=payload,
    )

    assert response.status_code == 422

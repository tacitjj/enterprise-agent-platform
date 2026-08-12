from __future__ import annotations

from hashlib import sha256
import os
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.migrations import apply_migrations
from tests.internal_auth_testkit import create_test_app


TEST_DSN = os.getenv("DIANLIAN_TEST_CONTEXT_DATABASE_DSN")
pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="DIANLIAN_TEST_CONTEXT_DATABASE_DSN is not configured",
)


def _settings() -> RuntimeSettings:
    return RuntimeSettings(
        service_name="dianlian-ai-runtime",
        service_version="test",
        role="context-worker",
        context_enabled=True,
        agent_enabled=False,
        supervisor_enabled=False,
        context_database_dsn=TEST_DSN,
    )


def _index_request(
    *,
    tenant_id: str,
    projection_resource_id: str,
    source_id: str,
    source_version: str,
    event_sequence: int,
    operation: str,
) -> dict:
    content = "工商银行展览项目合同需要核对预算。"
    body = {
        "contractVersion": "1.0",
        "requestId": str(uuid4()),
        "traceId": str(uuid4()),
        "jobId": str(uuid4()),
        "leaseEpoch": 1,
        "target": "LEXICAL",
        "operation": operation,
        "authorityScope": "TENANT",
        "tenantId": tenant_id,
        "resourceType": "KNOWLEDGE_DOCUMENT_VERSION",
        "resourceId": projection_resource_id,
        "sourceId": source_id,
        "sourceVersion": source_version,
        "eventSequence": event_sequence,
        "indexProfile": "context-default-v1",
        "title": "测试知识",
        "normalizedText": content,
        "sourceContentHash": "b" * 64,
        "normalizedTextHash": sha256(content.encode("utf-8")).hexdigest(),
        "normalizationProfileVersion": "plain-text-v1",
        "citation": "测试知识 / 版本 1",
    }
    if operation == "DELETE":
        for field in (
            "title",
            "sourceId",
            "sourceVersion",
            "normalizedText",
            "sourceContentHash",
            "normalizedTextHash",
            "normalizationProfileVersion",
            "citation",
        ):
            body.pop(field)
    return body


def _retrieval_request(
    *,
    tenant_id: str,
    resource_id: str,
    resource_version: str,
) -> dict:
    return {
        "contractVersion": "1.0",
        "requestId": str(uuid4()),
        "traceId": str(uuid4()),
        "deadlineAt": "2099-01-01T00:00:00Z",
        "tenantId": tenant_id,
        "actorUserId": str(uuid4()),
        "enterpriseAgentId": str(uuid4()),
        "conversationId": str(uuid4()),
        "query": "工商银行展览项目",
        "audienceUserIds": [str(uuid4())],
        "authorizedKnowledgeResources": [
            {
                "tenantId": tenant_id,
                "resourceId": resource_id,
                "resourceVersionId": resource_version,
            }
        ],
        "allowedMemoryScopes": [],
        "requestedSources": ["KNOWLEDGE"],
        "policy": {
            "lexicalTopK": 10,
            "vectorTopK": 10,
            "rerankTopK": 10,
            "maxEvidence": 5,
            "maxContextTokens": 4000,
        },
        "authorizationSnapshotHash": "a" * 64,
    }


def _memory_index_request(
    *,
    tenant_id: str,
    resource_id: str,
    enterprise_agent_id: str,
    scope_id: str,
    event_sequence: int,
    source_message_sequence_no: int | None,
) -> dict:
    content = "群聊客户偏好蓝色的展台方案。"
    content_hash = sha256(content.encode("utf-8")).hexdigest()
    return {
        "contractVersion": "1.0",
        "requestId": str(uuid4()),
        "traceId": str(uuid4()),
        "jobId": str(uuid4()),
        "leaseEpoch": 1,
        "target": "LEXICAL",
        "operation": "UPSERT",
        "authorityScope": "TENANT",
        "tenantId": tenant_id,
        "resourceType": "MEMORY_ITEM_VERSION",
        "resourceId": resource_id,
        "sourceId": resource_id,
        "sourceVersion": "1",
        "eventSequence": event_sequence,
        "indexProfile": "context-default-v1",
        "title": "群聊记忆",
        "normalizedText": content,
        "sourceContentHash": content_hash,
        "normalizedTextHash": content_hash,
        "normalizationProfileVersion": "memory-authority-v1",
        "citation": "群聊记忆 / 版本 1",
        "memoryScope": {
            "enterpriseAgentId": enterprise_agent_id,
            "scopeType": "GROUP_AGENT",
            "scopeId": scope_id,
            "sourceMessageSequenceNo": source_message_sequence_no,
        },
    }


def _memory_retrieval_request(
    *,
    tenant_id: str,
    enterprise_agent_id: str,
    scope_id: str,
) -> dict:
    return {
        "contractVersion": "1.0",
        "requestId": str(uuid4()),
        "traceId": str(uuid4()),
        "deadlineAt": "2099-01-01T00:00:00Z",
        "tenantId": tenant_id,
        "actorUserId": str(uuid4()),
        "enterpriseAgentId": enterprise_agent_id,
        "conversationId": scope_id,
        "query": "蓝色",
        "audienceUserIds": [str(uuid4())],
        "authorizedKnowledgeResources": [],
        "allowedMemoryScopes": [
            {
                "tenantId": tenant_id,
                "scopeType": "GROUP_AGENT",
                "scopeId": scope_id,
                "enterpriseAgentId": enterprise_agent_id,
                "historyFloorSequenceNo": 10,
            }
        ],
        "requestedSources": ["MEMORY"],
        "policy": {
            "lexicalTopK": 10,
            "vectorTopK": 10,
            "rerankTopK": 10,
            "maxEvidence": 5,
            "maxContextTokens": 4000,
        },
        "authorizationSnapshotHash": "a" * 64,
    }


def test_real_postgres_exact_allowlist_and_delete_fence() -> None:
    assert TEST_DSN is not None
    apply_migrations(TEST_DSN)
    tenant_id = str(uuid4())
    source_id = str(uuid4())
    source_version = str(uuid4())
    projection_resource_id = source_version
    app = create_test_app(_settings())

    try:
        with TestClient(app) as client:
            upsert = _index_request(
                tenant_id=tenant_id,
                projection_resource_id=projection_resource_id,
                source_id=source_id,
                source_version=source_version,
                event_sequence=17,
                operation="UPSERT",
            )
            assert client.post("/internal/v1/indexing/apply", json=upsert).status_code == 200

            retrieval = client.post(
                "/internal/v1/retrieval/search",
                json=_retrieval_request(
                    tenant_id=tenant_id,
                    resource_id=source_id,
                    resource_version=source_version,
                ),
            )
            assert retrieval.status_code == 200
            assert retrieval.json()["retrievalTrace"]["strategies"] == ["LEXICAL"]
            assert retrieval.json()["knowledge"]["evidence"][0]["sourceId"] == source_id
            assert retrieval.json()["knowledge"]["evidence"][0]["sourceVersion"] == source_version

            wrong_resource = _retrieval_request(
                tenant_id=tenant_id,
                resource_id=str(uuid4()),
                resource_version=str(uuid4()),
            )
            assert client.post(
                "/internal/v1/retrieval/search",
                json=wrong_resource,
            ).json()["knowledge"]["evidence"] == []

            delete = _index_request(
                tenant_id=tenant_id,
                projection_resource_id=projection_resource_id,
                source_id=source_id,
                source_version=source_version,
                event_sequence=17,
                operation="DELETE",
            )
            assert client.post("/internal/v1/indexing/apply", json=delete).json()["result"] == "APPLIED"
            assert client.post("/internal/v1/indexing/apply", json=upsert).json()["result"] == "NOOP_STALE"
    finally:
        with psycopg.connect(TEST_DSN) as connection:
            connection.execute(
                "DELETE FROM dianlian_context.lexical_chunk WHERE resource_id = %s",
                (UUID(projection_resource_id),),
            )
            connection.execute(
                "DELETE FROM dianlian_context.projection_fence WHERE resource_id = %s",
                (UUID(projection_resource_id),),
            )


def test_real_postgres_group_memory_requires_source_sequence() -> None:
    assert TEST_DSN is not None
    apply_migrations(TEST_DSN)
    tenant_id = str(uuid4())
    resource_id = str(uuid4())
    enterprise_agent_id = str(uuid4())
    scope_id = str(uuid4())
    app = create_test_app(_settings())

    try:
        with TestClient(app) as client:
            missing_sequence = _memory_index_request(
                tenant_id=tenant_id,
                resource_id=resource_id,
                enterprise_agent_id=enterprise_agent_id,
                scope_id=scope_id,
                event_sequence=21,
                source_message_sequence_no=None,
            )
            assert client.post(
                "/internal/v1/indexing/apply",
                json=missing_sequence,
            ).status_code == 200

            retrieval_body = _memory_retrieval_request(
                tenant_id=tenant_id,
                enterprise_agent_id=enterprise_agent_id,
                scope_id=scope_id,
            )
            hidden = client.post("/internal/v1/retrieval/search", json=retrieval_body)
            assert hidden.status_code == 200
            assert hidden.json()["memory"]["evidence"] == []

            sequenced = _memory_index_request(
                tenant_id=tenant_id,
                resource_id=resource_id,
                enterprise_agent_id=enterprise_agent_id,
                scope_id=scope_id,
                event_sequence=22,
                source_message_sequence_no=12,
            )
            sequenced.pop("sourceContentHash")
            assert client.post(
                "/internal/v1/indexing/apply",
                json=sequenced,
            ).status_code == 200
            visible = client.post("/internal/v1/retrieval/search", json=retrieval_body)
            assert visible.status_code == 200
            assert visible.json()["memory"]["evidence"][0]["sourceId"] == resource_id
            assert visible.json()["memory"]["evidence"][0]["sourceVersion"] == "1"
    finally:
        with psycopg.connect(TEST_DSN) as connection:
            connection.execute(
                "DELETE FROM dianlian_context.lexical_chunk WHERE resource_id = %s",
                (UUID(resource_id),),
            )
            connection.execute(
                "DELETE FROM dianlian_context.projection_fence WHERE resource_id = %s",
                (UUID(resource_id),),
            )

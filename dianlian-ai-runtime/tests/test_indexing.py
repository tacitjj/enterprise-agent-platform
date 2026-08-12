from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from pathlib import Path

from fastapi.testclient import TestClient

from dianlian_runtime.config import RuntimeSettings
from dianlian_runtime.context.indexing import (
    FenceDecision,
    LEXICAL_V1_PROFILE,
    decide_fence_write,
    split_lexical_chunks,
)
from dianlian_runtime.context.indexing_contracts import (
    ContextIndexingReceipt,
    ContextIndexingRequest,
    IndexApplyResult,
    IndexOperation,
)
from dianlian_runtime.context.contracts import ContextEvidence
from dianlian_runtime.context.postgres import PostgresContextService
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


def _request(*, target: str = "LEXICAL", operation: str = "UPSERT") -> dict:
    content = "工商银行展览项目需要核对合同与预算。"
    body = {
        "contractVersion": "1.0",
        "requestId": "10000000-0000-0000-0000-000000000101",
        "traceId": "20000000-0000-0000-0000-000000000101",
        "jobId": "30000000-0000-0000-0000-000000000101",
        "leaseEpoch": 1,
        "target": target,
        "operation": operation,
        "authorityScope": "TENANT",
        "tenantId": "40000000-0000-0000-0000-000000000101",
        "resourceType": "KNOWLEDGE_DOCUMENT_VERSION",
        "resourceId": "50000000-0000-0000-0000-000000000101",
        "sourceId": "51000000-0000-0000-0000-000000000101",
        "sourceVersion": "60000000-0000-0000-0000-000000000101",
        "eventSequence": 11,
        "indexProfile": "context-default-v1",
        "title": "测试知识",
        "normalizedText": content,
        "sourceContentHash": "b" * 64,
        "normalizedTextHash": sha256(content.encode("utf-8")).hexdigest(),
        "normalizationProfileVersion": "plain-text-v1",
        "citation": "测试知识 / 版本 1",
        "memoryScope": None,
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
            "memoryScope",
        ):
            body.pop(field)
    return body


class ReadyIndexingService:
    @property
    def ready(self) -> bool:
        return True

    def apply(self, request: ContextIndexingRequest) -> ContextIndexingReceipt:
        return ContextIndexingReceipt(
            contractVersion="1.0",
            requestId=request.request_id,
            jobId=request.job_id,
            leaseEpoch=request.lease_epoch,
            target=request.target,
            operation=request.operation,
            result=IndexApplyResult.APPLIED,
            eventSequence=request.event_sequence,
            indexedChunkCount=1,
            indexProfile=request.index_profile,
        )


class RecordingCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[tuple[object, ...]]]] = []

    def __enter__(self) -> "RecordingCursor":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def executemany(self, statement: str, rows: list[tuple[object, ...]]) -> None:
        self.calls.append((statement, rows))


class RecordingConnection:
    def __init__(self) -> None:
        self.opened_cursor = RecordingCursor()

    def cursor(self) -> RecordingCursor:
        return self.opened_cursor


def test_indexing_contract_is_strict_and_checks_normalized_text_hash() -> None:
    body = _request()
    body["normalizedTextHash"] = "a" * 64

    response = TestClient(
        create_test_app(
            _settings(context_enabled=True),
            context_indexing_service=ReadyIndexingService(),
        )
    ).post("/internal/v1/indexing/apply", json=body)

    assert response.status_code == 422
    assert "exact normalizedText UTF-8 bytes" in response.text


def test_normalized_text_hash_uses_unmodified_utf8_bytes() -> None:
    body = _request()
    body["normalizedText"] = "  保留边界空白  "
    body["normalizedTextHash"] = sha256(body["normalizedText"].encode("utf-8")).hexdigest()

    request = ContextIndexingRequest.model_validate(body)

    assert request.normalized_text == "  保留边界空白  "


def test_indexing_title_accepts_500_characters_and_rejects_501() -> None:
    accepted = _request()
    accepted["title"] = "题" * 500
    assert len(ContextIndexingRequest.model_validate(accepted).title or "") == 500

    rejected = _request()
    rejected["title"] = "题" * 501
    response = TestClient(
        create_test_app(
            _settings(context_enabled=True),
            context_indexing_service=ReadyIndexingService(),
        )
    ).post("/internal/v1/indexing/apply", json=rejected)

    assert response.status_code == 422


def test_context_evidence_accepts_500_character_title() -> None:
    evidence = ContextEvidence(
        evidenceId="lexical:test",
        sourceType="KNOWLEDGE",
        sourceId="51000000-0000-0000-0000-000000000101",
        sourceVersion="60000000-0000-0000-0000-000000000101",
        chunkId="a" * 64,
        title="题" * 500,
        excerpt="证据正文",
        contentHash="b" * 64,
        score=1.0,
        citation="测试知识 / 版本 1",
    )

    assert len(evidence.title) == 500


def test_source_hash_accepts_java_authority_width_but_memory_may_omit_it() -> None:
    knowledge = _request()
    knowledge["sourceContentHash"] = "b" * 128
    assert ContextIndexingRequest.model_validate(knowledge).source_content_hash == "b" * 128

    memory = _request()
    memory.update(
        {
            "resourceType": "MEMORY_ITEM_VERSION",
            "sourceId": memory["resourceId"],
            "sourceVersion": "1",
            "memoryScope": {
                "enterpriseAgentId": "70000000-0000-0000-0000-000000000101",
                "scopeType": "AGENT",
                "scopeId": "80000000-0000-0000-0000-000000000101",
                "sourceMessageSequenceNo": None,
            },
            "normalizationProfileVersion": "memory-authority-v1",
        }
    )
    memory.pop("sourceContentHash")
    assert ContextIndexingRequest.model_validate(memory).source_content_hash is None


def test_delete_contract_rejects_content_fields() -> None:
    body = _request(operation="DELETE")
    body["normalizedText"] = "must not be accepted"

    response = TestClient(
        create_test_app(
            _settings(context_enabled=True),
            context_indexing_service=ReadyIndexingService(),
        )
    ).post("/internal/v1/indexing/apply", json=body)

    assert response.status_code == 422
    assert "must not include content fields" in response.text


def test_delete_needs_only_stable_projection_identity() -> None:
    request = ContextIndexingRequest.model_validate(_request(operation="DELETE"))

    assert request.source_id is None
    assert request.source_version is None


def test_vector_target_fails_with_stable_retryable_provider_error() -> None:
    response = TestClient(create_test_app(_settings(context_enabled=True))).post(
        "/internal/v1/indexing/apply",
        json=_request(target="VECTOR"),
    )

    assert response.status_code == 503
    assert response.json() == {
        "code": "INDEX_PROVIDER_NOT_CONFIGURED",
        "message": "No production embedding provider is configured",
    }


def test_disabled_lexical_indexing_fails_closed() -> None:
    response = TestClient(create_test_app(_settings(context_enabled=False))).post(
        "/internal/v1/indexing/apply",
        json=_request(),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "CONTEXT_FEATURE_DISABLED"


def test_sentence_splitter_profile_produces_deterministic_chunk_ids() -> None:
    request = ContextIndexingRequest.model_validate(_request())

    first = split_lexical_chunks(request, LEXICAL_V1_PROFILE)
    second = split_lexical_chunks(request, LEXICAL_V1_PROFILE)

    assert first
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert all(len(chunk.chunk_id) == 64 for chunk in first)


def test_chunk_batch_insert_uses_the_psycopg_cursor_api() -> None:
    request = ContextIndexingRequest.model_validate(_request())
    chunks = split_lexical_chunks(request, LEXICAL_V1_PROFILE)
    connection = RecordingConnection()

    PostgresContextService._insert_chunks(connection, 9, request, chunks)  # type: ignore[arg-type]

    assert len(connection.opened_cursor.calls) == 1
    statement, rows = connection.opened_cursor.calls[0]
    assert "INSERT INTO dianlian_context.lexical_chunk" in statement
    assert len(rows) == len(chunks)


def test_postgres_allowlist_json_keys_match_jsonb_recordset_columns() -> None:
    source = (Path(__file__).parents[1] / "src/dianlian_runtime/context/postgres.py").read_text(
        encoding="utf-8"
    )

    assert '"resource_id": str(resource.resource_id)' in source
    assert '"resource_version": str(resource.resource_version_id)' in source
    assert '"scope_type": scope.scope_type.value' in source
    assert '"scope_id": str(scope.scope_id)' in source
    assert '"history_floor": scope.history_floor_sequence_no' in source
    assert '"resourceId": str(resource.resource_id)' not in source


def test_delete_wins_at_same_sequence_and_blocks_stale_upsert() -> None:
    assert decide_fence_write(
        previous_event_sequence=11,
        previous_operation=IndexOperation.UPSERT,
        previous_payload_hash="a" * 64,
        event_sequence=11,
        operation=IndexOperation.DELETE,
        payload_hash=None,
    ) == FenceDecision.APPLY
    assert decide_fence_write(
        previous_event_sequence=11,
        previous_operation=IndexOperation.DELETE,
        previous_payload_hash=None,
        event_sequence=11,
        operation=IndexOperation.UPSERT,
        payload_hash="a" * 64,
    ) == FenceDecision.NOOP_STALE


def test_same_upsert_is_idempotent_but_different_payload_conflicts() -> None:
    assert decide_fence_write(
        previous_event_sequence=11,
        previous_operation=IndexOperation.UPSERT,
        previous_payload_hash="a" * 64,
        event_sequence=11,
        operation=IndexOperation.UPSERT,
        payload_hash="a" * 64,
    ) == FenceDecision.NOOP_IDEMPOTENT
    assert decide_fence_write(
        previous_event_sequence=11,
        previous_operation=IndexOperation.UPSERT,
        previous_payload_hash="a" * 64,
        event_sequence=11,
        operation=IndexOperation.UPSERT,
        payload_hash="b" * 64,
    ) == FenceDecision.CONFLICT


def test_memory_group_projection_accepts_missing_sequence_for_safe_storage() -> None:
    body = _request()
    body.update(
        {
            "resourceType": "MEMORY_ITEM_VERSION",
            "sourceId": body["resourceId"],
            "sourceVersion": "1",
            "memoryScope": {
                "enterpriseAgentId": "70000000-0000-0000-0000-000000000101",
                "scopeType": "GROUP_AGENT",
                "scopeId": "80000000-0000-0000-0000-000000000101",
                "sourceMessageSequenceNo": None,
            },
            "normalizationProfileVersion": "memory-authority-v1",
        }
    )

    response = TestClient(
        create_test_app(
            _settings(context_enabled=True),
            context_indexing_service=ReadyIndexingService(),
        )
    ).post("/internal/v1/indexing/apply", json=body)

    assert response.status_code == 200

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import logging
from time import perf_counter
from typing import Iterator
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from dianlian_runtime.context.contracts import (
    ContextBundle,
    ContextEvidence,
    ContextRetrievalRequest,
    ContextSourceBundle,
    ContextSourceState,
    RequestedSource,
    RetrievalTrace,
)
from dianlian_runtime.context.indexing import (
    FenceDecision,
    LexicalChunk,
    LexicalIndexProfile,
    decide_fence_write,
    projection_payload_hash,
    projection_manifest_hash,
    split_lexical_chunks,
)
from dianlian_runtime.context.indexing_contracts import (
    ChunkManifestEntry,
    ContextIndexingReceipt,
    ContextIndexingRequest,
    IndexApplyResult,
    IndexOperation,
    IndexTarget,
)
from dianlian_runtime.context.service import (
    ContextIndexingConflict,
    ContextIndexingUnavailable,
    ContextRetrievalUnavailable,
)


LOGGER = logging.getLogger(__name__)
REQUIRED_MIGRATIONS = frozenset({"000", "001", "002"})


class PostgresContextDatabase:
    def __init__(
        self,
        dsn: str,
        *,
        min_size: int,
        max_size: int,
        connect_timeout_seconds: int,
    ) -> None:
        self._connect_timeout_seconds = connect_timeout_seconds
        self._pool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=connect_timeout_seconds,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        self._ready = False

    @property
    def ready(self) -> bool:
        return self._ready

    def start(self) -> None:
        try:
            self._pool.open(
                wait=True,
                timeout=self._connect_timeout_seconds,
            )
            with self._pool.connection() as connection:
                rows = connection.execute(
                    """
                    SELECT version
                      FROM dianlian_context.schema_migration
                     WHERE version = ANY(%s)
                    """,
                    (list(REQUIRED_MIGRATIONS),),
                ).fetchall()
                applied = {row["version"] for row in rows}
                self._ready = applied == REQUIRED_MIGRATIONS
        except Exception as exception:  # readiness must fail closed without leaking DSN details
            self._ready = False
            LOGGER.warning(
                "Context database is not ready; error_type=%s",
                type(exception).__name__,
            )

    def close(self) -> None:
        self._ready = False
        self._pool.close()

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        if not self._ready:
            raise ContextRetrievalUnavailable(
                "CONTEXT_DATABASE_NOT_READY",
                "Context projection database is not ready",
            )
        with self._pool.connection() as connection:
            yield connection


class PostgresContextService:
    def __init__(
        self,
        database: PostgresContextDatabase,
        profile: LexicalIndexProfile,
    ) -> None:
        self._database = database
        self._profile = profile

    @property
    def ready(self) -> bool:
        return self._database.ready

    def start(self) -> None:
        self._database.start()

    def close(self) -> None:
        self._database.close()

    def apply(self, request: ContextIndexingRequest) -> ContextIndexingReceipt:
        if not self.ready:
            raise ContextIndexingUnavailable(
                "CONTEXT_DATABASE_NOT_READY",
                "Context projection database is not ready",
            )
        if request.target == IndexTarget.VECTOR:
            raise ContextIndexingUnavailable(
                "INDEX_PROVIDER_NOT_CONFIGURED",
                "No production embedding provider is configured",
            )
        if request.index_profile != self._profile.name:
            raise ContextIndexingConflict(
                "INDEX_PROFILE_NOT_SUPPORTED",
                "The requested index profile is not active",
            )

        chunks = split_lexical_chunks(request, self._profile)
        payload_hash = projection_payload_hash(request)
        with self._database.connection() as connection:
            result = self._apply_projection(
                connection,
                request,
                chunks,
                payload_hash,
            )
        return ContextIndexingReceipt(
            contractVersion="1.0",
            requestId=request.request_id,
            jobId=request.job_id,
            leaseEpoch=request.lease_epoch,
            target=request.target,
            operation=request.operation,
            result=result,
            eventSequence=request.event_sequence,
            indexedChunkCount=len(chunks),
            indexProfile=request.index_profile,
            resourceType=request.resource_type,
            resourceId=request.resource_id,
            sourceId=request.source_id,
            sourceVersion=request.source_version,
            projectionManifestHash=projection_manifest_hash(chunks),
            chunkManifest=[
                ChunkManifestEntry(
                    chunkId=chunk.chunk_id,
                    chunkContentHash=chunk.content_hash,
                    ordinal=chunk.ordinal,
                )
                for chunk in chunks
            ],
        )

    def retrieve(self, request: ContextRetrievalRequest) -> ContextBundle:
        if not self.ready:
            raise ContextRetrievalUnavailable(
                "CONTEXT_DATABASE_NOT_READY",
                "Context projection database is not ready",
            )
        started = perf_counter()
        knowledge_rows: list[dict] = []
        memory_rows: list[dict] = []
        with self._database.connection() as connection:
            if RequestedSource.KNOWLEDGE in request.requested_sources:
                knowledge_rows = self._retrieve_knowledge(connection, request)
            if RequestedSource.MEMORY in request.requested_sources:
                memory_rows = self._retrieve_memory(connection, request)

        selected = self._select_evidence(
            knowledge_rows,
            memory_rows,
            max_evidence=request.policy.max_evidence,
            max_context_tokens=request.policy.max_context_tokens,
        )
        knowledge_evidence = [item for source, item in selected if source == RequestedSource.KNOWLEDGE]
        memory_evidence = [item for source, item in selected if source == RequestedSource.MEMORY]
        generated_at = datetime.now(timezone.utc)
        return ContextBundle(
            contractVersion=request.contract_version,
            requestId=request.request_id,
            retrievalSnapshotId=f"pg-lexical-{uuid4()}",
            generatedAt=generated_at,
            knowledge=self._source_bundle(
                RequestedSource.KNOWLEDGE,
                request,
                knowledge_evidence,
            ),
            memory=self._source_bundle(
                RequestedSource.MEMORY,
                request,
                memory_evidence,
            ),
            retrievalTrace=RetrievalTrace(
                strategies=["LEXICAL"],
                candidateCount=len(knowledge_rows) + len(memory_rows),
                rerankedCount=0,
                indexVersion=self._profile.name,
                elapsedMs=max(0, int((perf_counter() - started) * 1000)),
            ),
        )

    def _apply_projection(
        self,
        connection: Connection,
        request: ContextIndexingRequest,
        chunks: list[LexicalChunk],
        payload_hash: str | None,
    ) -> IndexApplyResult:
        with connection.transaction():
            connection.execute(
                """
                INSERT INTO dianlian_context.projection_fence
                    (authority_scope, tenant_id, resource_type, resource_id, index_profile,
                     last_event_sequence, last_operation, last_payload_hash, updated_at)
                VALUES (%s, %s, %s, %s, %s, 0, 'DELETE', NULL, CURRENT_TIMESTAMP)
                ON CONFLICT ON CONSTRAINT uq_context_projection_fence_identity DO NOTHING
                """,
                (
                    request.authority_scope.value,
                    request.tenant_id,
                    request.resource_type.value,
                    request.resource_id,
                    request.index_profile,
                ),
            )
            fence = connection.execute(
                """
                SELECT fence_id, last_event_sequence, last_operation, last_payload_hash
                  FROM dianlian_context.projection_fence
                 WHERE authority_scope = %s
                   AND tenant_id IS NOT DISTINCT FROM %s
                   AND resource_type = %s
                   AND resource_id = %s
                   AND index_profile = %s
                   FOR UPDATE
                """,
                (
                    request.authority_scope.value,
                    request.tenant_id,
                    request.resource_type.value,
                    request.resource_id,
                    request.index_profile,
                ),
            ).fetchone()
            if fence is None:
                raise RuntimeError("projection fence was not created")
            decision = decide_fence_write(
                previous_event_sequence=fence["last_event_sequence"],
                previous_operation=IndexOperation(fence["last_operation"]),
                previous_payload_hash=fence["last_payload_hash"],
                event_sequence=request.event_sequence,
                operation=request.operation,
                payload_hash=payload_hash,
            )
            if decision == FenceDecision.NOOP_STALE:
                return IndexApplyResult.NOOP_STALE
            if decision == FenceDecision.NOOP_IDEMPOTENT:
                return IndexApplyResult.NOOP_IDEMPOTENT
            if decision == FenceDecision.CONFLICT:
                raise ContextIndexingConflict(
                    "INDEX_EVENT_CONFLICT",
                    "The same projection event has a different payload",
                )

            fence_id = fence["fence_id"]
            connection.execute(
                "DELETE FROM dianlian_context.lexical_chunk WHERE fence_id = %s",
                (fence_id,),
            )
            if request.operation == IndexOperation.UPSERT:
                self._insert_chunks(connection, fence_id, request, chunks)
            connection.execute(
                """
                UPDATE dianlian_context.projection_fence
                   SET last_event_sequence = %s,
                       last_operation = %s,
                       last_payload_hash = %s,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE fence_id = %s
                """,
                (
                    request.event_sequence,
                    request.operation.value,
                    payload_hash,
                    fence_id,
                ),
            )
            return IndexApplyResult.APPLIED

    @staticmethod
    def _insert_chunks(
        connection: Connection,
        fence_id: int,
        request: ContextIndexingRequest,
        chunks: list[LexicalChunk],
    ) -> None:
        memory_scope = request.memory_scope
        rows = [
            (
                chunk.chunk_id,
                fence_id,
                request.authority_scope.value,
                request.tenant_id,
                request.resource_type.value,
                request.resource_id,
                request.source_id,
                request.source_version,
                request.index_profile,
                request.event_sequence,
                chunk.ordinal,
                request.title,
                chunk.content,
                request.source_content_hash,
                request.normalized_text_hash,
                request.normalization_profile_version,
                request.citation,
                None if memory_scope is None else memory_scope.enterprise_agent_id,
                None if memory_scope is None else memory_scope.scope_type.value,
                None if memory_scope is None else memory_scope.scope_id,
                None if memory_scope is None else memory_scope.source_message_sequence_no,
            )
            for chunk in chunks
        ]
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO dianlian_context.lexical_chunk
                    (chunk_id, fence_id, authority_scope, tenant_id, resource_type,
                     resource_id, source_id, source_version, index_profile, event_sequence,
                     chunk_ordinal, title, content, source_content_hash, normalized_text_hash,
                     normalization_profile_version, citation,
                     enterprise_agent_id, memory_scope_type, memory_scope_id,
                     source_message_sequence_no)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )

    def _retrieve_knowledge(
        self,
        connection: Connection,
        request: ContextRetrievalRequest,
    ) -> list[dict]:
        allowlist = json.dumps(
            [
                {
                    "resource_id": str(resource.resource_id),
                    "resource_version": str(resource.resource_version_id),
                }
                for resource in request.authorized_knowledge_resources
            ],
            separators=(",", ":"),
        )
        return connection.execute(
            """
            WITH allowed AS (
                SELECT resource_id, resource_version
                  FROM jsonb_to_recordset(%s::jsonb)
                       AS item(resource_id UUID, resource_version TEXT)
            ), query_input AS (
                SELECT websearch_to_tsquery('simple', %s) AS query
            )
            SELECT chunk.chunk_id,
                   chunk.source_id,
                   chunk.source_version,
                   chunk.title,
                   chunk.content,
                   chunk.citation,
                   LEAST(
                       1.0,
                       CASE
                           WHEN POSITION(LOWER(%s) IN LOWER(chunk.content)) > 0 THEN 1.0
                           ELSE ts_rank_cd(chunk.search_document, query_input.query)
                                / (1.0 + ts_rank_cd(chunk.search_document, query_input.query))
                       END
                   )::DOUBLE PRECISION AS score
              FROM allowed
              JOIN dianlian_context.lexical_chunk chunk
                ON chunk.source_id = allowed.resource_id
               AND chunk.source_version = allowed.resource_version
              JOIN dianlian_context.projection_fence fence
                ON fence.fence_id = chunk.fence_id
               AND fence.last_operation = 'UPSERT'
               AND fence.last_event_sequence = chunk.event_sequence
              CROSS JOIN query_input
             WHERE chunk.resource_type = 'KNOWLEDGE_DOCUMENT_VERSION'
               AND chunk.index_profile = %s
               AND (
                    (chunk.authority_scope = 'TENANT' AND chunk.tenant_id = %s)
                    OR chunk.authority_scope = 'PLATFORM'
               )
               AND (
                    chunk.search_document @@ query_input.query
                    OR POSITION(LOWER(%s) IN LOWER(chunk.content)) > 0
               )
             ORDER BY score DESC, chunk.chunk_id
             LIMIT %s
            """,
            (
                allowlist,
                request.query,
                request.query,
                self._profile.name,
                request.tenant_id,
                request.query,
                request.policy.lexical_top_k,
            ),
        ).fetchall()

    def _retrieve_memory(
        self,
        connection: Connection,
        request: ContextRetrievalRequest,
    ) -> list[dict]:
        scopes = json.dumps(
            [
                {
                    "scope_type": scope.scope_type.value,
                    "scope_id": str(scope.scope_id),
                    "history_floor": scope.history_floor_sequence_no,
                }
                for scope in request.allowed_memory_scopes
            ],
            separators=(",", ":"),
        )
        return connection.execute(
            """
            WITH allowed AS (
                SELECT scope_type, scope_id, history_floor
                  FROM jsonb_to_recordset(%s::jsonb)
                       AS item(scope_type TEXT, scope_id UUID, history_floor BIGINT)
            ), query_input AS (
                SELECT websearch_to_tsquery('simple', %s) AS query
            )
            SELECT chunk.chunk_id,
                   chunk.source_id,
                   chunk.source_version,
                   chunk.title,
                   chunk.content,
                   chunk.citation,
                   LEAST(
                       1.0,
                       CASE
                           WHEN POSITION(LOWER(%s) IN LOWER(chunk.content)) > 0 THEN 1.0
                           ELSE ts_rank_cd(chunk.search_document, query_input.query)
                                / (1.0 + ts_rank_cd(chunk.search_document, query_input.query))
                       END
                   )::DOUBLE PRECISION AS score
              FROM allowed
              JOIN dianlian_context.lexical_chunk chunk
                ON chunk.memory_scope_type = allowed.scope_type
               AND chunk.memory_scope_id = allowed.scope_id
              JOIN dianlian_context.projection_fence fence
                ON fence.fence_id = chunk.fence_id
               AND fence.last_operation = 'UPSERT'
               AND fence.last_event_sequence = chunk.event_sequence
              CROSS JOIN query_input
             WHERE chunk.resource_type = 'MEMORY_ITEM_VERSION'
               AND chunk.authority_scope = 'TENANT'
               AND chunk.tenant_id = %s
               AND chunk.enterprise_agent_id = %s
               AND chunk.index_profile = %s
               AND (
                    (chunk.memory_scope_type = 'GROUP_AGENT'
                        AND chunk.source_message_sequence_no IS NOT NULL
                        AND chunk.source_message_sequence_no >= allowed.history_floor)
                    OR
                    (chunk.memory_scope_type <> 'GROUP_AGENT'
                        AND (
                            (chunk.source_message_sequence_no IS NULL AND allowed.history_floor = 0)
                            OR chunk.source_message_sequence_no >= allowed.history_floor
                        ))
               )
               AND (
                    chunk.search_document @@ query_input.query
                    OR POSITION(LOWER(%s) IN LOWER(chunk.content)) > 0
               )
             ORDER BY score DESC, chunk.chunk_id
             LIMIT %s
            """,
            (
                scopes,
                request.query,
                request.query,
                request.tenant_id,
                request.enterprise_agent_id,
                self._profile.name,
                request.query,
                request.policy.lexical_top_k,
            ),
        ).fetchall()

    @staticmethod
    def _to_evidence(source: RequestedSource, row: dict) -> ContextEvidence:
        excerpt = row["content"]
        return ContextEvidence(
            evidenceId=f"lexical:{row['chunk_id']}",
            sourceType=source,
            sourceId=row["source_id"],
            sourceVersion=row["source_version"],
            chunkId=row["chunk_id"],
            title=row["title"],
            excerpt=excerpt,
            contentHash=sha256(excerpt.encode("utf-8")).hexdigest(),
            score=float(row["score"]),
            citation=row["citation"],
        )

    def _select_evidence(
        self,
        knowledge_rows: list[dict],
        memory_rows: list[dict],
        *,
        max_evidence: int,
        max_context_tokens: int,
    ) -> list[tuple[RequestedSource, ContextEvidence]]:
        candidates = [
            (RequestedSource.KNOWLEDGE, self._to_evidence(RequestedSource.KNOWLEDGE, row))
            for row in knowledge_rows
        ] + [
            (RequestedSource.MEMORY, self._to_evidence(RequestedSource.MEMORY, row))
            for row in memory_rows
        ]
        candidates.sort(key=lambda item: (-item[1].score, item[1].chunk_id))
        selected: list[tuple[RequestedSource, ContextEvidence]] = []
        remaining_bytes = max_context_tokens
        for source, evidence in candidates:
            if len(selected) >= max_evidence:
                break
            fixed_bytes = len((evidence.title + evidence.citation).encode("utf-8"))
            if fixed_bytes >= remaining_bytes:
                continue
            excerpt_bytes = len(evidence.excerpt.encode("utf-8"))
            if fixed_bytes + excerpt_bytes > remaining_bytes:
                continue
            selected.append((source, evidence))
            remaining_bytes -= fixed_bytes + excerpt_bytes
        return selected

    @staticmethod
    def _source_bundle(
        source: RequestedSource,
        request: ContextRetrievalRequest,
        evidence: list[ContextEvidence],
    ) -> ContextSourceBundle:
        if source not in request.requested_sources:
            return ContextSourceBundle(
                state=ContextSourceState.EMPTY,
                reasonCode="SOURCE_NOT_REQUESTED",
                evidence=[],
            )
        if evidence:
            return ContextSourceBundle(
                state=ContextSourceState.READY,
                evidence=evidence,
            )
        reason = (
            "KNOWLEDGE_NO_AUTHORIZED_EVIDENCE"
            if source == RequestedSource.KNOWLEDGE
            else "MEMORY_NO_CONFIRMED_EVIDENCE"
        )
        return ContextSourceBundle(
            state=ContextSourceState.EMPTY,
            reasonCode=reason,
            evidence=[],
        )


def _truncate_utf8(value: str, maximum_bytes: int) -> str:
    if maximum_bytes <= 0:
        return ""
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return value
    return encoded[:maximum_bytes].decode("utf-8", errors="ignore").strip()

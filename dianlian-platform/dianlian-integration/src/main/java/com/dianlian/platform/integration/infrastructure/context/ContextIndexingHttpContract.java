package com.dianlian.platform.integration.infrastructure.context;

import com.dianlian.platform.context.api.ContextIndexDispatch;
import com.dianlian.platform.context.api.ContextIndexDispatch.ClaimedProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.IndexOperation;
import com.dianlian.platform.context.api.ContextIndexDispatch.IndexTarget;
import com.dianlian.platform.context.api.ContextIndexDispatch.KnowledgeDocumentProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.MemoryItemProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.TombstoneProjection;
import com.fasterxml.jackson.annotation.JsonInclude;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Objects;
import java.util.UUID;

final class ContextIndexingHttpContract {

    static final String MEMORY_NORMALIZATION_PROFILE = "memory-authority-v1";
    private static final int MAX_NORMALIZED_TEXT_LENGTH = 2_000_000;

    private ContextIndexingHttpContract() {
    }

    static ContextIndexingRequest request(
            ClaimedProjection projection,
            UUID requestId,
            UUID traceId
    ) {
        Objects.requireNonNull(projection, "projection must not be null");
        Objects.requireNonNull(requestId, "requestId must not be null");
        Objects.requireNonNull(traceId, "traceId must not be null");
        var lease = projection.lease();
        var payload = projection.payload();
        if (payload.indexTarget() != IndexTarget.LEXICAL
                || !ContextIndexDispatch.DEFAULT_INDEX_PROFILE_VERSION.equals(payload.indexProfileVersion())) {
            throw new IllegalArgumentException("only the V1 lexical context profile can be dispatched");
        }
        if (payload.operation() == IndexOperation.VERIFY) {
            throw new IllegalArgumentException("VERIFY is not supported by the runtime indexing contract");
        }

        var base = new ContextIndexingRequest(
                ContextIndexDispatch.PROJECTION_CONTRACT_VERSION,
                requestId,
                traceId,
                payload.jobId(),
                lease.leaseEpoch(),
                payload.indexTarget().name(),
                payload.operation().name(),
                payload.authorityScope().name(),
                payload.tenantId(),
                payload.resourceType().name(),
                payload.resourceId(),
                null,
                null,
                payload.eventSequence(),
                payload.indexProfileVersion(),
                null,
                null,
                null,
                null,
                null,
                null,
                null
        );
        if (payload.operation() == IndexOperation.DELETE) {
            if (!(payload.body() instanceof TombstoneProjection)) {
                throw new IllegalArgumentException("DELETE projection requires a tombstone body");
            }
            return base;
        }
        if (payload.body() instanceof KnowledgeDocumentProjection knowledge) {
            requireRuntimeTextLength(knowledge.normalizedText());
            return base.withContent(
                    knowledge.documentId(),
                    knowledge.documentVersionId().toString(),
                    knowledge.title(),
                    knowledge.normalizedText(),
                    knowledge.sourceContentHash(),
                    knowledge.normalizedTextHash(),
                    knowledge.normalizationProfileVersion(),
                    citation(knowledge.title(), knowledge.documentVersionId().toString()),
                    null
            );
        }
        if (payload.body() instanceof MemoryItemProjection memory) {
            requireRuntimeTextLength(memory.content());
            String contentHash = sha256(memory.content());
            String title = memory.semanticKey() == null ? "数字员工长期记忆" : memory.semanticKey();
            return base.withContent(
                    memory.memoryId(),
                    Long.toString(memory.versionNo()),
                    title,
                    memory.content(),
                    contentHash,
                    contentHash,
                    MEMORY_NORMALIZATION_PROFILE,
                    citation(title, "版本 " + memory.versionNo()),
                    new MemoryProjectionScope(
                            memory.enterpriseAgentId(),
                            memory.scopeType().name(),
                            memory.scopeId(),
                            memory.sourceMessageSequenceNo()
                    )
            );
        }
        throw new IllegalArgumentException("unsupported context projection body");
    }

    private static void requireRuntimeTextLength(String value) {
        if (value.length() > MAX_NORMALIZED_TEXT_LENGTH) {
            throw new IllegalArgumentException("normalized context text exceeds the runtime contract limit");
        }
    }

    private static String citation(String title, String version) {
        return title + " / " + version;
    }

    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is required", exception);
        }
    }

    @JsonInclude(JsonInclude.Include.NON_NULL)
    record ContextIndexingRequest(
            String contractVersion,
            UUID requestId,
            UUID traceId,
            UUID jobId,
            long leaseEpoch,
            String target,
            String operation,
            String authorityScope,
            UUID tenantId,
            String resourceType,
            UUID resourceId,
            UUID sourceId,
            String sourceVersion,
            long eventSequence,
            String indexProfile,
            String title,
            String normalizedText,
            String sourceContentHash,
            String normalizedTextHash,
            String normalizationProfileVersion,
            String citation,
            MemoryProjectionScope memoryScope
    ) {

        ContextIndexingRequest withContent(
                UUID sourceId,
                String sourceVersion,
                String title,
                String normalizedText,
                String sourceContentHash,
                String normalizedTextHash,
                String normalizationProfileVersion,
                String citation,
                MemoryProjectionScope memoryScope
        ) {
            return new ContextIndexingRequest(
                    contractVersion,
                    requestId,
                    traceId,
                    jobId,
                    leaseEpoch,
                    target,
                    operation,
                    authorityScope,
                    tenantId,
                    resourceType,
                    resourceId,
                    sourceId,
                    sourceVersion,
                    eventSequence,
                    indexProfile,
                    title,
                    normalizedText,
                    sourceContentHash,
                    normalizedTextHash,
                    normalizationProfileVersion,
                    citation,
                    memoryScope
            );
        }
    }

    record MemoryProjectionScope(
            UUID enterpriseAgentId,
            String scopeType,
            UUID scopeId,
            Long sourceMessageSequenceNo
    ) {
    }

    record ContextIndexingReceipt(
            String contractVersion,
            UUID requestId,
            UUID jobId,
            long leaseEpoch,
            String target,
            String operation,
            String result,
            long eventSequence,
            int indexedChunkCount,
            String indexProfile
    ) {
    }
}

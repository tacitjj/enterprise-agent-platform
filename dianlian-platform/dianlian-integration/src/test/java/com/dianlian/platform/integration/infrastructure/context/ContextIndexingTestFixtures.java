package com.dianlian.platform.integration.infrastructure.context;

import com.dianlian.platform.context.api.ContextIndexDispatch;
import com.dianlian.platform.context.api.ContextIndexDispatch.AuthorityScope;
import com.dianlian.platform.context.api.ContextIndexDispatch.ClaimedProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.ContextIndexLease;
import com.dianlian.platform.context.api.ContextIndexDispatch.IndexOperation;
import com.dianlian.platform.context.api.ContextIndexDispatch.IndexTarget;
import com.dianlian.platform.context.api.ContextIndexDispatch.KnowledgeDocumentProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.MemoryItemProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.MemoryScopeType;
import com.dianlian.platform.context.api.ContextIndexDispatch.ProjectionBody;
import com.dianlian.platform.context.api.ContextIndexDispatch.ProjectionPayload;
import com.dianlian.platform.context.api.ContextIndexDispatch.ResourceType;
import com.dianlian.platform.context.api.ContextIndexDispatch.TombstoneProjection;
import com.dianlian.platform.context.api.ContextIndexDispatch.TombstoneReason;
import java.time.Instant;
import java.util.UUID;

final class ContextIndexingTestFixtures {

    static final UUID TENANT_ID = UUID.fromString("51000000-0000-4000-8000-000000000001");
    static final UUID JOB_ID = UUID.fromString("51000000-0000-4000-8000-000000000002");
    static final UUID DOCUMENT_VERSION_ID = UUID.fromString("51000000-0000-4000-8000-000000000003");
    static final UUID DOCUMENT_ID = UUID.fromString("51000000-0000-4000-8000-000000000004");
    static final UUID SPACE_ID = UUID.fromString("51000000-0000-4000-8000-000000000005");
    static final UUID MEMORY_ID = UUID.fromString("51000000-0000-4000-8000-000000000006");
    static final UUID AGENT_ID = UUID.fromString("51000000-0000-4000-8000-000000000007");
    static final UUID SCOPE_ID = UUID.fromString("51000000-0000-4000-8000-000000000008");
    static final UUID REQUEST_ID = UUID.fromString("51000000-0000-4000-8000-000000000009");
    static final UUID TRACE_ID = UUID.fromString("51000000-0000-4000-8000-000000000010");
    static final long EVENT_SEQUENCE = 41;
    static final long LEASE_EPOCH = 3;

    private ContextIndexingTestFixtures() {
    }

    static ClaimedProjection knowledgeProjection() {
        return projection(
                ResourceType.KNOWLEDGE_DOCUMENT_VERSION,
                DOCUMENT_VERSION_ID,
                2,
                IndexOperation.UPSERT,
                new KnowledgeDocumentProjection(
                        DOCUMENT_VERSION_ID,
                        DOCUMENT_ID,
                        SPACE_ID,
                        "展会执行规范",
                        "tenant/knowledge.pdf",
                        "a".repeat(64),
                        "权威规范化正文",
                        "b".repeat(64),
                        "knowledge-normalize-v2",
                        Instant.parse("2026-08-12T04:00:00Z"),
                        "application/pdf",
                        1024,
                        "{}"
                )
        );
    }

    static ClaimedProjection memoryProjection() {
        return projection(
                ResourceType.MEMORY_ITEM_VERSION,
                MEMORY_ID,
                4,
                IndexOperation.UPSERT,
                new MemoryItemProjection(
                        MEMORY_ID,
                        4,
                        AGENT_ID,
                        MemoryScopeType.GROUP_AGENT,
                        SCOPE_ID,
                        "客户偏好蓝色主视觉",
                        "visual.preference",
                        19L
                )
        );
    }

    static ClaimedProjection deleteProjection() {
        return projection(
                ResourceType.KNOWLEDGE_DOCUMENT_VERSION,
                DOCUMENT_VERSION_ID,
                2,
                IndexOperation.DELETE,
                new TombstoneProjection(TombstoneReason.REQUESTED_DELETE)
        );
    }

    private static ClaimedProjection projection(
            ResourceType resourceType,
            UUID resourceId,
            long resourceVersion,
            IndexOperation operation,
            ProjectionBody body
    ) {
        var payload = new ProjectionPayload(
                ContextIndexDispatch.PROJECTION_CONTRACT_VERSION,
                JOB_ID,
                TENANT_ID,
                AuthorityScope.TENANT,
                resourceType,
                resourceId,
                resourceVersion,
                EVENT_SEQUENCE,
                IndexTarget.LEXICAL,
                ContextIndexDispatch.DEFAULT_INDEX_PROFILE_VERSION,
                operation,
                operation,
                body
        );
        var lease = new ContextIndexLease(
                JOB_ID,
                "context-worker-test",
                2,
                LEASE_EPOCH,
                EVENT_SEQUENCE,
                Instant.parse("2026-08-12T04:02:00Z")
        );
        return new ClaimedProjection(lease, payload);
    }
}

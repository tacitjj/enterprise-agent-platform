package com.dianlian.platform.context.application;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScope;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AuthorizedKnowledgeResource;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RetrievalPolicy;
import com.dianlian.platform.context.api.ContextAuthorityPort.InvocationBoundary;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;

final class AuthorizationSnapshotHasher {

    private AuthorizationSnapshotHasher() {
    }

    static String hash(
            InvocationBoundary invocation,
            List<AuthorizedKnowledgeResource> knowledge,
            List<AllowedMemoryScope> memory,
            List<RequestedSource> sources,
            RetrievalPolicy policy
    ) {
        var canonical = new StringBuilder("context-authority-v1\n")
                .append(invocation.tenantId()).append('\n')
                .append(invocation.actorUserId()).append('\n')
                .append(invocation.enterpriseAgentId()).append('\n')
                .append(invocation.agentVersionId()).append('\n')
                .append(invocation.configurationVersionId()).append('\n')
                .append(invocation.conversationId()).append('\n')
                .append(invocation.groupConversation()).append('\n')
                .append(invocation.sourceMessageId()).append('\n')
                .append(invocation.sourceSequenceNo()).append('\n')
                .append(invocation.membershipVersion()).append('\n')
                .append(invocation.policyVersion()).append('\n')
                .append(invocation.historyFloorSequenceNo()).append('\n');
        invocation.audienceUserIds().stream().sorted().forEach(id -> canonical.append("aud:").append(id).append('\n'));
        knowledge.stream()
                .sorted(java.util.Comparator.comparing(AuthorizedKnowledgeResource::resourceId)
                        .thenComparing(AuthorizedKnowledgeResource::resourceVersionId))
                .forEach(item -> canonical.append("knowledge:").append(item.resourceId()).append(':')
                        .append(item.resourceVersionId()).append('\n'));
        memory.stream()
                .sorted(java.util.Comparator.comparing((AllowedMemoryScope scope) -> scope.scopeType().name())
                        .thenComparing(AllowedMemoryScope::scopeId)
                        .thenComparingLong(AllowedMemoryScope::historyFloorSequenceNo))
                .forEach(scope -> canonical.append("memory:").append(scope.scopeType()).append(':')
                        .append(scope.scopeId()).append(':').append(scope.historyFloorSequenceNo()).append('\n'));
        sources.stream().sorted().forEach(source -> canonical.append("source:").append(source).append('\n'));
        canonical.append("policy:")
                .append(policy.lexicalTopK()).append(':').append(policy.vectorTopK()).append(':')
                .append(policy.rerankTopK()).append(':').append(policy.maxEvidence()).append(':')
                .append(policy.maxContextTokens());
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(canonical.toString().getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is required", exception);
        }
    }
}

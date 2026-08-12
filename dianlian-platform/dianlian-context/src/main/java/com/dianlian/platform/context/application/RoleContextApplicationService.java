package com.dianlian.platform.context.application;

import com.dianlian.platform.context.api.AgentContextAssembler;
import com.dianlian.platform.context.api.AgentContextBundle;
import com.dianlian.platform.context.api.AgentContextRequest;
import com.dianlian.platform.context.api.ContextEvidence;
import com.dianlian.platform.context.api.ContextSourceResult;
import com.dianlian.platform.context.api.ContextSourceState;
import com.dianlian.platform.context.api.KnowledgeContextRequest;
import com.dianlian.platform.context.api.KnowledgeContextSource;
import com.dianlian.platform.context.api.MemoryContextRequest;
import com.dianlian.platform.context.api.MemoryContextSource;
import com.dianlian.platform.context.api.MemoryScopeRef;
import com.dianlian.platform.context.api.MemoryScopeType;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import org.springframework.stereotype.Service;

@Service
public class RoleContextApplicationService implements AgentContextAssembler {

    private final List<KnowledgeContextSource> knowledgeSources;
    private final List<MemoryContextSource> memorySources;

    public RoleContextApplicationService(
            List<KnowledgeContextSource> knowledgeSources,
            List<MemoryContextSource> memorySources
    ) {
        this.knowledgeSources = List.copyOf(Objects.requireNonNull(knowledgeSources, "knowledgeSources must not be null"));
        this.memorySources = List.copyOf(Objects.requireNonNull(memorySources, "memorySources must not be null"));
    }

    @Override
    public AgentContextBundle assemble(AgentContextRequest request) {
        Objects.requireNonNull(request, "request must not be null");
        var memoryScopes = memoryScopes(request);
        var knowledge = retrieveKnowledge(request);
        var memory = recallMemory(request, memoryScopes);
        var blockers = new ArrayList<String>();
        if (request.enterpriseKnowledgeRequired() && knowledge.state() != ContextSourceState.READY) {
            blockers.add("REQUIRED_ENTERPRISE_KNOWLEDGE_UNAVAILABLE");
        }
        if (request.longTermMemoryRequired() && memory.state() != ContextSourceState.READY) {
            blockers.add("REQUIRED_LONG_TERM_MEMORY_UNAVAILABLE");
        }

        return new AgentContextBundle(
                request.agentVersionId(),
                request.configurationVersionId(),
                renderSystemInstruction(request, knowledge, memory),
                request.recentMessages(),
                knowledge,
                memory,
                memoryScopes,
                blockers
        );
    }

    private ContextSourceResult retrieveKnowledge(AgentContextRequest request) {
        if (!request.enterpriseKnowledgeEnabled()) {
            return ContextSourceResult.empty("ENTERPRISE_KNOWLEDGE_NOT_CONFIGURED");
        }
        if (knowledgeSources.isEmpty()) {
            return ContextSourceResult.unavailable("KNOWLEDGE_SERVICE_NOT_CONNECTED");
        }
        return merge(knowledgeSources.stream()
                .map(source -> source.retrieve(new KnowledgeContextRequest(
                        request.tenantId(),
                        request.enterpriseAgentId(),
                        request.conversationId(),
                        request.audienceUserIds(),
                        request.userQuery()
                )))
                .toList(), "KNOWLEDGE_NO_AUTHORIZED_EVIDENCE");
    }

    private ContextSourceResult recallMemory(AgentContextRequest request, List<MemoryScopeRef> scopes) {
        if (memorySources.isEmpty()) {
            return ContextSourceResult.unavailable("MEMORY_SERVICE_NOT_CONNECTED");
        }
        return merge(memorySources.stream()
                .map(source -> source.recall(new MemoryContextRequest(
                        request.tenantId(),
                        request.actorUserId(),
                        request.enterpriseAgentId(),
                        request.conversationId(),
                        request.groupConversation(),
                        request.historyFloorSequenceNo(),
                        request.audienceUserIds(),
                        scopes,
                        request.userQuery()
                )))
                .toList(), "MEMORY_NO_CONFIRMED_EVIDENCE");
    }

    private static List<MemoryScopeRef> memoryScopes(AgentContextRequest request) {
        var scopes = new ArrayList<MemoryScopeRef>();
        scopes.add(new MemoryScopeRef(
                request.tenantId(),
                MemoryScopeType.AGENT,
                request.enterpriseAgentId(),
                request.enterpriseAgentId()
        ));
        scopes.add(new MemoryScopeRef(
                request.tenantId(),
                request.groupConversation() ? MemoryScopeType.GROUP_AGENT : MemoryScopeType.USER_AGENT,
                request.groupConversation() ? request.conversationId() : request.actorUserId(),
                request.enterpriseAgentId()
        ));
        return List.copyOf(scopes);
    }

    private static ContextSourceResult merge(List<ContextSourceResult> results, String emptyReason) {
        var evidence = results.stream()
                .filter(result -> result.state() == ContextSourceState.READY)
                .flatMap(result -> result.evidence().stream())
                .distinct()
                .toList();
        if (!evidence.isEmpty()) {
            return new ContextSourceResult(ContextSourceState.READY, evidence, null);
        }
        if (results.stream().anyMatch(result -> result.state() == ContextSourceState.FORBIDDEN)) {
            return new ContextSourceResult(ContextSourceState.FORBIDDEN, List.of(), "CONTEXT_ACCESS_FORBIDDEN");
        }
        if (results.stream().anyMatch(result -> result.state() == ContextSourceState.UNAVAILABLE)) {
            return ContextSourceResult.unavailable("CONTEXT_SOURCE_UNAVAILABLE");
        }
        return ContextSourceResult.empty(emptyReason);
    }

    static String renderSystemInstruction(
            AgentContextRequest request,
            ContextSourceResult knowledge,
            ContextSourceResult memory
    ) {
        var builder = new StringBuilder();
        builder.append("你是企业中的数字员工“").append(request.roleName()).append("”。\n")
                .append("【平台岗位配置｜版本 ").append(request.agentVersionId()).append("】\n")
                .append(request.platformProfile()).append("\n")
                .append("【企业员工配置｜版本 ").append(request.configurationVersionId()).append("】\n")
                .append(request.enterpriseInstructions()).append("\n")
                .append("【工作边界】\n")
                .append("只使用本次明确提供的授权证据与会话事实；证据不足时应说明缺口并追问。")
                .append("不得声称读取了未提供的企业知识或长期记忆，不输出隐藏推理过程。\n");
        appendEvidence(builder, "企业知识", knowledge);
        appendEvidence(builder, "已确认记忆", memory);
        return builder.toString();
    }

    private static void appendEvidence(StringBuilder builder, String label, ContextSourceResult source) {
        builder.append("【").append(label).append("｜").append(source.state()).append("】\n");
        if (source.state() != ContextSourceState.READY) {
            builder.append("当前无可用证据，原因：").append(source.reasonCode()).append("。\n");
            return;
        }
        for (ContextEvidence evidence : source.evidence()) {
            builder.append("- ").append(evidence.title()).append("：")
                    .append(evidence.excerpt()).append("（来源版本 ")
                    .append(evidence.sourceVersion()).append("）\n");
        }
    }
}

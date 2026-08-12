package com.dianlian.platform.context.application;

import static org.assertj.core.api.Assertions.assertThat;

import com.dianlian.platform.context.api.AgentContextRequest;
import com.dianlian.platform.context.api.ContextSourceResult;
import com.dianlian.platform.context.api.MemoryContextRequest;
import com.dianlian.platform.context.api.MemoryContextSource;
import com.dianlian.platform.context.api.MemoryScopeType;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class RoleContextApplicationServiceTests {

    private static final UUID TENANT_ID = UUID.fromString("00000000-0000-0000-0000-000000000001");
    private static final UUID USER_ID = UUID.fromString("00000000-0000-0000-0000-000000000011");
    private static final UUID AGENT_ID = UUID.fromString("00000000-0000-0000-0000-000000000121");
    private static final UUID CONVERSATION_ID = UUID.fromString("00000000-0000-0000-0000-000000000201");

    @Test
    void directConversationUsesAgentAndUserAgentMemoryOnly() {
        var memory = new RecordingMemorySource();
        var service = new RoleContextApplicationService(List.of(), List.of(memory));

        var bundle = service.assemble(request(false, false));

        assertThat(bundle.memoryScopes()).extracting(scope -> scope.scopeType())
                .containsExactly(MemoryScopeType.AGENT, MemoryScopeType.USER_AGENT);
        assertThat(bundle.memoryScopes().get(1).scopeId()).isEqualTo(USER_ID);
        assertThat(memory.lastRequest.allowedScopes()).isEqualTo(bundle.memoryScopes());
        assertThat(memory.lastRequest.audienceUserIds()).containsExactly(USER_ID);
        assertThat(memory.lastRequest.historyFloorSequenceNo()).isEqualTo(7);
        assertThat(bundle.systemInstruction())
                .contains("平台岗位配置", "企业员工配置", "MEMORY_NO_CONFIRMED_EVIDENCE")
                .doesNotContain("GROUP_AGENT");
    }

    @Test
    void groupConversationNeverIncludesPrivateUserAgentMemory() {
        var memory = new RecordingMemorySource();
        var service = new RoleContextApplicationService(List.of(), List.of(memory));

        var bundle = service.assemble(request(true, false));

        assertThat(bundle.memoryScopes()).extracting(scope -> scope.scopeType())
                .containsExactly(MemoryScopeType.AGENT, MemoryScopeType.GROUP_AGENT)
                .doesNotContain(MemoryScopeType.USER_AGENT);
        assertThat(bundle.memoryScopes().get(1).scopeId()).isEqualTo(CONVERSATION_ID);
    }

    @Test
    void requiredKnowledgeBlocksInvocationWhenNoKnowledgeSourceIsConnected() {
        var service = new RoleContextApplicationService(List.of(), List.of(new RecordingMemorySource()));

        var bundle = service.assemble(request(false, true));

        assertThat(bundle.ready()).isFalse();
        assertThat(bundle.blockers()).containsExactly("REQUIRED_ENTERPRISE_KNOWLEDGE_UNAVAILABLE");
        assertThat(bundle.knowledge().reasonCode()).isEqualTo("KNOWLEDGE_SERVICE_NOT_CONNECTED");
    }

    private static AgentContextRequest request(boolean group, boolean knowledgeRequired) {
        return new AgentContextRequest(
                TENANT_ID,
                USER_ID,
                AGENT_ID,
                CONVERSATION_ID,
                group,
                UUID.fromString("00000000-0000-0000-0000-000000000301"),
                UUID.fromString("00000000-0000-0000-0000-000000000302"),
                "法务合同审核",
                "遵循平台发布的岗位职责。",
                "使用本企业确认的法务红线。",
                "请审核这份合同",
                7,
                List.of(USER_ID),
                List.of(),
                knowledgeRequired,
                knowledgeRequired,
                false
        );
    }

    private static final class RecordingMemorySource implements MemoryContextSource {
        private MemoryContextRequest lastRequest;

        @Override
        public ContextSourceResult recall(MemoryContextRequest request) {
            lastRequest = request;
            return ContextSourceResult.empty("MEMORY_NO_CONFIRMED_EVIDENCE");
        }
    }
}

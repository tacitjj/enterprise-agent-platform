package com.dianlian.platform.context.api;

import static com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScopeType.AGENT;
import static com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScopeType.USER_AGENT;
import static com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource.KNOWLEDGE;
import static com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource.MEMORY;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScope;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AllowedMemoryScopeType;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.AuthorizedKnowledgeResource;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextBundle;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextEvidence;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextRetrievalRequest;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextSourceBundle;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.ContextSourceState;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RequestedSource;
import com.dianlian.platform.context.api.AuthorizedContextRetrievalContract.RetrievalPolicy;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.exc.InvalidFormatException;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class AuthorizedContextRetrievalContractTests {

    private static final UUID TENANT_ID = UUID.fromString("00000000-0000-0000-0000-000000000001");
    private static final UUID USER_ID = UUID.fromString("00000000-0000-0000-0000-000000000011");
    private static final UUID AGENT_ID = UUID.fromString("00000000-0000-0000-0000-000000000121");
    private static final UUID CONVERSATION_ID = UUID.fromString("00000000-0000-0000-0000-000000000201");

    private final ObjectMapper objectMapper = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);

    @Test
    void sharedRequestAndResponseFixturesMatchTheJavaContract() throws IOException {
        var request = objectMapper.readValue(
                fixture("context-retrieval-v1-request.json").toFile(),
                ContextRetrievalRequest.class
        );
        var response = objectMapper.readValue(
                fixture("context-retrieval-v1-response.json").toFile(),
                ContextBundle.class
        );

        assertThat(request.contractVersion()).isEqualTo(AuthorizedContextRetrievalContract.B0_CONTRACT_VERSION);
        assertThat(request.requestedSources()).containsExactly(KNOWLEDGE, MEMORY);
        assertThat(request.allowedMemoryScopes()).extracting(AllowedMemoryScope::scopeType)
                .containsExactly(AGENT, USER_AGENT);
        assertThat(response.requestId()).isEqualTo(request.requestId());
        assertThat(response.knowledge().state()).isEqualTo(ContextSourceState.READY);
        assertThat(response.knowledge().evidence()).hasSize(1);
        assertThat(response.memory().state()).isEqualTo(ContextSourceState.EMPTY);
    }

    @Test
    void b0ContractExposesOnlyTheThreeAuthorizedMemoryScopes() {
        assertThat(AllowedMemoryScopeType.values())
                .containsExactly(AGENT, USER_AGENT, AllowedMemoryScopeType.GROUP_AGENT);
    }

    @Test
    void rejectsFutureMemoryScopeNamesAtTheJsonBoundary() throws IOException {
        var root = objectMapper.readTree(fixture("context-retrieval-v1-request.json").toFile());
        ((ObjectNode) root.path("allowedMemoryScopes").get(0)).put("scopeType", "TENANT");

        assertThatThrownBy(() -> objectMapper.treeToValue(root, ContextRetrievalRequest.class))
                .isInstanceOf(InvalidFormatException.class)
                .hasMessageContaining("TENANT");
    }

    @Test
    void requestedSourcesRequireExplicitMatchingAllowlists() {
        assertThatThrownBy(() -> request(List.of(), validMemoryScopes(), List.of(KNOWLEDGE, MEMORY)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("resource allowlist");
        assertThatThrownBy(() -> request(validResources(), List.of(), List.of(KNOWLEDGE, MEMORY)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("scope allowlist");
    }

    @Test
    void nestedAuthorizationMustMatchTheTopLevelTenantAndAgent() {
        var foreignResource = new AuthorizedKnowledgeResource(UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID());
        assertThatThrownBy(() -> request(List.of(foreignResource), validMemoryScopes(), List.of(KNOWLEDGE)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("resource tenant");

        var foreignAgentScope = new AllowedMemoryScope(
                TENANT_ID,
                USER_AGENT,
                USER_ID,
                UUID.randomUUID(),
                0
        );
        assertThatThrownBy(() -> request(validResources(), List.of(foreignAgentScope), List.of(MEMORY)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("scope agent");
    }

    @Test
    void sourceStateCannotClaimReadinessWithoutEvidence() {
        assertThatThrownBy(() -> new ContextSourceBundle(ContextSourceState.READY, null, List.of()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("must include evidence");
        assertThatThrownBy(() -> new ContextSourceBundle(ContextSourceState.EMPTY, null, List.of()))
                .isInstanceOf(NullPointerException.class)
                .hasMessageContaining("reasonCode");
    }

    @Test
    void evidenceTitleLimitMatchesTheRuntimeContract() {
        var accepted = new ContextEvidence(
                "evidence-1",
                KNOWLEDGE,
                UUID.randomUUID(),
                "version-1",
                "chunk-1",
                "a".repeat(500),
                "authorized excerpt",
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                0.9,
                "document / chunk-1"
        );

        assertThat(accepted.title()).hasSize(500);
        assertThatThrownBy(() -> new ContextEvidence(
                "evidence-1",
                KNOWLEDGE,
                UUID.randomUUID(),
                "version-1",
                "chunk-1",
                "a".repeat(501),
                "authorized excerpt",
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                0.9,
                "document / chunk-1"
        )).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("title");
    }

    private static ContextRetrievalRequest request(
            List<AuthorizedKnowledgeResource> resources,
            List<AllowedMemoryScope> scopes,
            List<RequestedSource> sources
    ) {
        return new ContextRetrievalRequest(
                "1.0",
                UUID.randomUUID(),
                UUID.randomUUID(),
                Instant.parse("2099-01-01T00:00:00Z"),
                TENANT_ID,
                USER_ID,
                AGENT_ID,
                CONVERSATION_ID,
                "test query",
                List.of(USER_ID),
                resources,
                scopes,
                sources,
                new RetrievalPolicy(20, 20, 20, 8, 4_096),
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        );
    }

    private static List<AuthorizedKnowledgeResource> validResources() {
        return List.of(new AuthorizedKnowledgeResource(TENANT_ID, UUID.randomUUID(), UUID.randomUUID()));
    }

    private static List<AllowedMemoryScope> validMemoryScopes() {
        return List.of(new AllowedMemoryScope(TENANT_ID, AGENT, AGENT_ID, AGENT_ID, 0));
    }

    private static Path fixture(String fileName) {
        Path cursor = Path.of("").toAbsolutePath();
        while (cursor != null) {
            Path candidate = cursor.resolve("contracts/fixtures/context").resolve(fileName);
            if (Files.isRegularFile(candidate)) {
                return candidate;
            }
            cursor = cursor.getParent();
        }
        throw new IllegalStateException("shared context fixture not found: " + fileName);
    }
}

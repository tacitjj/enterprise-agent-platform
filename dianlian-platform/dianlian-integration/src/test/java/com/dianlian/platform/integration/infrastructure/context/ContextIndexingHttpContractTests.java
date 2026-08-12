package com.dianlian.platform.integration.infrastructure.context;

import static com.dianlian.platform.integration.infrastructure.context.ContextIndexingTestFixtures.DOCUMENT_ID;
import static com.dianlian.platform.integration.infrastructure.context.ContextIndexingTestFixtures.DOCUMENT_VERSION_ID;
import static com.dianlian.platform.integration.infrastructure.context.ContextIndexingTestFixtures.MEMORY_ID;
import static com.dianlian.platform.integration.infrastructure.context.ContextIndexingTestFixtures.REQUEST_ID;
import static com.dianlian.platform.integration.infrastructure.context.ContextIndexingTestFixtures.TRACE_ID;
import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import org.junit.jupiter.api.Test;

class ContextIndexingHttpContractTests {

    @Test
    void mapsKnowledgeProjectionIdentitySeparatelyFromCitationSourceIdentity() {
        var request = ContextIndexingHttpContract.request(
                ContextIndexingTestFixtures.knowledgeProjection(), REQUEST_ID, TRACE_ID);

        assertThat(request.resourceId()).isEqualTo(DOCUMENT_VERSION_ID);
        assertThat(request.sourceId()).isEqualTo(DOCUMENT_ID);
        assertThat(request.sourceVersion()).isEqualTo(DOCUMENT_VERSION_ID.toString());
        assertThat(request.sourceContentHash()).isEqualTo("a".repeat(64));
        assertThat(request.normalizedTextHash()).isEqualTo("b".repeat(64));
        assertThat(request.normalizationProfileVersion()).isEqualTo("knowledge-normalize-v2");
        assertThat(request.memoryScope()).isNull();
    }

    @Test
    void mapsMemoryContentHashProfileAndScopeFromAuthorityProjection() {
        var request = ContextIndexingHttpContract.request(
                ContextIndexingTestFixtures.memoryProjection(), REQUEST_ID, TRACE_ID);
        String expectedHash = sha256("客户偏好蓝色主视觉");

        assertThat(request.resourceId()).isEqualTo(MEMORY_ID);
        assertThat(request.sourceId()).isEqualTo(MEMORY_ID);
        assertThat(request.sourceVersion()).isEqualTo("4");
        assertThat(request.sourceContentHash()).isEqualTo(expectedHash);
        assertThat(request.normalizedTextHash()).isEqualTo(expectedHash);
        assertThat(request.normalizationProfileVersion())
                .isEqualTo(ContextIndexingHttpContract.MEMORY_NORMALIZATION_PROFILE);
        assertThat(request.memoryScope().scopeType()).isEqualTo("GROUP_AGENT");
        assertThat(request.memoryScope().sourceMessageSequenceNo()).isEqualTo(19L);
    }

    @Test
    void deleteJsonOmitsEveryContentAndSourceField() throws Exception {
        var request = ContextIndexingHttpContract.request(
                ContextIndexingTestFixtures.deleteProjection(), REQUEST_ID, TRACE_ID);
        var json = new ObjectMapper().valueToTree(request);

        assertThat(json.get("operation").asText()).isEqualTo("DELETE");
        assertThat(json.has("resourceId")).isTrue();
        assertThat(json.has("sourceId")).isFalse();
        assertThat(json.has("sourceVersion")).isFalse();
        assertThat(json.has("title")).isFalse();
        assertThat(json.has("normalizedText")).isFalse();
        assertThat(json.has("sourceContentHash")).isFalse();
        assertThat(json.has("normalizedTextHash")).isFalse();
        assertThat(json.has("normalizationProfileVersion")).isFalse();
        assertThat(json.has("citation")).isFalse();
        assertThat(json.has("memoryScope")).isFalse();
    }

    private static String sha256(String value) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException(exception);
        }
    }
}

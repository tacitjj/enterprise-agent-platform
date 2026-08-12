package com.dianlian.platform.model.infrastructure;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.ModelChatMessage;
import com.dianlian.platform.model.api.ModelChatRequest;
import com.dianlian.platform.model.api.ModelDefinitionStatus;
import com.dianlian.platform.model.api.ModelDefinitionView;
import com.dianlian.platform.model.api.ModelProviderUnavailableException;
import com.dianlian.platform.model.api.ResolvedModelRoute;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.Test;

class LangChain4jModelGatewayTests {

    @Test
    void validatesEndpointBeforeResolvingCredential() {
        var endpointChecked = new AtomicBoolean();
        var credentialResolver = new EnvironmentCredentialResolver() {
            @Override
            String resolve(String credentialRef) {
                throw new AssertionError("credential must not be resolved for a rejected endpoint");
            }
        };
        var gateway = new LangChain4jModelGateway(credentialResolver, baseUrl -> {
            endpointChecked.set(true);
            throw new IllegalArgumentException("rejected");
        });

        assertThatThrownBy(() -> gateway.chat(route(), new ModelChatRequest(
                UUID.randomUUID(),
                "Answer briefly",
                List.of(new ModelChatMessage(ModelChatMessage.Role.HUMAN, "Hello"))
        )))
                .isInstanceOf(ModelProviderUnavailableException.class)
                .extracting(exception -> ((ModelProviderUnavailableException) exception).code())
                .isEqualTo("MODEL_PROVIDER_CALL_FAILED");
        assertThat(endpointChecked).isTrue();
    }

    @Test
    void rejectsNonDedicatedCredentialReferenceBeforeEnvironmentLookup() {
        var resolver = new EnvironmentCredentialResolver();

        assertThatThrownBy(() -> resolver.resolve("env:DIANLIAN_JWT_SECRET"))
                .isInstanceOf(ModelProviderUnavailableException.class)
                .extracting(exception -> ((ModelProviderUnavailableException) exception).code())
                .isEqualTo("MODEL_CREDENTIAL_REFERENCE_REJECTED");
    }

    private static ResolvedModelRoute route() {
        var actorId = UUID.randomUUID();
        return new ResolvedModelRoute(
                UUID.randomUUID(),
                1,
                "AGENT",
                new ModelDefinitionView(
                        UUID.randomUUID(),
                        "TEXT_MODEL",
                        1,
                        "Text model",
                        "PROVIDER",
                        "OPENAI_COMPATIBLE",
                        "https://api.example.com/v1",
                        "provider-model",
                        "env:DIANLIAN_MODEL_PROVIDER_KEY",
                        ModelCapabilityType.TEXT_CHAT,
                        new BigDecimal("0.2"),
                        2_048,
                        1,
                        1,
                        10,
                        ModelDefinitionStatus.ACTIVE,
                        actorId,
                        Instant.parse("2026-08-11T00:00:00Z")
                )
        );
    }
}

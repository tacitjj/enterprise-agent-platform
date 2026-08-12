package com.dianlian.platform.model.api;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;
import org.junit.jupiter.api.Test;

class ModelCredentialReferenceTests {

    @Test
    void acceptsOnlyDedicatedModelEnvironmentReferences() {
        assertThat(command("env:DIANLIAN_MODEL_PROVIDER_KEY").credentialRef())
                .isEqualTo("env:DIANLIAN_MODEL_PROVIDER_KEY");
        assertThatThrownBy(() -> command("env:DIANLIAN_JWT_SECRET"))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> command("env:OTHER_PROVIDER_KEY"))
                .isInstanceOf(IllegalArgumentException.class);
    }

    private static RegisterModelDefinitionCommand command(String credentialRef) {
        return new RegisterModelDefinitionCommand(
                "TEXT_MODEL",
                "Text model",
                "PROVIDER",
                "OPENAI_COMPATIBLE",
                "https://api.example.com/v1",
                "provider-model",
                credentialRef,
                ModelCapabilityType.TEXT_CHAT,
                new BigDecimal("0.2"),
                2_048,
                1,
                1,
                10,
                "idem-1",
                "request-hash"
        );
    }
}

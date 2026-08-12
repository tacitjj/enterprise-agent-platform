package com.dianlian.platform.model.api;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record ModelDefinitionView(
        UUID modelDefinitionId,
        String modelCode,
        long configurationVersion,
        String displayName,
        String providerCode,
        String protocol,
        String baseUrl,
        String providerModelName,
        String credentialRef,
        ModelCapabilityType capabilityType,
        BigDecimal temperature,
        int maxOutputTokens,
        long inputRateMicroCreditPerMillionTokens,
        long outputRateMicroCreditPerMillionTokens,
        long reservationCeilingMicroCredit,
        ModelDefinitionStatus status,
        UUID createdBy,
        Instant createdAt
) {
    public ModelDefinitionView {
        Objects.requireNonNull(modelDefinitionId, "modelDefinitionId must not be null");
        modelCode = ModelValueChecks.code(modelCode, "modelCode", 64);
        if (configurationVersion < 1) throw new IllegalArgumentException("configurationVersion must be positive");
        displayName = ModelValueChecks.text(displayName, "displayName", 100);
        providerCode = ModelValueChecks.code(providerCode, "providerCode", 64);
        protocol = ModelValueChecks.code(protocol, "protocol", 64);
        baseUrl = ModelValueChecks.url(baseUrl, "baseUrl");
        providerModelName = ModelValueChecks.text(providerModelName, "providerModelName", 100);
        credentialRef = ModelValueChecks.credentialRef(credentialRef);
        Objects.requireNonNull(capabilityType, "capabilityType must not be null");
        Objects.requireNonNull(temperature, "temperature must not be null");
        if (temperature.compareTo(BigDecimal.ZERO) < 0 || temperature.compareTo(new BigDecimal("2.0")) > 0) {
            throw new IllegalArgumentException("temperature is out of range");
        }
        if (maxOutputTokens < 1 || maxOutputTokens > 131_072) {
            throw new IllegalArgumentException("maxOutputTokens is out of range");
        }
        if (inputRateMicroCreditPerMillionTokens < 0
                || outputRateMicroCreditPerMillionTokens < 0
                || reservationCeilingMicroCredit < 1) {
            throw new IllegalArgumentException("model rates are invalid");
        }
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(createdBy, "createdBy must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }
}

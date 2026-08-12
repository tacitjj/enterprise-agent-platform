package com.dianlian.platform.model.infrastructure.mapper;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.ModelDefinitionStatus;
import com.dianlian.platform.model.api.ModelDefinitionView;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

@TableName(value = "model_definition", schema = "dianlian_business")
public class ModelDefinitionReadRow {

    @TableId("model_definition_id")
    private String modelDefinitionId;
    private String modelCode;
    private Long configurationVersion;
    private String displayName;
    private String providerCode;
    private String protocol;
    private String baseUrl;
    private String providerModelName;
    private String credentialRef;
    private String capabilityType;
    private BigDecimal temperature;
    private Integer maxOutputTokens;
    private Long inputRateMicroCreditPerMillionTokens;
    private Long outputRateMicroCreditPerMillionTokens;
    private Long reservationCeilingMicroCredit;
    private String status;
    private String createdBy;
    private Instant createdAt;

    public ModelDefinitionView toView() {
        return new ModelDefinitionView(
                UUID.fromString(modelDefinitionId),
                modelCode,
                configurationVersion,
                displayName,
                providerCode,
                protocol,
                baseUrl,
                providerModelName,
                credentialRef,
                ModelCapabilityType.valueOf(capabilityType),
                temperature,
                maxOutputTokens,
                inputRateMicroCreditPerMillionTokens,
                outputRateMicroCreditPerMillionTokens,
                reservationCeilingMicroCredit,
                ModelDefinitionStatus.valueOf(status),
                UUID.fromString(createdBy),
                createdAt
        );
    }

    public void setModelDefinitionId(String modelDefinitionId) {
        this.modelDefinitionId = modelDefinitionId;
    }

    public void setModelCode(String modelCode) {
        this.modelCode = modelCode;
    }

    public void setConfigurationVersion(Long configurationVersion) {
        this.configurationVersion = configurationVersion;
    }

    public void setDisplayName(String displayName) {
        this.displayName = displayName;
    }

    public void setProviderCode(String providerCode) {
        this.providerCode = providerCode;
    }

    public void setProtocol(String protocol) {
        this.protocol = protocol;
    }

    public void setBaseUrl(String baseUrl) {
        this.baseUrl = baseUrl;
    }

    public void setProviderModelName(String providerModelName) {
        this.providerModelName = providerModelName;
    }

    public void setCredentialRef(String credentialRef) {
        this.credentialRef = credentialRef;
    }

    public void setCapabilityType(String capabilityType) {
        this.capabilityType = capabilityType;
    }

    public void setTemperature(BigDecimal temperature) {
        this.temperature = temperature;
    }

    public void setMaxOutputTokens(Integer maxOutputTokens) {
        this.maxOutputTokens = maxOutputTokens;
    }

    public void setInputRateMicroCreditPerMillionTokens(Long value) {
        this.inputRateMicroCreditPerMillionTokens = value;
    }

    public void setOutputRateMicroCreditPerMillionTokens(Long value) {
        this.outputRateMicroCreditPerMillionTokens = value;
    }

    public void setReservationCeilingMicroCredit(Long reservationCeilingMicroCredit) {
        this.reservationCeilingMicroCredit = reservationCeilingMicroCredit;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public void setCreatedBy(String createdBy) {
        this.createdBy = createdBy;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }
}

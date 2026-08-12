package com.dianlian.platform.employee.domain;

import java.time.Instant;
import java.util.Objects;
import java.util.UUID;

public record AgentTemplate(
        UUID templateId,
        String templateCode,
        AgentTemplateStatus status,
        UUID createdBy,
        Instant createdAt
) {

    public AgentTemplate {
        Objects.requireNonNull(templateId, "templateId must not be null");
        Objects.requireNonNull(templateCode, "templateCode must not be null");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(createdBy, "createdBy must not be null");
        Objects.requireNonNull(createdAt, "createdAt must not be null");
    }

    public static AgentTemplate active(
            UUID templateId,
            String templateCode,
            UUID createdBy,
            Instant createdAt
    ) {
        return new AgentTemplate(
                templateId,
                templateCode,
                AgentTemplateStatus.ACTIVE,
                createdBy,
                createdAt
        );
    }
}

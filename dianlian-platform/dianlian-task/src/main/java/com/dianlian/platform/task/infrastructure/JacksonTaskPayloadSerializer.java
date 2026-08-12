package com.dianlian.platform.task.infrastructure;

import com.dianlian.platform.task.api.CreateTaskCommand;
import com.dianlian.platform.task.application.HashedTaskRequest;
import com.dianlian.platform.task.application.TaskPayloadSerializer;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Component;

@Component
public class JacksonTaskPayloadSerializer implements TaskPayloadSerializer {

    private final ObjectMapper objectMapper;

    public JacksonTaskPayloadSerializer(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper.copy()
                .configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true);
    }

    @Override
    public HashedTaskRequest hash(CreateTaskCommand command) {
        var payload = new LinkedHashMap<String, Object>();
        payload.put("sourceConversationId", command.sourceConversationId());
        payload.put("sourceMessageId", command.sourceMessageId());
        payload.put("expectedMembershipVersion", command.expectedMembershipVersion());
        payload.put("goal", command.goal());
        payload.put("constraints", command.constraints());
        payload.put("inputRefs", command.inputRefs());
        payload.put("collaborationMode", command.collaborationMode());
        payload.put("targetAgentIds", command.targetAgentIds());
        payload.put("primaryAgentId", command.primaryAgentId());
        payload.put("ownership", command.ownership());
        payload.put("maxPointCost", command.maxPointCost());
        payload.put("capabilityInput", command.capabilityInput());
        payload.put("desiredArtifactType", command.desiredArtifactType());
        var canonicalJson = serialize(payload);
        return new HashedTaskRequest(sha256(canonicalJson), canonicalJson);
    }

    @Override
    public String serialize(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("Task payload cannot be serialized", exception);
        }
    }

    @Override
    public List<UUID> readUuidList(String json) {
        try {
            return List.copyOf(objectMapper.readValue(json, new TypeReference<List<UUID>>() {
            }));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Persisted task UUID list is invalid", exception);
        }
    }

    private String sha256(String value) {
        try {
            var digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(value.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }
}

package com.dianlian.platform.task.api;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.regex.Pattern;

public record CreateTaskCommand(
        String idempotencyKey,
        UUID sourceConversationId,
        UUID sourceMessageId,
        String expectedMembershipVersion,
        String goal,
        List<String> constraints,
        List<InputReference> inputRefs,
        CollaborationMode collaborationMode,
        List<UUID> targetAgentIds,
        UUID primaryAgentId,
        TaskOwnership ownership,
        long maxPointCost,
        CapabilityInput capabilityInput,
        String desiredArtifactType
) {

    private static final Pattern IDEMPOTENCY_KEY =
            Pattern.compile("^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$");

    public CreateTaskCommand {
        idempotencyKey = requireText(idempotencyKey, "idempotencyKey", 128);
        if (!IDEMPOTENCY_KEY.matcher(idempotencyKey).matches()) {
            throw new IllegalArgumentException("idempotencyKey does not match the public API contract");
        }
        if (sourceMessageId != null && sourceConversationId == null) {
            throw new IllegalArgumentException("sourceConversationId is required when sourceMessageId is present");
        }
        expectedMembershipVersion = optionalText(expectedMembershipVersion, "expectedMembershipVersion", 128);
        goal = requireText(goal, "goal", 5000);
        constraints = copyTextList(constraints, "constraints", 100, 1000);
        inputRefs = List.copyOf(Objects.requireNonNull(inputRefs, "inputRefs must not be null"));
        if (inputRefs.size() > 100) {
            throw new IllegalArgumentException("inputRefs must contain at most 100 items");
        }
        Objects.requireNonNull(collaborationMode, "collaborationMode must not be null");
        targetAgentIds = List.copyOf(Objects.requireNonNull(targetAgentIds, "targetAgentIds must not be null"));
        if (targetAgentIds.isEmpty() || targetAgentIds.size() > 20) {
            throw new IllegalArgumentException("targetAgentIds must contain 1 to 20 items");
        }
        if (new LinkedHashSet<>(targetAgentIds).size() != targetAgentIds.size()) {
            throw new IllegalArgumentException("targetAgentIds must be unique");
        }
        if (targetAgentIds.stream().anyMatch(Objects::isNull)) {
            throw new IllegalArgumentException("targetAgentIds must not contain null");
        }
        validateCollaboration(collaborationMode, targetAgentIds, primaryAgentId);
        Objects.requireNonNull(ownership, "ownership must not be null");
        if (maxPointCost < 1) {
            throw new IllegalArgumentException("maxPointCost must be positive");
        }
        Objects.requireNonNull(capabilityInput, "capabilityInput must not be null");
        desiredArtifactType = optionalText(desiredArtifactType, "desiredArtifactType", 64);
    }

    private static void validateCollaboration(
            CollaborationMode collaborationMode,
            List<UUID> targetAgentIds,
            UUID primaryAgentId
    ) {
        switch (collaborationMode) {
            case SINGLE_TARGET -> {
                if (targetAgentIds.size() != 1 || primaryAgentId != null) {
                    throw new IllegalArgumentException("SINGLE_TARGET requires exactly one target and no primary agent");
                }
            }
            case PARALLEL_SEPARATE -> {
                if (targetAgentIds.size() < 2 || primaryAgentId != null) {
                    throw new IllegalArgumentException("PARALLEL_SEPARATE requires multiple targets and no primary agent");
                }
            }
            case PRIMARY_SUMMARY -> {
                if (targetAgentIds.size() < 2 || primaryAgentId == null || !targetAgentIds.contains(primaryAgentId)) {
                    throw new IllegalArgumentException("PRIMARY_SUMMARY requires a primary agent among multiple targets");
                }
            }
        }
    }

    private static List<String> copyTextList(List<String> values, String name, int maxItems, int maxLength) {
        values = List.copyOf(Objects.requireNonNull(values, name + " must not be null"));
        if (values.size() > maxItems) {
            throw new IllegalArgumentException(name + " must contain at most " + maxItems + " items");
        }
        return values.stream().map(value -> requireText(value, name + " item", maxLength)).toList();
    }

    private static String optionalText(String value, String name, int maxLength) {
        return value == null ? null : requireText(value, name, maxLength);
    }

    private static String requireText(String value, String name, int maxLength) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank() || value.length() > maxLength) {
            throw new IllegalArgumentException(name + " must contain 1 to " + maxLength + " characters");
        }
        return value;
    }
}

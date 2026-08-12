package com.dianlian.platform.interaction.infrastructure.web;

import com.dianlian.platform.billing.api.PointValues;
import com.dianlian.platform.identity.api.AccessContextPort;
import com.dianlian.platform.interaction.api.ConversationCollaborationMode;
import com.dianlian.platform.interaction.api.ConversationCommands;
import com.dianlian.platform.interaction.api.ConversationMessagePage;
import com.dianlian.platform.interaction.api.ConversationMessageView;
import com.dianlian.platform.interaction.api.ConversationQuery;
import com.dianlian.platform.interaction.api.ConversationSummary;
import com.dianlian.platform.interaction.api.ConversationType;
import com.dianlian.platform.interaction.api.CreateConversationCommand;
import com.dianlian.platform.interaction.api.MessageTargetInput;
import com.dianlian.platform.interaction.api.MessageTriggerType;
import com.dianlian.platform.interaction.api.SendConversationMessageCommand;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.net.URI;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import java.util.regex.Pattern;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@Validated
@RequestMapping("/api/v1/conversations")
public class ConversationController {

    private static final Pattern IDEMPOTENCY_KEY = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$");

    private final ConversationCommands commands;
    private final ConversationQuery query;
    private final AccessContextPort accessContextPort;
    private final ObjectMapper objectMapper;

    public ConversationController(
            ConversationCommands commands,
            ConversationQuery query,
            AccessContextPort accessContextPort,
            ObjectMapper objectMapper
    ) {
        this.commands = commands;
        this.query = query;
        this.accessContextPort = accessContextPort;
        this.objectMapper = objectMapper;
    }

    @GetMapping
    List<ConversationSummary> list() {
        return query.list(accessContextPort.requireCurrent());
    }

    @PostMapping
    ResponseEntity<ConversationCommandResponse<ConversationSummary>> create(
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @Valid @RequestBody CreateConversationRequest request
    ) {
        String normalizedKey = requireIdempotencyKey(idempotencyKey);
        var outcome = commands.create(
                request.toCommand(normalizedKey, requestHash(request)),
                accessContextPort.requireCurrent()
        );
        return ResponseEntity.status(outcome.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .location(URI.create("/api/v1/conversations/" + outcome.resource().conversationId()))
                .header("Idempotency-Replayed", Boolean.toString(outcome.replayed()))
                .body(new ConversationCommandResponse<>(outcome.resource(), outcome.queuedInvocationIds()));
    }

    @GetMapping("/{conversationId}/messages")
    ConversationMessagePageResponse messages(
            @PathVariable UUID conversationId,
            @RequestParam(defaultValue = "0") long afterSequenceNo,
            @RequestParam(defaultValue = "50") int limit
    ) {
        return ConversationMessagePageResponse.from(query.messages(
                conversationId, afterSequenceNo, limit, accessContextPort.requireCurrent()));
    }

    @PostMapping("/{conversationId}/messages")
    ResponseEntity<ConversationCommandResponse<ConversationMessageResponse>> send(
            @PathVariable UUID conversationId,
            @RequestHeader("Idempotency-Key") String idempotencyKey,
            @Valid @RequestBody SendConversationMessageRequest request
    ) {
        String normalizedKey = requireIdempotencyKey(idempotencyKey);
        var outcome = commands.send(
                request.toCommand(
                        conversationId,
                        normalizedKey,
                        requestHash(new ScopedSendRequest(conversationId, request))
                ),
                accessContextPort.requireCurrent()
        );
        return ResponseEntity.status(outcome.replayed() ? HttpStatus.OK : HttpStatus.ACCEPTED)
                .header("Idempotency-Replayed", Boolean.toString(outcome.replayed()))
                .body(new ConversationCommandResponse<>(
                        ConversationMessageResponse.from(outcome.resource()),
                        outcome.queuedInvocationIds()
                ));
    }

    private String requestHash(Object value) {
        try {
            byte[] bytes = objectMapper.writeValueAsBytes(value);
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("request cannot be serialized", exception);
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is required", exception);
        }
    }

    private static String requireIdempotencyKey(String value) {
        if (value == null || !IDEMPOTENCY_KEY.matcher(value).matches()) {
            throw new IllegalArgumentException("Idempotency-Key must match the public contract");
        }
        return value.trim();
    }

    public record CreateConversationRequest(
            @NotNull ConversationType type,
            @NotBlank @Size(max = 200) String title,
            @NotNull @Size(max = 200) List<UUID> participantUserIds,
            @NotNull @Size(max = 20) List<UUID> enterpriseAgentIds
    ) {
        CreateConversationCommand toCommand(String idempotencyKey, String requestHash) {
            return new CreateConversationCommand(
                    type, title, participantUserIds, enterpriseAgentIds, idempotencyKey, requestHash);
        }
    }

    public record SendConversationMessageRequest(
            @NotBlank @Size(max = 160) String clientMessageId,
            @NotBlank @Size(max = 20_000) String text,
            @NotNull @Size(max = 20) List<@Valid MessageTargetRequest> targets,
            @NotNull ConversationCollaborationMode collaborationMode,
            UUID primaryAgentId,
            UUID replyToMessageId,
            long expectedMembershipVersion
    ) {
        SendConversationMessageCommand toCommand(
                UUID conversationId,
                String idempotencyKey,
                String requestHash
        ) {
            return new SendConversationMessageCommand(
                    conversationId,
                    clientMessageId,
                    text,
                    targets.stream().map(MessageTargetRequest::toInput).toList(),
                    collaborationMode,
                    primaryAgentId,
                    replyToMessageId,
                    expectedMembershipVersion,
                    idempotencyKey,
                    requestHash
            );
        }
    }

    public record MessageTargetRequest(
            @NotNull UUID enterpriseAgentId,
            @NotNull MessageTriggerType triggerType,
            UUID replyToMessageId
    ) {
        MessageTargetInput toInput() {
            return new MessageTargetInput(enterpriseAgentId, triggerType, replyToMessageId);
        }
    }

    public record ConversationCommandResponse<T>(T resource, List<UUID> queuedInvocationIds) {
    }

    public record ConversationMessagePageResponse(
            List<ConversationMessageResponse> items,
            long upToSequenceNo,
            boolean hasMore,
            long membershipVersion
    ) {
        static ConversationMessagePageResponse from(ConversationMessagePage source) {
            return new ConversationMessagePageResponse(
                    source.items().stream().map(ConversationMessageResponse::from).toList(),
                    source.upToSequenceNo(),
                    source.hasMore(),
                    source.membershipVersion()
            );
        }
    }

    public record ConversationMessageResponse(
            UUID messageId,
            UUID conversationId,
            long sequenceNo,
            String senderType,
            UUID senderUserId,
            UUID senderAgentId,
            String senderDisplayName,
            String senderAvatarUrl,
            String text,
            UUID replyToMessageId,
            List<UUID> targetAgentIds,
            String aiStatus,
            String knowledgeState,
            String memoryState,
            String chargedPoints,
            java.time.Instant createdAt
    ) {
        static ConversationMessageResponse from(ConversationMessageView source) {
            return new ConversationMessageResponse(
                    source.messageId(), source.conversationId(), source.sequenceNo(),
                    source.senderType().name(), source.senderUserId(), source.senderAgentId(),
                    source.senderDisplayName(), source.senderAvatarUrl(), source.text(),
                    source.replyToMessageId(), source.targetAgentIds(), source.aiStatus(),
                    source.knowledgeState() == null ? null : source.knowledgeState().name(),
                    source.memoryState() == null ? null : source.memoryState().name(),
                    PointValues.formatDisplayValue(source.chargedMicroCredit()),
                    source.createdAt()
            );
        }
    }

    private record ScopedSendRequest(UUID conversationId, SendConversationMessageRequest request) {
    }
}

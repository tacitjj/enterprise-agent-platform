package com.dianlian.platform.task.infrastructure.web;

import com.dianlian.platform.billing.api.PointValues;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.AccessContextPort;
import com.dianlian.platform.identity.api.ActorContextPort;
import com.dianlian.platform.task.api.BillingScopeType;
import com.dianlian.platform.task.api.CapabilityInput;
import com.dianlian.platform.task.api.CollaborationMode;
import com.dianlian.platform.task.api.CreateTaskCommand;
import com.dianlian.platform.task.api.CreateTaskUseCase;
import com.dianlian.platform.task.api.InputReference;
import com.dianlian.platform.task.api.InputReferenceType;
import com.dianlian.platform.task.api.TaskAdmissionRejectedException;
import com.dianlian.platform.task.api.TaskAllowedAction;
import com.dianlian.platform.task.api.TaskCommandAccepted;
import com.dianlian.platform.task.api.TaskOwnership;
import com.dianlian.platform.task.api.TaskPointSummary;
import com.dianlian.platform.task.api.TaskSnapshot;
import com.dianlian.platform.task.api.TaskSnapshotQuery;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectWriter;
import com.fasterxml.jackson.databind.SerializationFeature;
import java.net.URI;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.regex.Pattern;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/v1/tasks")
public class TaskController {

    private static final String IDEMPOTENCY_HEADER = "Idempotency-Key";
    private static final String PRIVATE_REVALIDATE = "private, no-cache, must-revalidate";
    private static final String SSE_NO_STORE = "no-store, no-transform";
    private static final Pattern EVENT_ID_PATTERN = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$");

    private final AccessContextPort accessContextPort;
    private final ActorContextPort actorContextPort;
    private final CreateTaskUseCase createTaskUseCase;
    private final TaskSnapshotQuery taskSnapshotQuery;
    private final TaskEventSsePublisher taskEventSsePublisher;
    private final ObjectWriter etagWriter;

    public TaskController(
            AccessContextPort accessContextPort,
            ActorContextPort actorContextPort,
            CreateTaskUseCase createTaskUseCase,
            TaskSnapshotQuery taskSnapshotQuery,
            TaskEventSsePublisher taskEventSsePublisher,
            ObjectMapper objectMapper
    ) {
        this.accessContextPort = Objects.requireNonNull(accessContextPort, "accessContextPort must not be null");
        this.actorContextPort = Objects.requireNonNull(actorContextPort, "actorContextPort must not be null");
        this.createTaskUseCase = Objects.requireNonNull(createTaskUseCase, "createTaskUseCase must not be null");
        this.taskSnapshotQuery = Objects.requireNonNull(taskSnapshotQuery, "taskSnapshotQuery must not be null");
        this.taskEventSsePublisher = Objects.requireNonNull(
                taskEventSsePublisher,
                "taskEventSsePublisher must not be null"
        );
        this.etagWriter = Objects.requireNonNull(objectMapper, "objectMapper must not be null")
                .writer()
                .with(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
    }

    @PostMapping
    ResponseEntity<TaskCommandAcceptedBody> createTask(
            @RequestHeader(IDEMPOTENCY_HEADER) String idempotencyKey,
            @RequestBody CreateTaskHttpRequest request
    ) {
        var accessContext = accessContextPort.requireCurrent();
        var result = createTaskUseCase.create(
                request.toCommand(idempotencyKey, accessContext.actorId().value()),
                accessContext
        );
        return ResponseEntity.accepted()
                .location(URI.create(result.statusUrl()))
                .header("Idempotency-Replayed", Boolean.toString(result.idempotencyReplayed()))
                .body(TaskCommandAcceptedBody.from(result));
    }

    @GetMapping("/{taskId}")
    ResponseEntity<TaskSnapshotBody> getTaskSnapshot(
            @PathVariable UUID taskId,
            @RequestHeader(name = "If-None-Match", required = false) String ifNoneMatch
    ) {
        var accessContext = accessContextPort.requireCurrent();
        var snapshot = taskSnapshotQuery.requireSnapshot(taskId, accessContext);
        var responseBody = TaskSnapshotBody.from(snapshot);
        var etag = etag(responseBody, accessContext);
        if (etag.equals(ifNoneMatch)) {
            return ResponseEntity.status(HttpStatus.NOT_MODIFIED)
                    .header(HttpHeaders.ETAG, etag)
                    .header(HttpHeaders.CACHE_CONTROL, PRIVATE_REVALIDATE)
                    .build();
        }
        return ResponseEntity.ok()
                .header(HttpHeaders.ETAG, etag)
                .header(HttpHeaders.CACHE_CONTROL, PRIVATE_REVALIDATE)
                .body(responseBody);
    }

    @GetMapping(path = "/{taskId}/events", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    ResponseEntity<SseEmitter> subscribeTaskEvents(
            @PathVariable UUID taskId,
            @RequestHeader(name = "Last-Event-ID", required = false) String lastEventId,
            @RequestParam(name = "afterEventId", required = false) String afterEventId
    ) {
        var cursor = resolveEventCursor(lastEventId, afterEventId);
        var principal = actorContextPort.requireCurrent();
        var emitter = taskEventSsePublisher.open(
                taskId,
                cursor,
                principal.sessionId(),
                AccessContext.fromAuthenticatedPrincipal(principal)
        );
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .header(HttpHeaders.CACHE_CONTROL, SSE_NO_STORE)
                .header("X-Accel-Buffering", "no")
                .header("X-Trace-Id", UUID.randomUUID().toString())
                .body(emitter);
    }

    private static String resolveEventCursor(String lastEventId, String afterEventId) {
        var normalizedHeader = normalizeEventCursor(lastEventId, "Last-Event-ID");
        var normalizedQuery = normalizeEventCursor(afterEventId, "afterEventId");
        if (normalizedHeader != null && normalizedQuery != null && !normalizedHeader.equals(normalizedQuery)) {
            throw new IllegalArgumentException("Last-Event-ID and afterEventId must match when both are provided");
        }
        return normalizedQuery == null ? normalizedHeader : normalizedQuery;
    }

    private static String normalizeEventCursor(String value, String fieldName) {
        if (value == null) {
            return null;
        }
        if (!EVENT_ID_PATTERN.matcher(value).matches()) {
            throw new IllegalArgumentException(fieldName + " does not match the event cursor contract");
        }
        return value;
    }

    private String etag(TaskSnapshotBody snapshot, AccessContext accessContext) {
        var material = new TaskEtagMaterial(
                accessContext.tenantId().value(),
                accessContext.actorId().value(),
                accessContext.authorities().stream().sorted().toList(),
                snapshot
        );
        try {
            var digest = MessageDigest.getInstance("SHA-256").digest(etagWriter.writeValueAsBytes(material));
            return '"' + HexFormat.of().formatHex(digest) + '"';
        } catch (NoSuchAlgorithmException | JsonProcessingException exception) {
            throw new IllegalStateException("Unable to generate task ETag", exception);
        }
    }

    public record CreateTaskHttpRequest(
            UUID sourceConversationId,
            UUID sourceMessageId,
            String expectedMembershipVersion,
            String goal,
            List<String> constraints,
            List<InputReferenceBody> inputRefs,
            CollaborationMode collaborationMode,
            List<UUID> targetAgentIds,
            UUID primaryAgentId,
            TaskOwnershipBody ownership,
            JsonNode maxPointCost,
            CapabilityInputBody capabilityInput,
            String desiredArtifactType
    ) {

        CreateTaskCommand toCommand(String idempotencyKey, UUID currentActorId) {
            requireField(goal, "goal");
            requireField(collaborationMode, "collaborationMode");
            requireField(targetAgentIds, "targetAgentIds");
            requireField(ownership, "ownership");
            requireField(capabilityInput, "capabilityInput");
            if (maxPointCost == null || !maxPointCost.isTextual()) {
                throw new IllegalArgumentException("maxPointCost must be a decimal string");
            }
            return new CreateTaskCommand(
                    idempotencyKey,
                    sourceConversationId,
                    sourceMessageId,
                    expectedMembershipVersion,
                    goal,
                    constraints == null ? List.of() : constraints,
                    inputRefs == null ? List.of() : inputRefs.stream().map(InputReferenceBody::toApi).toList(),
                    collaborationMode,
                    targetAgentIds,
                    primaryAgentId,
                    ownership.toApi(currentActorId),
                    PointValues.parseDisplayValue(maxPointCost.textValue()),
                    capabilityInput.toApi(),
                    desiredArtifactType
            );
        }

        private static <T> T requireField(T value, String name) {
            if (value == null) {
                throw new IllegalArgumentException(name + " is required");
            }
            return value;
        }
    }

    public record InputReferenceBody(InputReferenceType refType, UUID refId, String version) {

        InputReference toApi() {
            if (refType == null || refId == null || version == null) {
                throw new IllegalArgumentException("inputRefs entries require refType, refId and version");
            }
            return new InputReference(refType, refId, version);
        }
    }

    public record TaskOwnershipBody(
            UUID ownerUserId,
            UUID projectId,
            BillingScopeType billingScopeType,
            UUID billingScopeId
    ) {

        TaskOwnership toApi(UUID currentActorId) {
            if (ownerUserId == null || billingScopeType == null || billingScopeId == null) {
                throw new IllegalArgumentException(
                        "ownership requires ownerUserId, billingScopeType and billingScopeId"
                );
            }
            if (!ownerUserId.equals(currentActorId)) {
                throw new TaskAdmissionRejectedException(
                        "TASK_OWNER_MISMATCH",
                        "The initial task owner must be the current actor"
                );
            }
            return new TaskOwnership(ownerUserId, projectId, billingScopeType, billingScopeId);
        }
    }

    public record CapabilityInputBody(String schemaId, String schemaVersion, Map<String, Object> values) {

        CapabilityInput toApi() {
            if (schemaId == null || schemaVersion == null || values == null) {
                throw new IllegalArgumentException("capabilityInput requires schemaId, schemaVersion and values");
            }
            return new CapabilityInput(schemaId, schemaVersion, values);
        }
    }

    public record TaskCommandAcceptedBody(
            UUID taskId,
            long taskVersion,
            String status,
            java.time.Instant acceptedAt,
            String statusUrl,
            String eventsUrl,
            UUID resumeEventId
    ) {

        static TaskCommandAcceptedBody from(TaskCommandAccepted response) {
            return new TaskCommandAcceptedBody(
                    response.taskId(),
                    response.taskVersion(),
                    response.status().name(),
                    response.acceptedAt(),
                    response.statusUrl(),
                    response.eventsUrl(),
                    response.resumeEventId()
            );
        }
    }

    public record TaskSnapshotBody(
            UUID taskId,
            long taskVersion,
            String title,
            String goal,
            String status,
            TaskSnapshot.TaskBlocker blocker,
            int planVersion,
            String collaborationMode,
            String capabilityCode,
            Map<String, Object> capabilityView,
            List<UUID> targetAgentIds,
            UUID primaryAgentId,
            List<TaskSnapshot.StepView> steps,
            TaskSnapshot.RuntimeRunSummary activeRun,
            List<TaskSnapshot.ArtifactSummary> artifacts,
            TaskSnapshot.ApprovalSummary approval,
            TaskSnapshot.DeliverySummary delivery,
            TaskPointSummaryBody pointSummary,
            List<TaskSnapshot.BusinessTraceItem> businessTrace,
            List<String> allowedActions,
            UUID resumeEventId,
            Instant updatedAt
    ) {

        static TaskSnapshotBody from(TaskSnapshot snapshot) {
            return new TaskSnapshotBody(
                    snapshot.taskId(),
                    snapshot.taskVersion(),
                    snapshot.title(),
                    snapshot.goal(),
                    snapshot.status().name(),
                    snapshot.blocker(),
                    snapshot.planVersion(),
                    snapshot.collaborationMode().name(),
                    snapshot.capabilityCode(),
                    snapshot.capabilityView(),
                    snapshot.targetAgentIds(),
                    snapshot.primaryAgentId(),
                    snapshot.steps(),
                    snapshot.activeRun(),
                    snapshot.artifacts(),
                    snapshot.approval(),
                    snapshot.delivery(),
                    TaskPointSummaryBody.from(snapshot.pointSummary()),
                    snapshot.businessTrace(),
                    snapshot.allowedActions().stream()
                            .map(TaskAllowedAction::name)
                            .sorted()
                            .toList(),
                    snapshot.resumeEventId(),
                    snapshot.updatedAt()
            );
        }
    }

    public record TaskPointSummaryBody(
            String estimatedUpperBound,
            String reserved,
            String captured,
            String released,
            String pendingSettlement
    ) {

        static TaskPointSummaryBody from(TaskPointSummary summary) {
            return new TaskPointSummaryBody(
                    PointValues.formatDisplayValue(summary.estimatedUpperBound()),
                    PointValues.formatDisplayValue(summary.reserved()),
                    PointValues.formatDisplayValue(summary.captured()),
                    PointValues.formatDisplayValue(summary.released()),
                    PointValues.formatDisplayValue(summary.pendingSettlement())
            );
        }
    }

    private record TaskEtagMaterial(
            UUID tenantId,
            UUID actorId,
            List<String> authorities,
            TaskSnapshotBody snapshot
    ) {
    }
}

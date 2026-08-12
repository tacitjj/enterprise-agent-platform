package com.dianlian.platform.employee.infrastructure.web;

import com.dianlian.platform.employee.api.AgentTemplateCommands;
import com.dianlian.platform.employee.api.ActivateEnterpriseAgentCommand;
import com.dianlian.platform.employee.api.AgentVersionQuery;
import com.dianlian.platform.employee.api.CreateEnterpriseAgentConfigurationCommand;
import com.dianlian.platform.employee.api.EnterpriseAgentCommands;
import com.dianlian.platform.employee.api.EnterpriseAgentConfigurationSummary;
import com.dianlian.platform.employee.api.EnterpriseAgentDetail;
import com.dianlian.platform.employee.api.EnterpriseAgentKnowledgeScopeMode;
import com.dianlian.platform.employee.api.EnterpriseAgentManagementQuery;
import com.dianlian.platform.employee.api.EnterpriseAgentModelPolicyMode;
import com.dianlian.platform.employee.api.EnterpriseAgentReadiness;
import com.dianlian.platform.employee.api.EnterpriseAgentSummary;
import com.dianlian.platform.employee.api.EnterpriseAgentTemplateSnapshot;
import com.dianlian.platform.employee.api.EnterpriseAgentVisibilityScope;
import com.dianlian.platform.employee.api.EmployeePreconditionFailedException;
import com.dianlian.platform.employee.api.EmployeePreconditionRequiredException;
import com.dianlian.platform.employee.api.EnterpriseVisibility;
import com.dianlian.platform.employee.api.EnterpriseVisibilityMode;
import com.dianlian.platform.employee.api.ExecutionExecutorType;
import com.dianlian.platform.employee.api.ExecutionStepDescriptor;
import com.dianlian.platform.employee.api.ExecutionTemplateDescriptor;
import com.dianlian.platform.employee.api.HireEnterpriseAgentCommand;
import com.dianlian.platform.employee.api.InputSchemaDescriptor;
import com.dianlian.platform.employee.api.PublishAgentVersionCommand;
import com.dianlian.platform.employee.api.PublishedAgentVersion;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorContextPort;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectWriter;
import com.fasterxml.jackson.databind.SerializationFeature;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1")
public class EmployeeManagementController {

    private static final String IDEMPOTENCY_HEADER = "Idempotency-Key";
    private static final String NO_STORE = "no-store";
    private static final Pattern IDEMPOTENCY_KEY = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$");
    private static final Pattern POSITIVE_MICRO_CREDIT = Pattern.compile("^[1-9][0-9]{0,18}$");
    private static final Pattern EMPLOYEE_ETAG = Pattern.compile("^\"ea-([0-9]+)\"$");

    private final ActorContextPort actorContextPort;
    private final AgentTemplateCommands agentTemplateCommands;
    private final AgentVersionQuery agentVersionQuery;
    private final EnterpriseAgentCommands enterpriseAgentCommands;
    private final EnterpriseAgentManagementQuery enterpriseAgentManagementQuery;
    private final ObjectMapper objectMapper;
    private final ObjectWriter canonicalWriter;

    public EmployeeManagementController(
            ActorContextPort actorContextPort,
            AgentTemplateCommands agentTemplateCommands,
            AgentVersionQuery agentVersionQuery,
            EnterpriseAgentCommands enterpriseAgentCommands,
            EnterpriseAgentManagementQuery enterpriseAgentManagementQuery,
            ObjectMapper objectMapper
    ) {
        this.actorContextPort = Objects.requireNonNull(actorContextPort, "actorContextPort must not be null");
        this.agentTemplateCommands = Objects.requireNonNull(
                agentTemplateCommands,
                "agentTemplateCommands must not be null"
        );
        this.agentVersionQuery = Objects.requireNonNull(agentVersionQuery, "agentVersionQuery must not be null");
        this.enterpriseAgentCommands = Objects.requireNonNull(
                enterpriseAgentCommands,
                "enterpriseAgentCommands must not be null"
        );
        this.enterpriseAgentManagementQuery = Objects.requireNonNull(
                enterpriseAgentManagementQuery,
                "enterpriseAgentManagementQuery must not be null"
        );
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
        this.canonicalWriter = objectMapper.writer().with(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
    }

    @GetMapping("/platform/agent-versions")
    ResponseEntity<AgentVersionListResponse> listPublishedVersions() {
        var accessContext = PlatformAccessContext.fromAuthenticatedPrincipal(actorContextPort.requireCurrent());
        var items = agentVersionQuery.listPublished(accessContext).stream()
                .map(version -> AgentVersionView.from(version, objectMapper))
                .toList();
        return noStore(new AgentVersionListResponse(items));
    }

    @PostMapping("/platform/agent-versions")
    ResponseEntity<AgentVersionView> publishVersion(
            @RequestHeader(IDEMPOTENCY_HEADER) String idempotencyKey,
            @RequestBody PublishAgentVersionRequest request
    ) {
        var accessContext = PlatformAccessContext.fromAuthenticatedPrincipal(actorContextPort.requireCurrent());
        request = requireRequestBody(request);
        var normalizedKey = requireIdempotencyKey(idempotencyKey);
        var outcome = agentTemplateCommands.publishVersion(
                request.toCommand(normalizedKey, requestHash(request)),
                accessContext
        );
        var resource = AgentVersionView.from(outcome.resource(), objectMapper);
        return ResponseEntity.status(outcome.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .header(HttpHeaders.CACHE_CONTROL, NO_STORE)
                .header("Idempotency-Replayed", Boolean.toString(outcome.replayed()))
                .body(resource);
    }

    @GetMapping("/enterprise/agent-catalog")
    ResponseEntity<AgentVersionListResponse> listRecruitableVersions() {
        var accessContext = AccessContext.fromAuthenticatedPrincipal(actorContextPort.requireCurrent());
        var items = agentVersionQuery.listRecruitable(accessContext).stream()
                .map(version -> AgentVersionView.from(version, objectMapper))
                .toList();
        return noStore(new AgentVersionListResponse(items));
    }

    @GetMapping("/enterprise/agents")
    ResponseEntity<EnterpriseAgentListResponse> listEnterpriseAgents() {
        var accessContext = AccessContext.fromAuthenticatedPrincipal(actorContextPort.requireCurrent());
        var items = enterpriseAgentManagementQuery.listManaged(accessContext).stream()
                .map(EnterpriseAgentView::from)
                .toList();
        return noStore(new EnterpriseAgentListResponse(items));
    }

    @PostMapping("/enterprise/agents")
    ResponseEntity<EnterpriseAgentView> hireEnterpriseAgent(
            @RequestHeader(IDEMPOTENCY_HEADER) String idempotencyKey,
            @RequestBody HireEnterpriseAgentRequest request
    ) {
        var accessContext = AccessContext.fromAuthenticatedPrincipal(actorContextPort.requireCurrent());
        request = requireRequestBody(request);
        var normalizedKey = requireIdempotencyKey(idempotencyKey);
        var outcome = enterpriseAgentCommands.hire(
                request.toCommand(normalizedKey, requestHash(request)),
                accessContext
        );
        var resource = EnterpriseAgentView.from(outcome.resource());
        return ResponseEntity.status(outcome.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .header(HttpHeaders.CACHE_CONTROL, NO_STORE)
                .header("Idempotency-Replayed", Boolean.toString(outcome.replayed()))
                .body(resource);
    }

    @GetMapping("/enterprise/agents/{enterpriseAgentId}")
    ResponseEntity<EnterpriseAgentDetailView> getEnterpriseAgent(
            @PathVariable UUID enterpriseAgentId
    ) {
        var accessContext = AccessContext.fromAuthenticatedPrincipal(actorContextPort.requireCurrent());
        var detail = EnterpriseAgentDetailView.from(
                enterpriseAgentManagementQuery.getManagedDetail(enterpriseAgentId, accessContext)
        );
        return ResponseEntity.ok()
                .header(HttpHeaders.CACHE_CONTROL, NO_STORE)
                .eTag(employeeEtag(detail.stateVersion()))
                .body(detail);
    }

    @PostMapping("/enterprise/agents/{enterpriseAgentId}/configuration-versions")
    ResponseEntity<EnterpriseAgentDetailView> createConfigurationVersion(
            @PathVariable UUID enterpriseAgentId,
            @RequestHeader(name = HttpHeaders.IF_MATCH, required = false) String ifMatch,
            @RequestHeader(IDEMPOTENCY_HEADER) String idempotencyKey,
            @RequestBody CreateEnterpriseAgentConfigurationRequest request
    ) {
        var accessContext = AccessContext.fromAuthenticatedPrincipal(actorContextPort.requireCurrent());
        request = requireRequestBody(request);
        var normalizedKey = requireIdempotencyKey(idempotencyKey);
        var outcome = enterpriseAgentCommands.createConfigurationVersion(
                request.toCommand(
                        enterpriseAgentId,
                        requireStateVersion(ifMatch),
                        normalizedKey,
                        requestHash(new ScopedRequest(enterpriseAgentId, request))
                ),
                accessContext
        );
        var detail = EnterpriseAgentDetailView.from(outcome.resource());
        return ResponseEntity.status(outcome.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .header(HttpHeaders.CACHE_CONTROL, NO_STORE)
                .header("Idempotency-Replayed", Boolean.toString(outcome.replayed()))
                .eTag(employeeEtag(detail.stateVersion()))
                .body(detail);
    }

    @PostMapping("/enterprise/agents/{enterpriseAgentId}/activate")
    ResponseEntity<EnterpriseAgentDetailView> activateEnterpriseAgent(
            @PathVariable UUID enterpriseAgentId,
            @RequestHeader(name = HttpHeaders.IF_MATCH, required = false) String ifMatch,
            @RequestHeader(IDEMPOTENCY_HEADER) String idempotencyKey,
            @RequestBody ActivateEnterpriseAgentRequest request
    ) {
        var accessContext = AccessContext.fromAuthenticatedPrincipal(actorContextPort.requireCurrent());
        request = requireRequestBody(request);
        var normalizedKey = requireIdempotencyKey(idempotencyKey);
        var outcome = enterpriseAgentCommands.activate(
                new ActivateEnterpriseAgentCommand(
                        enterpriseAgentId,
                        requireConfigurationVersionId(request.configurationVersionId()),
                        requireStateVersion(ifMatch),
                        normalizedKey,
                        requestHash(new ScopedRequest(enterpriseAgentId, request))
                ),
                accessContext
        );
        var detail = EnterpriseAgentDetailView.from(outcome.resource());
        return ResponseEntity.ok()
                .header(HttpHeaders.CACHE_CONTROL, NO_STORE)
                .header("Idempotency-Replayed", Boolean.toString(outcome.replayed()))
                .eTag(employeeEtag(detail.stateVersion()))
                .body(detail);
    }

    private <T> ResponseEntity<T> noStore(T body) {
        return ResponseEntity.ok().header(HttpHeaders.CACHE_CONTROL, NO_STORE).body(body);
    }

    private String requestHash(Object request) {
        try {
            var bytes = canonicalWriter.writeValueAsString(request).getBytes(StandardCharsets.UTF_8);
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (JsonProcessingException | NoSuchAlgorithmException exception) {
            throw new IllegalStateException("Unable to hash employee management request", exception);
        }
    }

    private static String requireIdempotencyKey(String value) {
        if (value == null || !IDEMPOTENCY_KEY.matcher(value).matches()) {
            throw new IllegalArgumentException("Idempotency-Key must match the public contract");
        }
        return value;
    }

    private static long requireStateVersion(String ifMatch) {
        if (ifMatch == null || ifMatch.isBlank()) {
            throw new EmployeePreconditionRequiredException();
        }
        var matcher = EMPLOYEE_ETAG.matcher(ifMatch.trim());
        if (!matcher.matches()) {
            throw new EmployeePreconditionFailedException();
        }
        try {
            return Long.parseLong(matcher.group(1));
        } catch (NumberFormatException exception) {
            throw new EmployeePreconditionFailedException();
        }
    }

    private static String employeeEtag(String stateVersion) {
        return "\"ea-" + stateVersion + "\"";
    }

    private static UUID requireConfigurationVersionId(UUID value) {
        if (value == null) {
            throw new IllegalArgumentException("configurationVersionId must not be null");
        }
        return value;
    }

    private static <T> T requireRequestBody(T value) {
        if (value == null) {
            throw new IllegalArgumentException("request body must not be null");
        }
        return value;
    }

    public record AgentVersionListResponse(List<AgentVersionView> items) {
        public AgentVersionListResponse {
            items = List.copyOf(items);
        }
    }

    public record EnterpriseAgentListResponse(List<EnterpriseAgentView> items) {
        public EnterpriseAgentListResponse {
            items = List.copyOf(items);
        }
    }

    public record PublishAgentVersionRequest(
            String templateCode,
            String templateName,
            String templateDescription,
            String version,
            String capabilityCode,
            InputSchemaRequest inputSchema,
            ExecutionTemplateRequest executionTemplate,
            JsonNode pointEstimateMicroCredit,
            VisibilityRequest enterpriseVisibility
    ) {
        PublishAgentVersionCommand toCommand(String idempotencyKey, String requestHash) {
            return new PublishAgentVersionCommand(
                    templateCode,
                    templateName,
                    templateDescription,
                    version,
                    capabilityCode,
                    Objects.requireNonNull(inputSchema, "inputSchema must not be null").toApi(),
                    Objects.requireNonNull(executionTemplate, "executionTemplate must not be null").toApi(),
                    parsePositiveMicroCredit(pointEstimateMicroCredit),
                    Objects.requireNonNull(enterpriseVisibility, "enterpriseVisibility must not be null").toApi(),
                    idempotencyKey,
                    requestHash
            );
        }
    }

    private static long parsePositiveMicroCredit(JsonNode value) {
        if (value == null || !value.isTextual()) {
            throw new IllegalArgumentException("pointEstimateMicroCredit must be a positive integer string");
        }
        String text = value.textValue();
        if (!POSITIVE_MICRO_CREDIT.matcher(text).matches()) {
            throw new IllegalArgumentException("pointEstimateMicroCredit must be a positive integer string");
        }
        try {
            return Long.parseLong(text);
        } catch (NumberFormatException exception) {
            throw new IllegalArgumentException("pointEstimateMicroCredit exceeds the supported range", exception);
        }
    }

    public record HireEnterpriseAgentRequest(
            UUID agentVersionId,
            String employeeCode,
            String displayName
    ) {
        HireEnterpriseAgentCommand toCommand(String idempotencyKey, String requestHash) {
            return new HireEnterpriseAgentCommand(
                    agentVersionId,
                    employeeCode,
                    displayName,
                    idempotencyKey,
                    requestHash
            );
        }
    }

    public record CreateEnterpriseAgentConfigurationRequest(
            String displayNameSnapshot,
            String profile,
            String enterpriseInstructions,
            EnterpriseAgentModelPolicyMode modelPolicyMode,
            EnterpriseAgentKnowledgeScopeMode knowledgeScopeMode,
            EnterpriseAgentVisibilityScope visibilityScope
    ) {
        CreateEnterpriseAgentConfigurationCommand toCommand(
                UUID enterpriseAgentId,
                long expectedStateVersion,
                String idempotencyKey,
                String requestHash
        ) {
            return new CreateEnterpriseAgentConfigurationCommand(
                    enterpriseAgentId,
                    expectedStateVersion,
                    displayNameSnapshot,
                    profile,
                    enterpriseInstructions,
                    modelPolicyMode,
                    knowledgeScopeMode,
                    visibilityScope,
                    idempotencyKey,
                    requestHash
            );
        }
    }

    public record ActivateEnterpriseAgentRequest(UUID configurationVersionId) {
    }

    private record ScopedRequest(UUID enterpriseAgentId, Object request) {
    }

    public record InputSchemaRequest(String schemaId, String schemaVersion, JsonNode jsonSchema) {
        InputSchemaDescriptor toApi() {
            if (jsonSchema == null || !jsonSchema.isObject()) {
                throw new IllegalArgumentException("jsonSchema must be an object");
            }
            return new InputSchemaDescriptor(schemaId, schemaVersion, jsonSchema.toString());
        }
    }

    public record ExecutionTemplateRequest(
            String templateCode,
            String version,
            List<ExecutionStepRequest> steps
    ) {
        ExecutionTemplateDescriptor toApi() {
            return new ExecutionTemplateDescriptor(
                    templateCode,
                    version,
                    Objects.requireNonNull(steps, "steps must not be null").stream()
                            .map(ExecutionStepRequest::toApi)
                            .toList()
            );
        }
    }

    public record ExecutionStepRequest(
            String stepKey,
            String title,
            ExecutionExecutorType executorType,
            List<String> dependsOn,
            String inputSchemaRef,
            String outputSchemaRef,
            boolean humanCheckpoint
    ) {
        ExecutionStepDescriptor toApi() {
            return new ExecutionStepDescriptor(
                    stepKey,
                    title,
                    executorType,
                    dependsOn == null ? List.of() : dependsOn,
                    inputSchemaRef,
                    outputSchemaRef,
                    humanCheckpoint
            );
        }
    }

    public record VisibilityRequest(EnterpriseVisibilityMode mode, Set<UUID> tenantIds) {
        EnterpriseVisibility toApi() {
            return new EnterpriseVisibility(mode, tenantIds == null ? Set.of() : tenantIds);
        }
    }

    public record AgentVersionView(
            UUID templateId,
            UUID agentVersionId,
            String templateCode,
            String templateName,
            String templateDescription,
            String version,
            String capabilityCode,
            InputSchemaView inputSchema,
            ExecutionTemplateView executionTemplate,
            String pointEstimateMicroCredit,
            String status,
            VisibilityView enterpriseVisibility,
            String publishedAt
    ) {
        static AgentVersionView from(PublishedAgentVersion source, ObjectMapper objectMapper) {
            try {
                return new AgentVersionView(
                        source.templateId(),
                        source.agentVersionId(),
                        source.templateCode(),
                        source.templateName(),
                        source.templateDescription(),
                        source.version(),
                        source.capabilityCode(),
                        new InputSchemaView(
                                source.inputSchema().schemaId(),
                                source.inputSchema().version(),
                                objectMapper.readTree(source.inputSchema().jsonSchema())
                        ),
                        ExecutionTemplateView.from(source.executionTemplate()),
                        Long.toString(source.pointEstimate()),
                        source.status().name(),
                        new VisibilityView(
                                source.enterpriseVisibility().mode().name(),
                                source.enterpriseVisibility().tenantIds()
                        ),
                        source.publishedAt().toString()
                );
            } catch (JsonProcessingException exception) {
                throw new IllegalStateException("Published input schema is invalid", exception);
            }
        }
    }

    public record InputSchemaView(String schemaId, String schemaVersion, JsonNode jsonSchema) {
    }

    public record ExecutionTemplateView(
            String templateCode,
            String version,
            List<ExecutionStepRequest> steps
    ) {
        static ExecutionTemplateView from(ExecutionTemplateDescriptor source) {
            return new ExecutionTemplateView(
                    source.templateCode(),
                    source.version(),
                    source.steps().stream()
                            .map(step -> new ExecutionStepRequest(
                                    step.stepKey(),
                                    step.title(),
                                    step.executorType(),
                                    step.dependsOn(),
                                    step.inputSchemaRef(),
                                    step.outputSchemaRef(),
                                    step.humanCheckpoint()
                            ))
                            .toList()
            );
        }
    }

    public record VisibilityView(String mode, Set<UUID> tenantIds) {
    }

    public record EnterpriseAgentView(
            UUID enterpriseAgentId,
            UUID templateId,
            UUID agentVersionId,
            String employeeCode,
            String displayName,
            String capabilityCode,
            String status,
            String stateVersion,
            UUID activeConfigurationVersionId,
            UUID activatedBy,
            String activatedAt,
            String hiredAt
    ) {
        static EnterpriseAgentView from(EnterpriseAgentSummary source) {
            return new EnterpriseAgentView(
                    source.enterpriseAgentId(),
                    source.templateId(),
                    source.agentVersionId(),
                    source.employeeCode(),
                    source.displayName(),
                    source.capabilityCode(),
                    source.status().name(),
                    Long.toString(source.stateVersion()),
                    source.activeConfigurationVersionId(),
                    source.activatedBy(),
                    source.activatedAt() == null ? null : source.activatedAt().toString(),
                    source.hiredAt().toString()
            );
        }
    }

    public record EnterpriseAgentDetailView(
            UUID enterpriseAgentId,
            UUID templateId,
            UUID agentVersionId,
            String employeeCode,
            String displayName,
            String capabilityCode,
            String status,
            String stateVersion,
            UUID activeConfigurationVersionId,
            UUID activatedBy,
            String activatedAt,
            String hiredAt,
            EnterpriseAgentTemplateView template,
            EnterpriseAgentConfigurationView latestConfiguration,
            EnterpriseAgentReadinessView readiness,
            List<String> allowedActions
    ) {
        static EnterpriseAgentDetailView from(EnterpriseAgentDetail source) {
            var agent = source.agent();
            return new EnterpriseAgentDetailView(
                    agent.enterpriseAgentId(),
                    agent.templateId(),
                    agent.agentVersionId(),
                    agent.employeeCode(),
                    agent.displayName(),
                    agent.capabilityCode(),
                    agent.status().name(),
                    Long.toString(agent.stateVersion()),
                    agent.activeConfigurationVersionId(),
                    agent.activatedBy(),
                    agent.activatedAt() == null ? null : agent.activatedAt().toString(),
                    agent.hiredAt().toString(),
                    EnterpriseAgentTemplateView.from(source.template()),
                    source.latestConfiguration() == null
                            ? null
                            : EnterpriseAgentConfigurationView.from(source.latestConfiguration()),
                    EnterpriseAgentReadinessView.from(source.readiness()),
                    source.allowedActions().stream().map(Enum::name).sorted().toList()
            );
        }
    }

    public record EnterpriseAgentTemplateView(
            String templateName,
            String templateDescription,
            String version
    ) {
        static EnterpriseAgentTemplateView from(EnterpriseAgentTemplateSnapshot source) {
            return new EnterpriseAgentTemplateView(
                    source.templateName(),
                    source.templateDescription(),
                    source.version()
            );
        }
    }

    public record EnterpriseAgentConfigurationView(
            UUID configurationVersionId,
            String revision,
            String displayNameSnapshot,
            String profile,
            String enterpriseInstructions,
            String modelPolicyMode,
            String knowledgeScopeMode,
            String visibilityScope,
            String status,
            UUID createdBy,
            String createdAt,
            UUID activatedBy,
            String activatedAt
    ) {
        static EnterpriseAgentConfigurationView from(EnterpriseAgentConfigurationSummary source) {
            return new EnterpriseAgentConfigurationView(
                    source.configurationVersionId(),
                    Long.toString(source.revision()),
                    source.displayNameSnapshot(),
                    source.profile(),
                    source.enterpriseInstructions(),
                    source.modelPolicyMode().name(),
                    source.knowledgeScopeMode().name(),
                    source.visibilityScope().name(),
                    source.status().name(),
                    source.createdBy(),
                    source.createdAt().toString(),
                    source.activatedBy(),
                    source.activatedAt() == null ? null : source.activatedAt().toString()
            );
        }
    }

    public record EnterpriseAgentReadinessView(
            boolean ready,
            List<EnterpriseAgentReadinessBlockerView> blockers
    ) {
        static EnterpriseAgentReadinessView from(EnterpriseAgentReadiness source) {
            return new EnterpriseAgentReadinessView(
                    source.ready(),
                    source.blockers().stream()
                            .map(blocker -> new EnterpriseAgentReadinessBlockerView(
                                    blocker.code(),
                                    blocker.message()
                            ))
                            .toList()
            );
        }
    }

    public record EnterpriseAgentReadinessBlockerView(String code, String message) {
    }
}

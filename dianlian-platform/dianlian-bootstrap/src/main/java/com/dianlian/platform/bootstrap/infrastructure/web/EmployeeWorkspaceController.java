package com.dianlian.platform.bootstrap.infrastructure.web;

import com.dianlian.platform.billing.api.PointValues;
import com.dianlian.platform.employee.api.ExecutableAgentQuery;
import com.dianlian.platform.employee.api.ExecutableAgentSummary;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorContextPort;
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
import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/employees")
public final class EmployeeWorkspaceController {

    private static final String PRIVATE_REVALIDATE = "private, no-cache, must-revalidate";

    private final ActorContextPort actorContextPort;
    private final ExecutableAgentQuery executableAgentQuery;
    private final ObjectMapper objectMapper;
    private final ObjectWriter etagWriter;

    public EmployeeWorkspaceController(
            ActorContextPort actorContextPort,
            ExecutableAgentQuery executableAgentQuery,
            ObjectMapper objectMapper
    ) {
        this.actorContextPort = Objects.requireNonNull(actorContextPort, "actorContextPort must not be null");
        this.executableAgentQuery = Objects.requireNonNull(
                executableAgentQuery,
                "executableAgentQuery must not be null"
        );
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
        this.etagWriter = objectMapper.writer().with(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
    }

    @GetMapping("/{agentId}")
    public ResponseEntity<EmployeeWorkspaceView> currentWorkspace(
            @PathVariable UUID agentId,
            @RequestHeader(name = HttpHeaders.IF_NONE_MATCH, required = false) String ifNoneMatch
    ) {
        var principal = actorContextPort.requireCurrent();
        var accessContext = AccessContext.fromAuthenticatedPrincipal(principal);
        var employee = executableAgentQuery.requireExecutableForTask(agentId, accessContext);
        var response = EmployeeWorkspaceView.from(employee, objectMapper);
        var etag = etag(principal.permissionVersion(), accessContext, response);
        if (HttpEtagSupport.matches(ifNoneMatch, etag)) {
            return ResponseEntity.status(HttpStatus.NOT_MODIFIED)
                    .header(HttpHeaders.ETAG, etag)
                    .header(HttpHeaders.CACHE_CONTROL, PRIVATE_REVALIDATE)
                    .build();
        }
        return ResponseEntity.ok()
                .header(HttpHeaders.ETAG, etag)
                .header(HttpHeaders.CACHE_CONTROL, PRIVATE_REVALIDATE)
                .body(response);
    }

    private String etag(String permissionVersion, AccessContext accessContext, EmployeeWorkspaceView response) {
        try {
            var material = etagWriter.writeValueAsString(new EmployeeWorkspaceEtagMaterial(
                    permissionVersion,
                    accessContext.tenantId().value(),
                    accessContext.actorId().value(),
                    response
            ));
            var digest = MessageDigest.getInstance("SHA-256")
                    .digest(material.getBytes(StandardCharsets.UTF_8));
            return '"' + HexFormat.of().formatHex(digest) + '"';
        } catch (JsonProcessingException | NoSuchAlgorithmException exception) {
            throw new IllegalStateException("Unable to generate employee workspace ETag", exception);
        }
    }

    public record EmployeeWorkspaceView(
            UUID agentId,
            UUID agentVersionId,
            String displayName,
            String roleName,
            String capabilityCode,
            String profile,
            List<String> skillLabels,
            String avatarUrl,
            EmployeeInputSchemaView inputSchema,
            EmployeeExecutionTemplateView executionTemplate,
            String pointEstimate,
            List<String> allowedActions
    ) {

        static EmployeeWorkspaceView from(ExecutableAgentSummary employee, ObjectMapper objectMapper) {
            return new EmployeeWorkspaceView(
                    employee.enterpriseAgentId(),
                    employee.agentVersionId(),
                    employee.displayName(),
                    employee.roleName(),
                    employee.capabilityCode(),
                    employee.profile(),
                    employee.skillLabels(),
                    employee.avatarUrl(),
                    EmployeeInputSchemaView.from(employee, objectMapper),
                    EmployeeExecutionTemplateView.from(employee),
                    PointValues.formatDisplayValue(employee.pointEstimate()),
                    List.of("VIEW", "START_WORK")
            );
        }
    }

    public record EmployeeInputSchemaView(
            String schemaId,
            String schemaVersion,
            JsonNode jsonSchema
    ) {

        static EmployeeInputSchemaView from(ExecutableAgentSummary employee, ObjectMapper objectMapper) {
            try {
                var jsonSchema = objectMapper.readTree(employee.inputSchema().jsonSchema());
                if (jsonSchema == null || !jsonSchema.isObject()) {
                    throw new IllegalStateException("Employee input schema must be a JSON object");
                }
                return new EmployeeInputSchemaView(
                        employee.inputSchema().schemaId(),
                        employee.inputSchema().version(),
                        jsonSchema
                );
            } catch (JsonProcessingException exception) {
                throw new IllegalStateException("Employee input schema is not valid JSON", exception);
            }
        }
    }

    public record EmployeeExecutionTemplateView(
            String templateCode,
            String version,
            List<EmployeeExecutionStepView> steps
    ) {

        static EmployeeExecutionTemplateView from(ExecutableAgentSummary employee) {
            var template = employee.executionTemplate();
            return new EmployeeExecutionTemplateView(
                    template.templateCode(),
                    template.version(),
                    template.steps().stream().map(EmployeeExecutionStepView::from).toList()
            );
        }
    }

    public record EmployeeExecutionStepView(
            String stepKey,
            String title,
            String executorType,
            List<String> dependsOn,
            String inputSchemaRef,
            String outputSchemaRef,
            boolean humanCheckpoint
    ) {

        static EmployeeExecutionStepView from(com.dianlian.platform.employee.api.ExecutionStepDescriptor step) {
            return new EmployeeExecutionStepView(
                    step.stepKey(),
                    step.title(),
                    step.executorType().name(),
                    step.dependsOn(),
                    step.inputSchemaRef(),
                    step.outputSchemaRef(),
                    step.humanCheckpoint()
            );
        }
    }

    private record EmployeeWorkspaceEtagMaterial(
            String permissionVersion,
            UUID tenantId,
            UUID actorId,
            EmployeeWorkspaceView response
    ) {
    }
}

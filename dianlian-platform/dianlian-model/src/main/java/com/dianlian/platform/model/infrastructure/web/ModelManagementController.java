package com.dianlian.platform.model.infrastructure.web;

import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.ActorContextPort;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import com.dianlian.platform.identity.api.PlatformAccessRequiredException;
import com.dianlian.platform.model.api.ModelAccessDeniedException;
import com.dianlian.platform.model.api.ModelCatalogCommands;
import com.dianlian.platform.model.api.ModelCatalogQuery;
import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.ModelCommandOutcome;
import com.dianlian.platform.model.api.ModelDefinitionView;
import com.dianlian.platform.model.api.ModelPermissions;
import com.dianlian.platform.model.api.ModelRouteBindingView;
import com.dianlian.platform.model.api.PlatformDefaultModelRouteView;
import com.dianlian.platform.model.api.RegisterModelDefinitionCommand;
import com.dianlian.platform.model.api.SetModelRouteCommand;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.ObjectWriter;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.List;
import java.util.Objects;
import java.util.UUID;
import java.util.regex.Pattern;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1")
public class ModelManagementController {

    private static final String IDEMPOTENCY_HEADER = "Idempotency-Key";
    private static final Pattern IDEMPOTENCY_KEY = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$");
    private static final Pattern NON_NEGATIVE_INTEGER = Pattern.compile("^(0|[1-9][0-9]{0,18})$");
    private static final Pattern POSITIVE_INTEGER = Pattern.compile("^[1-9][0-9]{0,18}$");

    private final ActorContextPort actorContextPort;
    private final ModelCatalogCommands commands;
    private final ModelCatalogQuery query;
    private final ObjectWriter canonicalWriter;

    public ModelManagementController(
            ActorContextPort actorContextPort,
            ModelCatalogCommands commands,
            ModelCatalogQuery query,
            ObjectMapper objectMapper
    ) {
        this.actorContextPort = Objects.requireNonNull(actorContextPort, "actorContextPort must not be null");
        this.commands = Objects.requireNonNull(commands, "commands must not be null");
        this.query = Objects.requireNonNull(query, "query must not be null");
        this.canonicalWriter = Objects.requireNonNull(objectMapper, "objectMapper must not be null")
                .writer()
                .with(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS);
    }

    @GetMapping("/platform/model-definitions")
    ResponseEntity<ModelDefinitionListResponse> listDefinitions() {
        var accessContext = currentPlatformAccessContext(ModelPermissions.PLATFORM_READ);
        return ResponseEntity.ok()
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .body(new ModelDefinitionListResponse(
                        query.list(accessContext).stream().map(ModelDefinitionResponse::from).toList()));
    }

    @GetMapping("/platform/model-routes/defaults")
    ResponseEntity<PlatformDefaultModelRouteListResponse> listPlatformDefaultRoutes() {
        var accessContext = currentPlatformAccessContext(ModelPermissions.PLATFORM_READ);
        return ResponseEntity.ok()
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .body(new PlatformDefaultModelRouteListResponse(query.listPlatformDefaults(accessContext)));
    }

    @PostMapping("/platform/model-definitions")
    ResponseEntity<ModelDefinitionResponse> registerDefinition(
            @RequestHeader(IDEMPOTENCY_HEADER) String idempotencyKey,
            @RequestBody RegisterModelDefinitionRequest request
    ) {
        var accessContext = currentPlatformAccessContext(ModelPermissions.PLATFORM_MANAGE);
        request = Objects.requireNonNull(request, "request must not be null");
        var outcome = commands.register(request.toCommand(
                requireIdempotencyKey(idempotencyKey),
                requestHash(request)
        ), accessContext);
        return ResponseEntity.status(outcome.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .header("Idempotency-Replayed", Boolean.toString(outcome.replayed()))
                .body(ModelDefinitionResponse.from(outcome.resource()));
    }

    @PostMapping("/platform/model-routes/{capabilityType}/default")
    ResponseEntity<ModelRouteBindingView> setPlatformDefault(
            @PathVariable ModelCapabilityType capabilityType,
            @RequestHeader(IDEMPOTENCY_HEADER) String idempotencyKey,
            @RequestBody SetModelRouteRequest request
    ) {
        var accessContext = currentPlatformAccessContext(ModelPermissions.PLATFORM_MANAGE);
        request = Objects.requireNonNull(request, "request must not be null");
        var outcome = commands.setPlatformDefault(
                request.toCommand(capabilityType, requireIdempotencyKey(idempotencyKey), requestHash(
                        new RouteHashScope("PLATFORM", null, capabilityType, request)
                )),
                accessContext
        );
        return outcome(outcome);
    }

    @PostMapping("/enterprise/agents/{enterpriseAgentId}/model-routes/{capabilityType}")
    ResponseEntity<ModelRouteBindingView> bindEnterpriseAgent(
            @PathVariable UUID enterpriseAgentId,
            @PathVariable ModelCapabilityType capabilityType,
            @RequestHeader(IDEMPOTENCY_HEADER) String idempotencyKey,
            @RequestBody SetModelRouteRequest request
    ) {
        var accessContext = AccessContext.fromAuthenticatedPrincipal(actorContextPort.requireCurrent());
        request = Objects.requireNonNull(request, "request must not be null");
        var outcome = commands.bindEnterpriseAgent(
                enterpriseAgentId,
                request.toCommand(capabilityType, requireIdempotencyKey(idempotencyKey), requestHash(
                        new RouteHashScope("AGENT", enterpriseAgentId, capabilityType, request)
                )),
                accessContext
        );
        return outcome(outcome);
    }

    private <T> ResponseEntity<T> outcome(ModelCommandOutcome<T> outcome) {
        return ResponseEntity.status(outcome.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .header("Idempotency-Replayed", Boolean.toString(outcome.replayed()))
                .body(outcome.resource());
    }

    private PlatformAccessContext currentPlatformAccessContext(String permission) {
        try {
            return PlatformAccessContext.fromAuthenticatedPrincipal(actorContextPort.requireCurrent());
        } catch (PlatformAccessRequiredException exception) {
            throw new ModelAccessDeniedException(permission);
        }
    }

    private static String requireIdempotencyKey(String value) {
        if (value == null || !IDEMPOTENCY_KEY.matcher(value).matches()) {
            throw new IllegalArgumentException("Idempotency-Key must match the public contract");
        }
        return value;
    }

    private String requestHash(Object request) {
        try {
            var bytes = canonicalWriter.writeValueAsString(request).getBytes(StandardCharsets.UTF_8);
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (JsonProcessingException | NoSuchAlgorithmException exception) {
            throw new IllegalStateException("Unable to hash model management request", exception);
        }
    }

    private static long parseAmount(JsonNode rawValue, boolean positive) {
        if (rawValue == null || !rawValue.isTextual()) {
            throw new IllegalArgumentException("model rate must be a JSON string");
        }
        String value = rawValue.textValue();
        var pattern = positive ? POSITIVE_INTEGER : NON_NEGATIVE_INTEGER;
        if (value == null || !pattern.matcher(value).matches()) {
            throw new IllegalArgumentException("model rate must be an integer string");
        }
        try {
            return Long.parseLong(value);
        } catch (NumberFormatException exception) {
            throw new IllegalArgumentException("model rate is out of range", exception);
        }
    }

    public record RegisterModelDefinitionRequest(
            String modelCode,
            String displayName,
            String providerCode,
            String protocol,
            String baseUrl,
            String providerModelName,
            String credentialRef,
            ModelCapabilityType capabilityType,
            BigDecimal temperature,
            int maxOutputTokens,
            JsonNode inputRateMicroCreditPerMillionTokens,
            JsonNode outputRateMicroCreditPerMillionTokens,
            JsonNode reservationCeilingMicroCredit
    ) {
        RegisterModelDefinitionCommand toCommand(String idempotencyKey, String requestHash) {
            return new RegisterModelDefinitionCommand(
                    modelCode,
                    displayName,
                    providerCode,
                    protocol,
                    baseUrl,
                    providerModelName,
                    credentialRef,
                    capabilityType,
                    temperature,
                    maxOutputTokens,
                    parseAmount(inputRateMicroCreditPerMillionTokens, false),
                    parseAmount(outputRateMicroCreditPerMillionTokens, false),
                    parseAmount(reservationCeilingMicroCredit, true),
                    idempotencyKey,
                    requestHash
            );
        }
    }

    public record SetModelRouteRequest(UUID modelDefinitionId) {
        SetModelRouteCommand toCommand(
                ModelCapabilityType capabilityType,
                String idempotencyKey,
                String requestHash
        ) {
            return new SetModelRouteCommand(modelDefinitionId, capabilityType, idempotencyKey, requestHash);
        }
    }

    public record ModelDefinitionListResponse(List<ModelDefinitionResponse> items) {
        public ModelDefinitionListResponse {
            items = List.copyOf(Objects.requireNonNull(items, "items must not be null"));
        }
    }

    public record PlatformDefaultModelRouteListResponse(List<PlatformDefaultModelRouteView> items) {
        public PlatformDefaultModelRouteListResponse {
            items = List.copyOf(Objects.requireNonNull(items, "items must not be null"));
        }
    }

    public record ModelDefinitionResponse(
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
            String inputRateMicroCreditPerMillionTokens,
            String outputRateMicroCreditPerMillionTokens,
            String reservationCeilingMicroCredit,
            String status,
            UUID createdBy,
            java.time.Instant createdAt
    ) {
        static ModelDefinitionResponse from(ModelDefinitionView source) {
            return new ModelDefinitionResponse(
                    source.modelDefinitionId(), source.modelCode(), source.configurationVersion(),
                    source.displayName(), source.providerCode(), source.protocol(), source.baseUrl(),
                    source.providerModelName(), source.credentialRef(), source.capabilityType(),
                    source.temperature(), source.maxOutputTokens(),
                    Long.toString(source.inputRateMicroCreditPerMillionTokens()),
                    Long.toString(source.outputRateMicroCreditPerMillionTokens()),
                    Long.toString(source.reservationCeilingMicroCredit()),
                    source.status().name(), source.createdBy(), source.createdAt()
            );
        }
    }

    private record RouteHashScope(
            String scopeType,
            UUID enterpriseAgentId,
            ModelCapabilityType capabilityType,
            SetModelRouteRequest request
    ) {
    }
}

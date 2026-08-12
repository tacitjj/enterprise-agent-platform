package com.dianlian.platform.model.infrastructure;

import com.dianlian.platform.model.api.ModelDefinitionStatus;
import com.dianlian.platform.model.api.ModelDefinitionView;
import com.dianlian.platform.model.api.ModelRouteBindingView;
import com.dianlian.platform.model.api.ModelCapabilityType;
import com.dianlian.platform.model.api.ModelRoutePreference;
import com.dianlian.platform.model.api.PlatformDefaultModelRouteView;
import com.dianlian.platform.model.api.RegisterModelDefinitionCommand;
import com.dianlian.platform.model.api.SetModelRouteCommand;
import com.dianlian.platform.model.application.ModelRepository;
import com.dianlian.platform.model.infrastructure.mapper.ModelDefinitionReadMapper;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcModelRepository implements ModelRepository {

    private static final String DEFINITION_SELECT = """
            SELECT model_definition_id, model_code, configuration_version, display_name,
                   provider_code, protocol, base_url, provider_model_name, credential_ref,
                   capability_type, temperature, max_output_tokens,
                   input_rate_micro_credit_per_million_tokens,
                   output_rate_micro_credit_per_million_tokens,
                   reservation_ceiling_micro_credit, status, request_hash,
                   created_by, created_at
              FROM dianlian_business.model_definition
            """;

    private static final String ROUTE_SELECT = """
            SELECT route_binding_id, scope_type, tenant_id, enterprise_agent_id,
                   capability_type, model_definition_id, state_version, status,
                   request_hash, created_by, created_at
              FROM dianlian_business.model_route_binding
            """;

    private final JdbcClient jdbcClient;
    private final ModelDefinitionReadMapper definitionReadMapper;

    public JdbcModelRepository(JdbcClient jdbcClient, ModelDefinitionReadMapper definitionReadMapper) {
        this.jdbcClient = jdbcClient;
        this.definitionReadMapper = definitionReadMapper;
    }

    @Override
    public Optional<StoredModelDefinition> findDefinitionByIdempotency(UUID actorId, String idempotencyKey) {
        return jdbcClient.sql(DEFINITION_SELECT + """
                        WHERE created_by = :actorId AND idempotency_key = :idempotencyKey
                        """)
                .param("actorId", actorId)
                .param("idempotencyKey", idempotencyKey)
                .query((resultSet, rowNumber) -> new StoredModelDefinition(
                        mapDefinition(resultSet, rowNumber),
                        resultSet.getString("request_hash")
                ))
                .optional();
    }

    @Override
    public ModelDefinitionView insertDefinition(
            RegisterModelDefinitionCommand command,
            UUID actorId,
            Instant now
    ) {
        acquireTransactionLock("model-definition:" + command.modelCode());
        return jdbcClient.sql("""
                        WITH next_version AS (
                            SELECT COALESCE(MAX(configuration_version), 0) + 1 AS value
                              FROM dianlian_business.model_definition
                             WHERE model_code = :modelCode
                        )
                        INSERT INTO dianlian_business.model_definition
                            (model_definition_id, model_code, configuration_version, display_name,
                             provider_code, protocol, base_url, provider_model_name, credential_ref,
                             capability_type, temperature, max_output_tokens,
                             input_rate_micro_credit_per_million_tokens,
                             output_rate_micro_credit_per_million_tokens,
                             reservation_ceiling_micro_credit, status, request_hash, idempotency_key,
                             created_by, created_at)
                        SELECT :definitionId, :modelCode, next_version.value, :displayName,
                               :providerCode, :protocol, :baseUrl, :providerModelName, :credentialRef,
                               :capabilityType, :temperature, :maxOutputTokens,
                               :inputRate, :outputRate, :reservationCeiling, 'ACTIVE',
                               :requestHash, :idempotencyKey, :actorId, :createdAt
                          FROM next_version
                        RETURNING model_definition_id, model_code, configuration_version, display_name,
                                  provider_code, protocol, base_url, provider_model_name, credential_ref,
                                  capability_type, temperature, max_output_tokens,
                                  input_rate_micro_credit_per_million_tokens,
                                  output_rate_micro_credit_per_million_tokens,
                                  reservation_ceiling_micro_credit, status, request_hash,
                                  created_by, created_at
                        """)
                .param("definitionId", UUID.randomUUID())
                .param("modelCode", command.modelCode())
                .param("displayName", command.displayName())
                .param("providerCode", command.providerCode())
                .param("protocol", command.protocol())
                .param("baseUrl", command.baseUrl())
                .param("providerModelName", command.providerModelName())
                .param("credentialRef", command.credentialRef())
                .param("capabilityType", command.capabilityType().name())
                .param("temperature", command.temperature())
                .param("maxOutputTokens", command.maxOutputTokens())
                .param("inputRate", command.inputRateMicroCreditPerMillionTokens())
                .param("outputRate", command.outputRateMicroCreditPerMillionTokens())
                .param("reservationCeiling", command.reservationCeilingMicroCredit())
                .param("requestHash", command.requestHash())
                .param("idempotencyKey", command.idempotencyKey())
                .param("actorId", actorId)
                .param("createdAt", Timestamp.from(now))
                .query(this::mapDefinition)
                .single();
    }

    @Override
    public List<ModelDefinitionView> listDefinitions(int limit) {
        if (limit < 1 || limit > 1_000) {
            throw new IllegalArgumentException("limit must be between 1 and 1000");
        }
        return definitionReadMapper.selectLatest(limit).stream()
                .map(row -> row.toView())
                .toList();
    }

    @Override
    public List<PlatformDefaultModelRouteView> listActivePlatformDefaultRoutes() {
        return jdbcClient.sql("""
                        SELECT capability_type, model_definition_id, route_binding_id,
                               state_version, status, created_at
                          FROM dianlian_business.model_route_binding
                         WHERE scope_type = 'PLATFORM'
                           AND status = 'ACTIVE'
                         ORDER BY capability_type
                        """)
                .query((resultSet, rowNumber) -> new PlatformDefaultModelRouteView(
                        ModelCapabilityType.valueOf(resultSet.getString("capability_type")),
                        resultSet.getObject("model_definition_id", UUID.class),
                        resultSet.getObject("route_binding_id", UUID.class),
                        resultSet.getLong("state_version"),
                        resultSet.getString("status"),
                        resultSet.getTimestamp("created_at").toInstant()
                ))
                .list();
    }

    @Override
    public Optional<ModelDefinitionView> findActiveDefinition(
            UUID modelDefinitionId,
            ModelCapabilityType capabilityType
    ) {
        return jdbcClient.sql(DEFINITION_SELECT + """
                        WHERE model_definition_id = :definitionId
                          AND capability_type = :capabilityType
                          AND status = 'ACTIVE'
                        """)
                .param("definitionId", modelDefinitionId)
                .param("capabilityType", capabilityType.name())
                .query(this::mapDefinition)
                .optional();
    }

    @Override
    public Optional<StoredRouteBinding> findRouteByIdempotency(UUID actorId, String idempotencyKey) {
        return jdbcClient.sql(ROUTE_SELECT + """
                        WHERE created_by = :actorId AND idempotency_key = :idempotencyKey
                        """)
                .param("actorId", actorId)
                .param("idempotencyKey", idempotencyKey)
                .query((resultSet, rowNumber) -> new StoredRouteBinding(
                        mapRoute(resultSet, rowNumber),
                        resultSet.getString("request_hash")
                ))
                .optional();
    }

    @Override
    public ModelRouteBindingView replaceRoute(
            String scopeType,
            UUID tenantId,
            UUID enterpriseAgentId,
            SetModelRouteCommand command,
            UUID actorId,
            Instant now
    ) {
        String routeKey = String.join(":",
                "model-route",
                scopeType,
                tenantId == null ? "platform" : tenantId.toString(),
                enterpriseAgentId == null ? "default" : enterpriseAgentId.toString(),
                command.capabilityType().name());
        acquireTransactionLock(routeKey);
        long stateVersion = jdbcClient.sql("""
                        SELECT COALESCE(MAX(state_version), 0) + 1
                          FROM dianlian_business.model_route_binding
                         WHERE scope_type = :scopeType
                           AND tenant_id IS NOT DISTINCT FROM :tenantId
                           AND enterprise_agent_id IS NOT DISTINCT FROM :enterpriseAgentId
                           AND capability_type = :capabilityType
                        """)
                .param("scopeType", scopeType)
                .param("tenantId", tenantId)
                .param("enterpriseAgentId", enterpriseAgentId)
                .param("capabilityType", command.capabilityType().name())
                .query(Long.class)
                .single();

        jdbcClient.sql("""
                        UPDATE dianlian_business.model_route_binding
                           SET status = 'SUPERSEDED', superseded_at = :now
                         WHERE scope_type = :scopeType
                           AND tenant_id IS NOT DISTINCT FROM :tenantId
                           AND enterprise_agent_id IS NOT DISTINCT FROM :enterpriseAgentId
                           AND capability_type = :capabilityType
                           AND status = 'ACTIVE'
                        """)
                .param("now", Timestamp.from(now))
                .param("scopeType", scopeType)
                .param("tenantId", tenantId)
                .param("enterpriseAgentId", enterpriseAgentId)
                .param("capabilityType", command.capabilityType().name())
                .update();

        return jdbcClient.sql("""
                        INSERT INTO dianlian_business.model_route_binding
                            (route_binding_id, scope_type, tenant_id, enterprise_agent_id,
                             capability_type, model_definition_id, state_version, status,
                             request_hash, idempotency_key, created_by, created_at)
                        VALUES
                            (:routeId, :scopeType, :tenantId, :enterpriseAgentId,
                             :capabilityType, :modelDefinitionId, :stateVersion, 'ACTIVE',
                             :requestHash, :idempotencyKey, :actorId, :createdAt)
                        RETURNING route_binding_id, scope_type, tenant_id, enterprise_agent_id,
                                  capability_type, model_definition_id, state_version, status,
                                  request_hash, created_by, created_at
                        """)
                .param("routeId", UUID.randomUUID())
                .param("scopeType", scopeType)
                .param("tenantId", tenantId)
                .param("enterpriseAgentId", enterpriseAgentId)
                .param("capabilityType", command.capabilityType().name())
                .param("modelDefinitionId", command.modelDefinitionId())
                .param("stateVersion", stateVersion)
                .param("requestHash", command.requestHash())
                .param("idempotencyKey", command.idempotencyKey())
                .param("actorId", actorId)
                .param("createdAt", Timestamp.from(now))
                .query(this::mapRoute)
                .single();
    }

    private void acquireTransactionLock(String lockKey) {
        // PostgreSQL exposes pg_advisory_xact_lock as the pseudo type void. Projecting
        // an IS NULL expression keeps the call executable while giving JDBC a real type.
        jdbcClient.sql("SELECT pg_advisory_xact_lock(hashtextextended(:lockKey, 0)) IS NULL")
                .param("lockKey", lockKey)
                .query(Boolean.class)
                .single();
    }

    @Override
    public Optional<ResolvedRouteRecord> resolve(
            UUID tenantId,
            UUID enterpriseAgentId,
            ModelCapabilityType capabilityType,
            ModelRoutePreference preference
    ) {
        return jdbcClient.sql("""
                        WITH selected_route AS (
                            SELECT r.*
                              FROM dianlian_business.model_route_binding r
                             WHERE r.status = 'ACTIVE'
                               AND r.capability_type = :capabilityType
                               AND (
                                   (:allowAgent = TRUE AND r.scope_type = 'AGENT'
                                       AND r.tenant_id = :tenantId
                                       AND r.enterprise_agent_id = :enterpriseAgentId)
                                   OR (:allowPlatform = TRUE AND r.scope_type = 'PLATFORM')
                               )
                             ORDER BY CASE r.scope_type WHEN 'AGENT' THEN 0 ELSE 1 END,
                                      r.state_version DESC
                             LIMIT 1
                        )
                        SELECT r.route_binding_id, r.scope_type, r.tenant_id, r.enterprise_agent_id,
                               r.capability_type AS route_capability_type, r.model_definition_id AS route_model_definition_id,
                               r.state_version, r.status AS route_status, r.request_hash AS route_request_hash,
                               r.created_by AS route_created_by, r.created_at AS route_created_at,
                               m.model_definition_id, m.model_code, m.configuration_version, m.display_name,
                               m.provider_code, m.protocol, m.base_url, m.provider_model_name, m.credential_ref,
                               m.capability_type, m.temperature, m.max_output_tokens,
                               m.input_rate_micro_credit_per_million_tokens,
                               m.output_rate_micro_credit_per_million_tokens,
                               m.reservation_ceiling_micro_credit, m.status, m.request_hash,
                               m.created_by, m.created_at
                          FROM selected_route r
                          JOIN dianlian_business.model_definition m
                            ON m.model_definition_id = r.model_definition_id
                           AND m.status = 'ACTIVE'
                        """)
                .param("tenantId", tenantId)
                .param("enterpriseAgentId", enterpriseAgentId)
                .param("capabilityType", capabilityType.name())
                .param("allowAgent", preference != ModelRoutePreference.PLATFORM_ONLY)
                .param("allowPlatform", preference != ModelRoutePreference.AGENT_ONLY)
                .query((resultSet, rowNumber) -> new ResolvedRouteRecord(
                        new ModelRouteBindingView(
                                resultSet.getObject("route_binding_id", UUID.class),
                                resultSet.getString("scope_type"),
                                resultSet.getObject("tenant_id", UUID.class),
                                resultSet.getObject("enterprise_agent_id", UUID.class),
                                ModelCapabilityType.valueOf(resultSet.getString("route_capability_type")),
                                resultSet.getObject("route_model_definition_id", UUID.class),
                                resultSet.getLong("state_version"),
                                resultSet.getString("route_status"),
                                resultSet.getObject("route_created_by", UUID.class),
                                resultSet.getTimestamp("route_created_at").toInstant()
                        ),
                        mapDefinition(resultSet, rowNumber)
                ))
                .optional();
    }

    @Override
    public Optional<ResolvedRouteRecord> findSnapshot(UUID routeBindingId, UUID modelDefinitionId) {
        return joinedRouteQuery("""
                        WHERE r.route_binding_id = :routeBindingId
                          AND r.model_definition_id = :modelDefinitionId
                        """)
                .param("routeBindingId", routeBindingId)
                .param("modelDefinitionId", modelDefinitionId)
                .query((resultSet, rowNumber) -> mapResolvedRoute(resultSet, rowNumber))
                .optional();
    }

    private JdbcClient.StatementSpec joinedRouteQuery(String predicate) {
        return jdbcClient.sql("""
                        SELECT r.route_binding_id, r.scope_type, r.tenant_id, r.enterprise_agent_id,
                               r.capability_type AS route_capability_type, r.model_definition_id AS route_model_definition_id,
                               r.state_version, r.status AS route_status, r.request_hash AS route_request_hash,
                               r.created_by AS route_created_by, r.created_at AS route_created_at,
                               m.model_definition_id, m.model_code, m.configuration_version, m.display_name,
                               m.provider_code, m.protocol, m.base_url, m.provider_model_name, m.credential_ref,
                               m.capability_type, m.temperature, m.max_output_tokens,
                               m.input_rate_micro_credit_per_million_tokens,
                               m.output_rate_micro_credit_per_million_tokens,
                               m.reservation_ceiling_micro_credit, m.status, m.request_hash,
                               m.created_by, m.created_at
                          FROM dianlian_business.model_route_binding r
                          JOIN dianlian_business.model_definition m
                            ON m.model_definition_id = r.model_definition_id
                        """ + predicate);
    }

    private ResolvedRouteRecord mapResolvedRoute(ResultSet resultSet, int rowNumber) throws SQLException {
        return new ResolvedRouteRecord(
                new ModelRouteBindingView(
                        resultSet.getObject("route_binding_id", UUID.class),
                        resultSet.getString("scope_type"),
                        resultSet.getObject("tenant_id", UUID.class),
                        resultSet.getObject("enterprise_agent_id", UUID.class),
                        ModelCapabilityType.valueOf(resultSet.getString("route_capability_type")),
                        resultSet.getObject("route_model_definition_id", UUID.class),
                        resultSet.getLong("state_version"),
                        resultSet.getString("route_status"),
                        resultSet.getObject("route_created_by", UUID.class),
                        resultSet.getTimestamp("route_created_at").toInstant()
                ),
                mapDefinition(resultSet, rowNumber)
        );
    }

    private ModelDefinitionView mapDefinition(ResultSet resultSet, int rowNumber) throws SQLException {
        return new ModelDefinitionView(
                resultSet.getObject("model_definition_id", UUID.class),
                resultSet.getString("model_code"),
                resultSet.getLong("configuration_version"),
                resultSet.getString("display_name"),
                resultSet.getString("provider_code"),
                resultSet.getString("protocol"),
                resultSet.getString("base_url"),
                resultSet.getString("provider_model_name"),
                resultSet.getString("credential_ref"),
                ModelCapabilityType.valueOf(resultSet.getString("capability_type")),
                resultSet.getBigDecimal("temperature"),
                resultSet.getInt("max_output_tokens"),
                resultSet.getLong("input_rate_micro_credit_per_million_tokens"),
                resultSet.getLong("output_rate_micro_credit_per_million_tokens"),
                resultSet.getLong("reservation_ceiling_micro_credit"),
                ModelDefinitionStatus.valueOf(resultSet.getString("status")),
                resultSet.getObject("created_by", UUID.class),
                resultSet.getTimestamp("created_at").toInstant()
        );
    }

    private ModelRouteBindingView mapRoute(ResultSet resultSet, int rowNumber) throws SQLException {
        return new ModelRouteBindingView(
                resultSet.getObject("route_binding_id", UUID.class),
                resultSet.getString("scope_type"),
                resultSet.getObject("tenant_id", UUID.class),
                resultSet.getObject("enterprise_agent_id", UUID.class),
                ModelCapabilityType.valueOf(resultSet.getString("capability_type")),
                resultSet.getObject("model_definition_id", UUID.class),
                resultSet.getLong("state_version"),
                resultSet.getString("status"),
                resultSet.getObject("created_by", UUID.class),
                resultSet.getTimestamp("created_at").toInstant()
        );
    }
}

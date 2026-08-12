package com.dianlian.platform.employee.infrastructure;

import com.dianlian.platform.employee.api.AgentVersionStatus;
import com.dianlian.platform.employee.api.EnterpriseAgentStatus;
import com.dianlian.platform.employee.api.EnterpriseAgentConfigurationStatus;
import com.dianlian.platform.employee.api.EnterpriseAgentKnowledgeScopeMode;
import com.dianlian.platform.employee.api.EnterpriseAgentModelPolicyMode;
import com.dianlian.platform.employee.api.EnterpriseAgentSummary;
import com.dianlian.platform.employee.api.EnterpriseAgentVisibilityScope;
import com.dianlian.platform.employee.api.EnterpriseVisibility;
import com.dianlian.platform.employee.api.EnterpriseVisibilityMode;
import com.dianlian.platform.employee.api.ExecutableAgentSummary;
import com.dianlian.platform.employee.api.ExecutionTemplateDescriptor;
import com.dianlian.platform.employee.api.InputSchemaDescriptor;
import com.dianlian.platform.employee.application.EmployeeRepository;
import com.dianlian.platform.employee.domain.AgentTemplate;
import com.dianlian.platform.employee.domain.AgentTemplateStatus;
import com.dianlian.platform.employee.domain.AgentVersion;
import com.dianlian.platform.employee.domain.EnterpriseAgent;
import com.dianlian.platform.employee.domain.EnterpriseAgentConfigurationVersion;
import com.dianlian.platform.employee.domain.EnterpriseAgentStateEvent;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcEmployeeRepository implements EmployeeRepository {

    private static final String VERSION_SELECT = """
            SELECT
                v.agent_version_id,
                v.agent_template_id,
                t.template_code,
                v.template_name,
                v.template_description,
                v.version_label,
                v.capability_code,
                v.input_schema::text AS input_schema,
                v.execution_template::text AS execution_template,
                v.point_estimate,
                v.status,
                v.visibility_mode,
                v.visible_tenant_ids::text AS visible_tenant_ids,
                v.request_hash,
                v.publish_idempotency_key,
                v.published_by,
                v.published_at
            FROM dianlian_business.agent_version v
            JOIN dianlian_business.agent_template t
              ON t.agent_template_id = v.agent_template_id
            """;

    private static final String EXECUTABLE_SELECT = """
            SELECT
                a.enterprise_agent_id,
                a.agent_template_id,
                a.agent_version_id,
                a.active_configuration_version_id,
                t.template_code,
                c.display_name_snapshot,
                v.template_name,
                c.profile,
                c.enterprise_instructions,
                c.model_policy_mode,
                c.knowledge_scope_mode,
                v.capability_code,
                v.input_schema::text AS input_schema,
                v.execution_template::text AS execution_template,
                v.point_estimate,
                a.status AS agent_status,
                v.status AS version_status
            FROM dianlian_business.enterprise_agent a
            JOIN dianlian_business.agent_version v
              ON v.agent_version_id = a.agent_version_id
            JOIN dianlian_business.agent_template t
              ON t.agent_template_id = a.agent_template_id
            JOIN dianlian_business.enterprise_agent_configuration_version c
              ON c.tenant_id = a.tenant_id
             AND c.enterprise_agent_id = a.enterprise_agent_id
             AND c.configuration_version_id = a.active_configuration_version_id
             AND c.status = 'ACTIVE'
            """;

    private static final String AGENT_SELECT = """
            SELECT
                a.enterprise_agent_id,
                a.tenant_id,
                a.agent_template_id,
                a.agent_version_id,
                a.employee_code,
                a.display_name,
                v.capability_code,
                a.status,
                a.state_version,
                a.active_configuration_version_id,
                a.activated_by,
                a.activated_at,
                a.request_hash,
                a.hire_idempotency_key,
                a.hired_by,
                a.hired_at
            FROM dianlian_business.enterprise_agent a
            JOIN dianlian_business.agent_version v
              ON v.agent_version_id = a.agent_version_id
            """;

    private static final String CONFIGURATION_SELECT = """
            SELECT
                c.configuration_version_id,
                c.tenant_id,
                c.enterprise_agent_id,
                c.revision,
                c.display_name_snapshot,
                c.profile,
                c.enterprise_instructions,
                c.model_policy_mode,
                c.knowledge_scope_mode,
                c.visibility_scope,
                c.status,
                c.create_request_hash,
                c.create_idempotency_key,
                c.created_by,
                c.created_at,
                c.create_result_state_version,
                c.activation_request_hash,
                c.activation_idempotency_key,
                c.activated_by,
                c.activated_at,
                c.activation_result_state_version
            FROM dianlian_business.enterprise_agent_configuration_version c
            """;

    private final JdbcClient jdbcClient;
    private final ObjectMapper objectMapper;

    public JdbcEmployeeRepository(JdbcClient jdbcClient, ObjectMapper objectMapper) {
        this.jdbcClient = Objects.requireNonNull(jdbcClient, "jdbcClient must not be null");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
    }

    @Override
    public Optional<AgentVersion> findVersionByIdempotency(
            UUID actorId,
            String idempotencyKey
    ) {
        return jdbcClient.sql(VERSION_SELECT + """
                        WHERE v.published_by = :actorId
                          AND v.publish_idempotency_key = :idempotencyKey
                        """)
                .param("actorId", actorId)
                .param("idempotencyKey", idempotencyKey)
                .query(this::mapAgentVersion)
                .optional();
    }

    @Override
    public AgentTemplate getOrCreateTemplate(AgentTemplate proposedTemplate) {
        return jdbcClient.sql("""
                        INSERT INTO dianlian_business.agent_template
                            (agent_template_id, owner_scope, template_code, status, created_by, created_at, updated_at)
                        VALUES
                            (:templateId, 'PLATFORM', :templateCode, :status, :createdBy, :createdAt, :createdAt)
                        ON CONFLICT (template_code)
                        DO UPDATE SET template_code = EXCLUDED.template_code
                        RETURNING agent_template_id, template_code, status, created_by, created_at
                        """)
                .param("templateId", proposedTemplate.templateId())
                .param("templateCode", proposedTemplate.templateCode())
                .param("status", proposedTemplate.status().name())
                .param("createdBy", proposedTemplate.createdBy())
                .param("createdAt", Timestamp.from(proposedTemplate.createdAt()))
                .query(this::mapAgentTemplate)
                .single();
    }

    @Override
    public Optional<AgentVersion> findVersionByTemplateAndLabel(
            UUID templateId,
            String version
    ) {
        return jdbcClient.sql(VERSION_SELECT + """
                        WHERE v.agent_template_id = :templateId
                          AND v.version_label = :version
                        """)
                .param("templateId", templateId)
                .param("version", version)
                .query(this::mapAgentVersion)
                .optional();
    }

    @Override
    public boolean insertVersionIfAbsent(AgentVersion version) {
        int inserted = jdbcClient.sql("""
                        INSERT INTO dianlian_business.agent_version
                            (agent_version_id, owner_scope, agent_template_id, template_name,
                             template_description, version_label, capability_code, input_schema,
                             execution_template, point_estimate, status, visibility_mode,
                             visible_tenant_ids, request_hash, publish_idempotency_key,
                             published_by, published_at, created_at, updated_at)
                        VALUES
                            (:versionId, 'PLATFORM', :templateId, :templateName,
                             :templateDescription, :versionLabel, :capabilityCode,
                             CAST(:inputSchema AS JSONB), CAST(:executionTemplate AS JSONB),
                             :pointEstimate, :status, :visibilityMode,
                             CAST(:visibleTenantIds AS JSONB), :requestHash, :idempotencyKey,
                             :publishedBy, :publishedAt, :publishedAt, :publishedAt)
                        ON CONFLICT DO NOTHING
                        """)
                .param("versionId", version.agentVersionId())
                .param("templateId", version.templateId())
                .param("templateName", version.templateName())
                .param("templateDescription", version.templateDescription())
                .param("versionLabel", version.version())
                .param("capabilityCode", version.capabilityCode())
                .param("inputSchema", writeInputSchema(version.inputSchema()))
                .param("executionTemplate", writeJson(version.executionTemplate()))
                .param("pointEstimate", version.pointEstimate())
                .param("status", version.status().name())
                .param("visibilityMode", version.enterpriseVisibility().mode().name())
                .param("visibleTenantIds", writeTenantIds(version.enterpriseVisibility().tenantIds()))
                .param("requestHash", version.requestHash())
                .param("idempotencyKey", version.publishIdempotencyKey())
                .param("publishedBy", version.publishedBy())
                .param("publishedAt", Timestamp.from(version.publishedAt()))
                .update();
        return inserted == 1;
    }

    @Override
    public List<AgentVersion> listPublishedVersions(int limit) {
        return jdbcClient.sql(VERSION_SELECT + """
                        WHERE v.status = 'PUBLISHED'
                        ORDER BY v.published_at DESC, v.agent_version_id
                        LIMIT :limit
                        """)
                .param("limit", limit)
                .query(this::mapAgentVersion)
                .list();
    }

    @Override
    public List<AgentVersion> listRecruitableVersions(UUID enterpriseTenantId, int limit) {
        return jdbcClient.sql(VERSION_SELECT + """
                        WHERE v.status = 'PUBLISHED'
                          AND (
                              v.visibility_mode = 'ALL'
                              OR v.visible_tenant_ids @> jsonb_build_array(CAST(:enterpriseTenantId AS TEXT))
                          )
                        ORDER BY v.template_name, v.published_at DESC, v.agent_version_id
                        LIMIT :limit
                        """)
                .param("enterpriseTenantId", enterpriseTenantId)
                .param("limit", limit)
                .query(this::mapAgentVersion)
                .list();
    }

    @Override
    public Optional<AgentVersion> findRecruitableVersion(UUID agentVersionId, UUID enterpriseTenantId) {
        return jdbcClient.sql(VERSION_SELECT + """
                        WHERE v.agent_version_id = :versionId
                          AND v.status = 'PUBLISHED'
                          AND (
                              v.visibility_mode = 'ALL'
                              OR v.visible_tenant_ids @> jsonb_build_array(CAST(:enterpriseTenantId AS TEXT))
                          )
                        """)
                .param("versionId", agentVersionId)
                .param("enterpriseTenantId", enterpriseTenantId)
                .query(this::mapAgentVersion)
                .optional();
    }

    @Override
    public Optional<AgentVersion> lockRecruitableVersion(UUID agentVersionId, UUID enterpriseTenantId) {
        return jdbcClient.sql(VERSION_SELECT + """
                        WHERE v.agent_version_id = :versionId
                          AND v.status = 'PUBLISHED'
                          AND (
                              v.visibility_mode = 'ALL'
                              OR v.visible_tenant_ids @> jsonb_build_array(CAST(:enterpriseTenantId AS TEXT))
                          )
                        FOR SHARE OF v
                        """)
                .param("versionId", agentVersionId)
                .param("enterpriseTenantId", enterpriseTenantId)
                .query(this::mapAgentVersion)
                .optional();
    }

    @Override
    public Optional<AgentVersion> findVersion(UUID agentVersionId) {
        return jdbcClient.sql(VERSION_SELECT + """
                        WHERE v.agent_version_id = :versionId
                        """)
                .param("versionId", agentVersionId)
                .query(this::mapAgentVersion)
                .optional();
    }

    @Override
    public Optional<EnterpriseAgent> findAgentByIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        return jdbcClient.sql(AGENT_SELECT + """
                        WHERE a.tenant_id = :tenantId
                          AND a.hired_by = :actorId
                          AND a.hire_idempotency_key = :idempotencyKey
                        """)
                .param("tenantId", tenantId)
                .param("actorId", actorId)
                .param("idempotencyKey", idempotencyKey)
                .query(this::mapEnterpriseAgent)
                .optional();
    }

    @Override
    public boolean insertAgentIfAbsent(EnterpriseAgent agent) {
        int inserted = jdbcClient.sql("""
                        INSERT INTO dianlian_business.enterprise_agent
                            (enterprise_agent_id, tenant_id, agent_template_id, agent_version_id,
                             employee_code, display_name, status, request_hash,
                             hire_idempotency_key, hired_by, hired_at, created_at, updated_at)
                        VALUES
                            (:agentId, :tenantId, :templateId, :versionId,
                             :employeeCode, :displayName, :status, :requestHash,
                             :idempotencyKey, :hiredBy, :hiredAt, :hiredAt, :hiredAt)
                        ON CONFLICT DO NOTHING
                        """)
                .param("agentId", agent.enterpriseAgentId())
                .param("tenantId", agent.tenantId())
                .param("templateId", agent.templateId())
                .param("versionId", agent.agentVersionId())
                .param("employeeCode", agent.employeeCode())
                .param("displayName", agent.displayName())
                .param("status", agent.status().name())
                .param("requestHash", agent.requestHash())
                .param("idempotencyKey", agent.hireIdempotencyKey())
                .param("hiredBy", agent.hiredBy())
                .param("hiredAt", Timestamp.from(agent.hiredAt()))
                .update();
        return inserted == 1;
    }

    @Override
    public boolean existsAgentByCode(UUID tenantId, String employeeCode) {
        return Boolean.TRUE.equals(jdbcClient.sql("""
                        SELECT EXISTS (
                            SELECT 1
                              FROM dianlian_business.enterprise_agent
                             WHERE tenant_id = :tenantId
                               AND employee_code = :employeeCode
                        )
                        """)
                .param("tenantId", tenantId)
                .param("employeeCode", employeeCode)
                .query(Boolean.class)
                .single());
    }

    @Override
    public Optional<EnterpriseAgent> findAgent(UUID tenantId, UUID enterpriseAgentId) {
        return jdbcClient.sql(AGENT_SELECT + """
                        WHERE a.tenant_id = :tenantId
                          AND a.enterprise_agent_id = :agentId
                        """)
                .param("tenantId", tenantId)
                .param("agentId", enterpriseAgentId)
                .query(this::mapEnterpriseAgent)
                .optional();
    }

    @Override
    public Optional<EnterpriseAgent> lockAgent(UUID tenantId, UUID enterpriseAgentId) {
        return jdbcClient.sql(AGENT_SELECT + """
                        WHERE a.tenant_id = :tenantId
                          AND a.enterprise_agent_id = :agentId
                        FOR UPDATE OF a
                        """)
                .param("tenantId", tenantId)
                .param("agentId", enterpriseAgentId)
                .query(this::mapEnterpriseAgent)
                .optional();
    }

    @Override
    public Optional<EnterpriseAgentConfigurationVersion> findConfigurationByCreateIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        return jdbcClient.sql(CONFIGURATION_SELECT + """
                        WHERE c.tenant_id = :tenantId
                          AND c.created_by = :actorId
                          AND c.create_idempotency_key = :idempotencyKey
                        """)
                .param("tenantId", tenantId)
                .param("actorId", actorId)
                .param("idempotencyKey", idempotencyKey)
                .query(this::mapConfiguration)
                .optional();
    }

    @Override
    public Optional<EnterpriseAgentConfigurationVersion> findConfigurationByActivationIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    ) {
        return jdbcClient.sql(CONFIGURATION_SELECT + """
                        WHERE c.tenant_id = :tenantId
                          AND c.activated_by = :actorId
                          AND c.activation_idempotency_key = :idempotencyKey
                        """)
                .param("tenantId", tenantId)
                .param("actorId", actorId)
                .param("idempotencyKey", idempotencyKey)
                .query(this::mapConfiguration)
                .optional();
    }

    @Override
    public Optional<EnterpriseAgentConfigurationVersion> findConfiguration(
            UUID tenantId,
            UUID enterpriseAgentId,
            UUID configurationVersionId
    ) {
        return jdbcClient.sql(CONFIGURATION_SELECT + """
                        WHERE c.tenant_id = :tenantId
                          AND c.enterprise_agent_id = :agentId
                          AND c.configuration_version_id = :configurationVersionId
                        """)
                .param("tenantId", tenantId)
                .param("agentId", enterpriseAgentId)
                .param("configurationVersionId", configurationVersionId)
                .query(this::mapConfiguration)
                .optional();
    }

    @Override
    public Optional<EnterpriseAgentConfigurationVersion> findLatestConfiguration(
            UUID tenantId,
            UUID enterpriseAgentId
    ) {
        return jdbcClient.sql(CONFIGURATION_SELECT + """
                        WHERE c.tenant_id = :tenantId
                          AND c.enterprise_agent_id = :agentId
                        ORDER BY c.revision DESC
                        LIMIT 1
                        """)
                .param("tenantId", tenantId)
                .param("agentId", enterpriseAgentId)
                .query(this::mapConfiguration)
                .optional();
    }

    @Override
    public long nextConfigurationRevision(UUID tenantId, UUID enterpriseAgentId) {
        return jdbcClient.sql("""
                        SELECT COALESCE(MAX(revision), 0) + 1
                        FROM dianlian_business.enterprise_agent_configuration_version
                        WHERE tenant_id = :tenantId
                          AND enterprise_agent_id = :agentId
                        """)
                .param("tenantId", tenantId)
                .param("agentId", enterpriseAgentId)
                .query(Long.class)
                .single();
    }

    @Override
    public boolean insertConfigurationIfAbsent(EnterpriseAgentConfigurationVersion configuration) {
        int inserted = jdbcClient.sql("""
                        INSERT INTO dianlian_business.enterprise_agent_configuration_version
                            (configuration_version_id, tenant_id, enterprise_agent_id, revision,
                             display_name_snapshot, profile, enterprise_instructions,
                             model_policy_mode, knowledge_scope_mode, visibility_scope, status,
                             create_request_hash, create_idempotency_key, created_by, created_at,
                             create_result_state_version, updated_at)
                        VALUES
                            (:configurationVersionId, :tenantId, :agentId, :revision,
                             :displayName, :profile, :instructions,
                             :modelPolicyMode, :knowledgeScopeMode, :visibilityScope, :status,
                             :requestHash, :idempotencyKey, :createdBy, :createdAt,
                             :resultStateVersion, :createdAt)
                        ON CONFLICT DO NOTHING
                        """)
                .param("configurationVersionId", configuration.configurationVersionId())
                .param("tenantId", configuration.tenantId())
                .param("agentId", configuration.enterpriseAgentId())
                .param("revision", configuration.revision())
                .param("displayName", configuration.displayNameSnapshot())
                .param("profile", configuration.profile())
                .param("instructions", configuration.enterpriseInstructions())
                .param("modelPolicyMode", configuration.modelPolicyMode().name())
                .param("knowledgeScopeMode", configuration.knowledgeScopeMode().name())
                .param("visibilityScope", configuration.visibilityScope().name())
                .param("status", configuration.status().name())
                .param("requestHash", configuration.createRequestHash())
                .param("idempotencyKey", configuration.createIdempotencyKey())
                .param("createdBy", configuration.createdBy())
                .param("createdAt", Timestamp.from(configuration.createdAt()))
                .param("resultStateVersion", configuration.createResultStateVersion())
                .update();
        return inserted == 1;
    }

    @Override
    public void supersedeOtherDraftConfigurations(
            UUID tenantId,
            UUID enterpriseAgentId,
            UUID retainedConfigurationVersionId,
            Instant now
    ) {
        jdbcClient.sql("""
                        UPDATE dianlian_business.enterprise_agent_configuration_version
                           SET status = 'SUPERSEDED',
                               updated_at = :updatedAt
                         WHERE tenant_id = :tenantId
                           AND enterprise_agent_id = :agentId
                           AND configuration_version_id <> :retainedConfigurationVersionId
                           AND status = 'DRAFT'
                        """)
                .param("updatedAt", Timestamp.from(now))
                .param("tenantId", tenantId)
                .param("agentId", enterpriseAgentId)
                .param("retainedConfigurationVersionId", retainedConfigurationVersionId)
                .update();
    }

    @Override
    public boolean advanceAgentConfigurationState(
            UUID tenantId,
            UUID enterpriseAgentId,
            long expectedStateVersion,
            Instant now
    ) {
        return jdbcClient.sql("""
                        UPDATE dianlian_business.enterprise_agent
                           SET state_version = state_version + 1,
                               updated_at = :updatedAt
                         WHERE tenant_id = :tenantId
                           AND enterprise_agent_id = :agentId
                           AND status = 'DRAFT'
                           AND state_version = :expectedStateVersion
                        """)
                .param("updatedAt", Timestamp.from(now))
                .param("tenantId", tenantId)
                .param("agentId", enterpriseAgentId)
                .param("expectedStateVersion", expectedStateVersion)
                .update() == 1;
    }

    @Override
    public boolean activateConfiguration(
            UUID tenantId,
            UUID enterpriseAgentId,
            UUID configurationVersionId,
            UUID actorId,
            String requestHash,
            String idempotencyKey,
            long activationResultStateVersion,
            Instant now
    ) {
        return jdbcClient.sql("""
                        UPDATE dianlian_business.enterprise_agent_configuration_version
                           SET status = 'ACTIVE',
                               activation_request_hash = :requestHash,
                               activation_idempotency_key = :idempotencyKey,
                               activated_by = :actorId,
                               activated_at = :activatedAt,
                               activation_result_state_version = :resultStateVersion,
                               updated_at = :activatedAt
                         WHERE tenant_id = :tenantId
                           AND enterprise_agent_id = :agentId
                           AND configuration_version_id = :configurationVersionId
                           AND status = 'DRAFT'
                           AND activation_idempotency_key IS NULL
                        """)
                .param("requestHash", requestHash)
                .param("idempotencyKey", idempotencyKey)
                .param("actorId", actorId)
                .param("activatedAt", Timestamp.from(now))
                .param("resultStateVersion", activationResultStateVersion)
                .param("tenantId", tenantId)
                .param("agentId", enterpriseAgentId)
                .param("configurationVersionId", configurationVersionId)
                .update() == 1;
    }

    @Override
    public boolean activateAgent(
            UUID tenantId,
            UUID enterpriseAgentId,
            UUID configurationVersionId,
            String displayName,
            UUID actorId,
            long expectedStateVersion,
            Instant now
    ) {
        return jdbcClient.sql("""
                        UPDATE dianlian_business.enterprise_agent
                           SET display_name = :displayName,
                               status = 'ACTIVE',
                               state_version = state_version + 1,
                               active_configuration_version_id = :configurationVersionId,
                               activated_by = :actorId,
                               activated_at = :activatedAt,
                               updated_at = :activatedAt
                         WHERE tenant_id = :tenantId
                           AND enterprise_agent_id = :agentId
                           AND status = 'DRAFT'
                           AND state_version = :expectedStateVersion
                           AND active_configuration_version_id IS NULL
                        """)
                .param("displayName", displayName)
                .param("configurationVersionId", configurationVersionId)
                .param("actorId", actorId)
                .param("activatedAt", Timestamp.from(now))
                .param("tenantId", tenantId)
                .param("agentId", enterpriseAgentId)
                .param("expectedStateVersion", expectedStateVersion)
                .update() == 1;
    }

    @Override
    public void insertStateEvent(EnterpriseAgentStateEvent event) {
        jdbcClient.sql("""
                        INSERT INTO dianlian_business.enterprise_agent_state_event
                            (event_id, tenant_id, enterprise_agent_id, state_version, event_type,
                             from_status, to_status, configuration_version_id, request_hash,
                             idempotency_key, actor_id, occurred_at)
                        VALUES
                            (:eventId, :tenantId, :agentId, :stateVersion, :eventType,
                             :fromStatus, :toStatus, :configurationVersionId, :requestHash,
                             :idempotencyKey, :actorId, :occurredAt)
                        """)
                .param("eventId", event.eventId())
                .param("tenantId", event.tenantId())
                .param("agentId", event.enterpriseAgentId())
                .param("stateVersion", event.stateVersion())
                .param("eventType", event.eventType())
                .param("fromStatus", event.fromStatus() == null ? null : event.fromStatus().name())
                .param("toStatus", event.toStatus().name())
                .param("configurationVersionId", event.configurationVersionId())
                .param("requestHash", event.requestHash())
                .param("idempotencyKey", event.idempotencyKey())
                .param("actorId", event.actorId())
                .param("occurredAt", Timestamp.from(event.occurredAt()))
                .update();
    }

    @Override
    public List<EnterpriseAgentSummary> listManagedAgents(UUID tenantId, int limit) {
        return jdbcClient.sql("""
                        SELECT
                            a.enterprise_agent_id,
                            a.tenant_id,
                            a.agent_template_id,
                            a.agent_version_id,
                            a.employee_code,
                            a.display_name,
                            v.capability_code,
                            a.status,
                            a.state_version,
                            a.active_configuration_version_id,
                            a.activated_by,
                            a.activated_at,
                            a.hired_at
                        FROM dianlian_business.enterprise_agent a
                        JOIN dianlian_business.agent_version v
                          ON v.agent_version_id = a.agent_version_id
                        WHERE a.tenant_id = :tenantId
                        ORDER BY a.hired_at DESC, a.enterprise_agent_id
                        LIMIT :limit
                        """)
                .param("tenantId", tenantId)
                .param("limit", limit)
                .query((resultSet, rowNumber) -> new EnterpriseAgentSummary(
                        resultSet.getObject("enterprise_agent_id", UUID.class),
                        resultSet.getObject("tenant_id", UUID.class),
                        resultSet.getObject("agent_template_id", UUID.class),
                        resultSet.getObject("agent_version_id", UUID.class),
                        resultSet.getString("employee_code"),
                        resultSet.getString("display_name"),
                        resultSet.getString("capability_code"),
                        EnterpriseAgentStatus.valueOf(resultSet.getString("status")),
                        resultSet.getLong("state_version"),
                        resultSet.getObject("active_configuration_version_id", UUID.class),
                        resultSet.getObject("activated_by", UUID.class),
                        nullableInstant(resultSet, "activated_at"),
                        resultSet.getTimestamp("hired_at").toInstant()
                ))
                .list();
    }

    @Override
    public Optional<ExecutableAgentSummary> findExecutableAgent(UUID tenantId, UUID enterpriseAgentId) {
        return jdbcClient.sql(EXECUTABLE_SELECT + """
                        WHERE a.tenant_id = :tenantId
                          AND a.enterprise_agent_id = :agentId
                          AND a.status = 'ACTIVE'
                          AND v.status = 'PUBLISHED'
                        """)
                .param("tenantId", tenantId)
                .param("agentId", enterpriseAgentId)
                .query(this::mapExecutableAgent)
                .optional();
    }

    @Override
    public List<ExecutableAgentSummary> listExecutableAgents(UUID tenantId, int limit) {
        return jdbcClient.sql(EXECUTABLE_SELECT + """
                        WHERE a.tenant_id = :tenantId
                          AND a.status = 'ACTIVE'
                          AND v.status = 'PUBLISHED'
                        ORDER BY a.display_name, a.enterprise_agent_id
                        LIMIT :limit
                        """)
                .param("tenantId", tenantId)
                .param("limit", limit)
                .query(this::mapExecutableAgent)
                .list();
    }

    private AgentTemplate mapAgentTemplate(ResultSet resultSet, int rowNumber) throws SQLException {
        return new AgentTemplate(
                resultSet.getObject("agent_template_id", UUID.class),
                resultSet.getString("template_code"),
                AgentTemplateStatus.valueOf(resultSet.getString("status")),
                resultSet.getObject("created_by", UUID.class),
                resultSet.getTimestamp("created_at").toInstant()
        );
    }

    private AgentVersion mapAgentVersion(ResultSet resultSet, int rowNumber) throws SQLException {
        return new AgentVersion(
                resultSet.getObject("agent_version_id", UUID.class),
                resultSet.getObject("agent_template_id", UUID.class),
                resultSet.getString("template_code"),
                resultSet.getString("template_name"),
                resultSet.getString("template_description"),
                resultSet.getString("version_label"),
                resultSet.getString("capability_code"),
                readInputSchema(resultSet.getString("input_schema")),
                readJson(resultSet.getString("execution_template"), ExecutionTemplateDescriptor.class),
                resultSet.getLong("point_estimate"),
                AgentVersionStatus.valueOf(resultSet.getString("status")),
                readVisibility(
                        resultSet.getString("visibility_mode"),
                        resultSet.getString("visible_tenant_ids")
                ),
                resultSet.getString("request_hash"),
                resultSet.getString("publish_idempotency_key"),
                resultSet.getObject("published_by", UUID.class),
                resultSet.getTimestamp("published_at").toInstant()
        );
    }

    private EnterpriseAgent mapEnterpriseAgent(ResultSet resultSet, int rowNumber) throws SQLException {
        return new EnterpriseAgent(
                resultSet.getObject("enterprise_agent_id", UUID.class),
                resultSet.getObject("tenant_id", UUID.class),
                resultSet.getObject("agent_template_id", UUID.class),
                resultSet.getObject("agent_version_id", UUID.class),
                resultSet.getString("employee_code"),
                resultSet.getString("display_name"),
                resultSet.getString("capability_code"),
                EnterpriseAgentStatus.valueOf(resultSet.getString("status")),
                resultSet.getLong("state_version"),
                resultSet.getObject("active_configuration_version_id", UUID.class),
                resultSet.getObject("activated_by", UUID.class),
                nullableInstant(resultSet, "activated_at"),
                resultSet.getString("request_hash"),
                resultSet.getString("hire_idempotency_key"),
                resultSet.getObject("hired_by", UUID.class),
                resultSet.getTimestamp("hired_at").toInstant()
        );
    }

    private ExecutableAgentSummary mapExecutableAgent(ResultSet resultSet, int rowNumber) throws SQLException {
        return new ExecutableAgentSummary(
                resultSet.getObject("enterprise_agent_id", UUID.class),
                resultSet.getObject("agent_template_id", UUID.class),
                resultSet.getObject("agent_version_id", UUID.class),
                resultSet.getObject("active_configuration_version_id", UUID.class),
                resultSet.getString("template_code"),
                resultSet.getString("display_name_snapshot"),
                resultSet.getString("template_name"),
                resultSet.getString("profile"),
                resultSet.getString("enterprise_instructions"),
                EnterpriseAgentModelPolicyMode.valueOf(resultSet.getString("model_policy_mode")),
                EnterpriseAgentKnowledgeScopeMode.valueOf(resultSet.getString("knowledge_scope_mode")),
                List.of(),
                null,
                resultSet.getString("capability_code"),
                readInputSchema(resultSet.getString("input_schema")),
                readJson(resultSet.getString("execution_template"), ExecutionTemplateDescriptor.class),
                resultSet.getLong("point_estimate"),
                EnterpriseAgentStatus.valueOf(resultSet.getString("agent_status")),
                AgentVersionStatus.valueOf(resultSet.getString("version_status"))
        );
    }

    private EnterpriseAgentConfigurationVersion mapConfiguration(ResultSet resultSet, int rowNumber)
            throws SQLException {
        Long activationResultStateVersion = resultSet.getObject("activation_result_state_version", Long.class);
        return new EnterpriseAgentConfigurationVersion(
                resultSet.getObject("configuration_version_id", UUID.class),
                resultSet.getObject("tenant_id", UUID.class),
                resultSet.getObject("enterprise_agent_id", UUID.class),
                resultSet.getLong("revision"),
                resultSet.getString("display_name_snapshot"),
                resultSet.getString("profile"),
                resultSet.getString("enterprise_instructions"),
                EnterpriseAgentModelPolicyMode.valueOf(resultSet.getString("model_policy_mode")),
                EnterpriseAgentKnowledgeScopeMode.valueOf(resultSet.getString("knowledge_scope_mode")),
                EnterpriseAgentVisibilityScope.valueOf(resultSet.getString("visibility_scope")),
                EnterpriseAgentConfigurationStatus.valueOf(resultSet.getString("status")),
                resultSet.getString("create_request_hash"),
                resultSet.getString("create_idempotency_key"),
                resultSet.getObject("created_by", UUID.class),
                resultSet.getTimestamp("created_at").toInstant(),
                resultSet.getLong("create_result_state_version"),
                resultSet.getString("activation_request_hash"),
                resultSet.getString("activation_idempotency_key"),
                resultSet.getObject("activated_by", UUID.class),
                nullableInstant(resultSet, "activated_at"),
                activationResultStateVersion
        );
    }

    private static Instant nullableInstant(ResultSet resultSet, String column) throws SQLException {
        Timestamp value = resultSet.getTimestamp(column);
        return value == null ? null : value.toInstant();
    }

    private String writeInputSchema(InputSchemaDescriptor inputSchema) {
        try {
            ObjectNode root = objectMapper.createObjectNode();
            root.put("schemaId", inputSchema.schemaId());
            root.put("version", inputSchema.version());
            root.set("schema", objectMapper.readTree(inputSchema.jsonSchema()));
            return objectMapper.writeValueAsString(root);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("failed to serialize input schema", exception);
        }
    }

    private InputSchemaDescriptor readInputSchema(String value) {
        JsonNode root = readTree(value);
        JsonNode schema = root.get("schema");
        if (schema == null) {
            throw new IllegalStateException("stored input schema is missing schema");
        }
        return new InputSchemaDescriptor(
                root.path("schemaId").asText(),
                root.path("version").asText(),
                schema.toString()
        );
    }

    private String writeTenantIds(Set<UUID> tenantIds) {
        ArrayNode root = objectMapper.createArrayNode();
        tenantIds.stream()
                .sorted(Comparator.comparing(UUID::toString))
                .forEach(tenantId -> root.add(tenantId.toString()));
        return root.toString();
    }

    private EnterpriseVisibility readVisibility(String modeValue, String tenantIdsValue) {
        EnterpriseVisibilityMode mode = EnterpriseVisibilityMode.valueOf(modeValue);
        if (mode == EnterpriseVisibilityMode.ALL) {
            return EnterpriseVisibility.allEnterprises();
        }
        JsonNode root = readTree(tenantIdsValue);
        if (!root.isArray()) {
            throw new IllegalStateException("stored visible tenant ids must be an array");
        }
        Set<UUID> tenantIds = new HashSet<>();
        root.forEach(value -> tenantIds.add(UUID.fromString(value.asText())));
        return EnterpriseVisibility.allowlist(tenantIds);
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("failed to serialize employee data", exception);
        }
    }

    private <T> T readJson(String value, Class<T> type) {
        try {
            return objectMapper.readValue(value, type);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("failed to deserialize employee data", exception);
        }
    }

    private JsonNode readTree(String value) {
        try {
            return objectMapper.readTree(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("failed to deserialize employee JSON", exception);
        }
    }
}

package com.dianlian.platform.employee.application;

import com.dianlian.platform.employee.api.ExecutableAgentSummary;
import com.dianlian.platform.employee.api.EnterpriseAgentSummary;
import com.dianlian.platform.employee.domain.AgentTemplate;
import com.dianlian.platform.employee.domain.AgentVersion;
import com.dianlian.platform.employee.domain.EnterpriseAgent;
import com.dianlian.platform.employee.domain.EnterpriseAgentConfigurationVersion;
import com.dianlian.platform.employee.domain.EnterpriseAgentStateEvent;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface EmployeeRepository {

    Optional<AgentVersion> findVersionByIdempotency(
            UUID actorId,
            String idempotencyKey
    );

    AgentTemplate getOrCreateTemplate(AgentTemplate proposedTemplate);

    Optional<AgentVersion> findVersionByTemplateAndLabel(
            UUID templateId,
            String version
    );

    boolean insertVersionIfAbsent(AgentVersion version);

    List<AgentVersion> listPublishedVersions(int limit);

    List<AgentVersion> listRecruitableVersions(UUID enterpriseTenantId, int limit);

    Optional<AgentVersion> findRecruitableVersion(UUID agentVersionId, UUID enterpriseTenantId);

    Optional<AgentVersion> lockRecruitableVersion(UUID agentVersionId, UUID enterpriseTenantId);

    Optional<AgentVersion> findVersion(UUID agentVersionId);

    Optional<EnterpriseAgent> findAgentByIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    );

    boolean insertAgentIfAbsent(EnterpriseAgent agent);

    boolean existsAgentByCode(UUID tenantId, String employeeCode);

    Optional<EnterpriseAgent> findAgent(UUID tenantId, UUID enterpriseAgentId);

    Optional<EnterpriseAgent> lockAgent(UUID tenantId, UUID enterpriseAgentId);

    Optional<EnterpriseAgentConfigurationVersion> findConfigurationByCreateIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    );

    Optional<EnterpriseAgentConfigurationVersion> findConfigurationByActivationIdempotency(
            UUID tenantId,
            UUID actorId,
            String idempotencyKey
    );

    Optional<EnterpriseAgentConfigurationVersion> findConfiguration(
            UUID tenantId,
            UUID enterpriseAgentId,
            UUID configurationVersionId
    );

    Optional<EnterpriseAgentConfigurationVersion> findLatestConfiguration(
            UUID tenantId,
            UUID enterpriseAgentId
    );

    long nextConfigurationRevision(UUID tenantId, UUID enterpriseAgentId);

    boolean insertConfigurationIfAbsent(EnterpriseAgentConfigurationVersion configuration);

    void supersedeOtherDraftConfigurations(
            UUID tenantId,
            UUID enterpriseAgentId,
            UUID retainedConfigurationVersionId,
            Instant now
    );

    boolean advanceAgentConfigurationState(
            UUID tenantId,
            UUID enterpriseAgentId,
            long expectedStateVersion,
            Instant now
    );

    boolean activateConfiguration(
            UUID tenantId,
            UUID enterpriseAgentId,
            UUID configurationVersionId,
            UUID actorId,
            String requestHash,
            String idempotencyKey,
            long activationResultStateVersion,
            Instant now
    );

    boolean activateAgent(
            UUID tenantId,
            UUID enterpriseAgentId,
            UUID configurationVersionId,
            String displayName,
            UUID actorId,
            long expectedStateVersion,
            Instant now
    );

    void insertStateEvent(EnterpriseAgentStateEvent event);

    List<EnterpriseAgentSummary> listManagedAgents(UUID tenantId, int limit);

    Optional<ExecutableAgentSummary> findExecutableAgent(UUID tenantId, UUID enterpriseAgentId);

    List<ExecutableAgentSummary> listExecutableAgents(UUID tenantId, int limit);
}

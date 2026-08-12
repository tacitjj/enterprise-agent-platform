package com.dianlian.platform.employee.application;

import com.dianlian.platform.employee.api.AgentTemplateCommands;
import com.dianlian.platform.employee.api.ActivateEnterpriseAgentCommand;
import com.dianlian.platform.employee.api.AgentVersionQuery;
import com.dianlian.platform.employee.api.AgentVersionStatus;
import com.dianlian.platform.employee.api.CommandOutcome;
import com.dianlian.platform.employee.api.CreateEnterpriseAgentConfigurationCommand;
import com.dianlian.platform.employee.api.EmployeeAccessDeniedException;
import com.dianlian.platform.employee.api.EmployeeCommandConflictException;
import com.dianlian.platform.employee.api.EmployeePermissions;
import com.dianlian.platform.employee.api.EmployeePreconditionFailedException;
import com.dianlian.platform.employee.api.EmployeeResourceNotDiscoverableException;
import com.dianlian.platform.employee.api.EnterpriseAgentCommands;
import com.dianlian.platform.employee.api.EnterpriseAgentAllowedAction;
import com.dianlian.platform.employee.api.EnterpriseAgentConfigurationStatus;
import com.dianlian.platform.employee.api.EnterpriseAgentConfigurationSummary;
import com.dianlian.platform.employee.api.EnterpriseAgentDetail;
import com.dianlian.platform.employee.api.EnterpriseAgentManagementQuery;
import com.dianlian.platform.employee.api.EnterpriseAgentReadiness;
import com.dianlian.platform.employee.api.EnterpriseAgentReadinessBlocker;
import com.dianlian.platform.employee.api.EnterpriseAgentStatus;
import com.dianlian.platform.employee.api.EnterpriseAgentSummary;
import com.dianlian.platform.employee.api.EnterpriseAgentTemplateSnapshot;
import com.dianlian.platform.employee.api.ExecutableAgentQuery;
import com.dianlian.platform.employee.api.ExecutableAgentSummary;
import com.dianlian.platform.employee.api.HireEnterpriseAgentCommand;
import com.dianlian.platform.employee.api.PublishAgentVersionCommand;
import com.dianlian.platform.employee.api.PublishedAgentVersion;
import com.dianlian.platform.employee.domain.AgentTemplate;
import com.dianlian.platform.employee.domain.AgentTemplateStatus;
import com.dianlian.platform.employee.domain.AgentVersion;
import com.dianlian.platform.employee.domain.EnterpriseAgent;
import com.dianlian.platform.employee.domain.EnterpriseAgentConfigurationVersion;
import com.dianlian.platform.employee.domain.EnterpriseAgentStateEvent;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.Objects;
import java.util.UUID;
import java.util.function.Supplier;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class EmployeeApplicationService implements
        AgentTemplateCommands,
        EnterpriseAgentCommands,
        AgentVersionQuery,
        EnterpriseAgentManagementQuery,
        ExecutableAgentQuery {

    private static final int OFFICE_AGENT_LIMIT = 50;
    private static final int MANAGEMENT_LIST_LIMIT = 100;

    private final EmployeeRepository employeeRepository;
    private final EmployeeContractValidator contractValidator;
    private final Clock clock;
    private final Supplier<UUID> idGenerator;

    @Autowired
    public EmployeeApplicationService(EmployeeRepository employeeRepository, ObjectMapper objectMapper) {
        this(
                employeeRepository,
                new EmployeeContractValidator(objectMapper),
                Clock.systemUTC(),
                UUID::randomUUID
        );
    }

    EmployeeApplicationService(
            EmployeeRepository employeeRepository,
            EmployeeContractValidator contractValidator,
            Clock clock,
            Supplier<UUID> idGenerator
    ) {
        this.employeeRepository = Objects.requireNonNull(employeeRepository, "employeeRepository must not be null");
        this.contractValidator = Objects.requireNonNull(contractValidator, "contractValidator must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
        this.idGenerator = Objects.requireNonNull(idGenerator, "idGenerator must not be null");
    }

    @Override
    @Transactional
    public CommandOutcome<PublishedAgentVersion> publishVersion(
            PublishAgentVersionCommand command,
            PlatformAccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePlatformPermission(accessContext, EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH);

        UUID actorId = accessContext.actorId().value();
        var replay = employeeRepository.findVersionByIdempotency(
                actorId,
                command.idempotencyKey()
        );
        if (replay.isPresent()) {
            requireSameRequest(replay.get().requestHash(), command.requestHash());
            return new CommandOutcome<>(replay.get().toPublishedView(), true);
        }

        contractValidator.requireObjectSchema(command.inputSchema());
        Instant now = clock.instant();
        var proposedTemplate = AgentTemplate.active(
                idGenerator.get(),
                command.templateCode(),
                actorId,
                now
        );
        var template = employeeRepository.getOrCreateTemplate(proposedTemplate);
        if (template.status() != AgentTemplateStatus.ACTIVE) {
            throw new EmployeeCommandConflictException(
                    "AGENT_TEMPLATE_RETIRED",
                    "retired agent template cannot publish a new version"
            );
        }
        if (employeeRepository.findVersionByTemplateAndLabel(
                template.templateId(),
                command.version()
        ).isPresent()) {
            throw new EmployeeCommandConflictException(
                    "AGENT_VERSION_ALREADY_EXISTS",
                    "agent version is append-only and already exists"
            );
        }

        var version = new AgentVersion(
                idGenerator.get(),
                template.templateId(),
                template.templateCode(),
                command.templateName(),
                command.templateDescription(),
                command.version(),
                command.capabilityCode(),
                command.inputSchema(),
                command.executionTemplate(),
                command.pointEstimate(),
                AgentVersionStatus.PUBLISHED,
                command.enterpriseVisibility(),
                command.requestHash(),
                command.idempotencyKey(),
                actorId,
                now
        );
        if (!employeeRepository.insertVersionIfAbsent(version)) {
            var concurrentReplay = employeeRepository.findVersionByIdempotency(
                    actorId,
                    command.idempotencyKey()
            );
            if (concurrentReplay.isPresent()) {
                requireSameRequest(concurrentReplay.get().requestHash(), command.requestHash());
                return new CommandOutcome<>(concurrentReplay.get().toPublishedView(), true);
            }
            if (employeeRepository.findVersionByTemplateAndLabel(
                    template.templateId(),
                    command.version()
            ).isPresent()) {
                throw new EmployeeCommandConflictException(
                        "AGENT_VERSION_ALREADY_EXISTS",
                        "agent version is append-only and already exists"
                );
            }
            throw new EmployeeCommandConflictException(
                    "AGENT_VERSION_CONCURRENT_CONFLICT",
                    "agent version could not be created because another write won"
            );
        }
        return new CommandOutcome<>(version.toPublishedView(), false);
    }

    @Override
    @Transactional
    public CommandOutcome<EnterpriseAgentSummary> hire(
            HireEnterpriseAgentCommand command,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePermission(accessContext, EmployeePermissions.ENTERPRISE_AGENT_HIRE);

        UUID tenantId = accessContext.tenantId().value();
        UUID actorId = accessContext.actorId().value();
        var replay = employeeRepository.findAgentByIdempotency(
                tenantId,
                actorId,
                command.idempotencyKey()
        );
        if (replay.isPresent()) {
            requireSameRequest(replay.get().requestHash(), command.requestHash());
            return new CommandOutcome<>(replay.get().toSummary(), true);
        }

        var version = employeeRepository.findRecruitableVersion(command.agentVersionId(), tenantId)
                .orElseThrow(EmployeeResourceNotDiscoverableException::new);
        Instant now = clock.instant();
        var enterpriseAgent = new EnterpriseAgent(
                idGenerator.get(),
                tenantId,
                version.templateId(),
                version.agentVersionId(),
                command.employeeCode(),
                command.displayName(),
                version.capabilityCode(),
                EnterpriseAgentStatus.DRAFT,
                0,
                null,
                null,
                null,
                command.requestHash(),
                command.idempotencyKey(),
                actorId,
                now
        );
        if (!employeeRepository.insertAgentIfAbsent(enterpriseAgent)) {
            var concurrentReplay = employeeRepository.findAgentByIdempotency(
                    tenantId,
                    actorId,
                    command.idempotencyKey()
            );
            if (concurrentReplay.isPresent()) {
                requireSameRequest(concurrentReplay.get().requestHash(), command.requestHash());
                return new CommandOutcome<>(concurrentReplay.get().toSummary(), true);
            }
            if (employeeRepository.existsAgentByCode(tenantId, command.employeeCode())) {
                throw new EmployeeCommandConflictException(
                        "ENTERPRISE_AGENT_CODE_ALREADY_EXISTS",
                        "employeeCode is already in use in the enterprise tenant"
                );
            }
            throw new EmployeeCommandConflictException(
                    "ENTERPRISE_AGENT_CONCURRENT_CONFLICT",
                    "enterprise agent could not be created because another write won"
            );
        }
        employeeRepository.insertStateEvent(new EnterpriseAgentStateEvent(
                enterpriseAgent.enterpriseAgentId(),
                tenantId,
                enterpriseAgent.enterpriseAgentId(),
                0,
                "HIRED",
                null,
                EnterpriseAgentStatus.DRAFT,
                null,
                command.requestHash(),
                command.idempotencyKey(),
                actorId,
                now
        ));
        return new CommandOutcome<>(enterpriseAgent.toSummary(), false);
    }

    @Override
    @Transactional
    public CommandOutcome<EnterpriseAgentDetail> createConfigurationVersion(
            CreateEnterpriseAgentConfigurationCommand command,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePermission(accessContext, EmployeePermissions.ENTERPRISE_AGENT_CONFIGURE);
        UUID tenantId = accessContext.tenantId().value();
        UUID actorId = accessContext.actorId().value();

        var replay = employeeRepository.findConfigurationByCreateIdempotency(
                tenantId,
                actorId,
                command.idempotencyKey()
        );
        if (replay.isPresent()) {
            requireSameConfigurationIntent(replay.get(), command.enterpriseAgentId(), command.requestHash());
            return new CommandOutcome<>(buildDetail(command.enterpriseAgentId(), accessContext), true);
        }

        var agent = employeeRepository.lockAgent(tenantId, command.enterpriseAgentId())
                .orElseThrow(EmployeeResourceNotDiscoverableException::new);
        if (agent.stateVersion() != command.expectedStateVersion()) {
            var concurrentReplay = employeeRepository.findConfigurationByCreateIdempotency(
                    tenantId,
                    actorId,
                    command.idempotencyKey()
            );
            if (concurrentReplay.isPresent()) {
                requireSameConfigurationIntent(
                        concurrentReplay.get(),
                        command.enterpriseAgentId(),
                        command.requestHash()
                );
                return new CommandOutcome<>(buildDetail(command.enterpriseAgentId(), accessContext), true);
            }
            throw new EmployeePreconditionFailedException();
        }
        requireDraftAgent(agent);
        lockPublishedBinding(agent, tenantId);

        Instant now = clock.instant();
        long resultingStateVersion = Math.addExact(agent.stateVersion(), 1);
        var configuration = new EnterpriseAgentConfigurationVersion(
                idGenerator.get(),
                tenantId,
                agent.enterpriseAgentId(),
                employeeRepository.nextConfigurationRevision(tenantId, agent.enterpriseAgentId()),
                command.displayNameSnapshot(),
                command.profile(),
                command.enterpriseInstructions(),
                command.modelPolicyMode(),
                command.knowledgeScopeMode(),
                command.visibilityScope(),
                EnterpriseAgentConfigurationStatus.DRAFT,
                command.requestHash(),
                command.idempotencyKey(),
                actorId,
                now,
                resultingStateVersion,
                null,
                null,
                null,
                null,
                null
        );
        if (!employeeRepository.insertConfigurationIfAbsent(configuration)) {
            var concurrentReplay = employeeRepository.findConfigurationByCreateIdempotency(
                    tenantId,
                    actorId,
                    command.idempotencyKey()
            );
            if (concurrentReplay.isPresent()) {
                requireSameConfigurationIntent(
                        concurrentReplay.get(),
                        command.enterpriseAgentId(),
                        command.requestHash()
                );
                return new CommandOutcome<>(buildDetail(command.enterpriseAgentId(), accessContext), true);
            }
            throw new EmployeeCommandConflictException(
                    "ENTERPRISE_AGENT_CONFIGURATION_CONCURRENT_CONFLICT",
                    "configuration version could not be created because another write won"
            );
        }
        employeeRepository.supersedeOtherDraftConfigurations(
                tenantId,
                agent.enterpriseAgentId(),
                configuration.configurationVersionId(),
                now
        );
        if (!employeeRepository.advanceAgentConfigurationState(
                tenantId,
                agent.enterpriseAgentId(),
                agent.stateVersion(),
                now
        )) {
            throw new EmployeePreconditionFailedException();
        }
        employeeRepository.insertStateEvent(new EnterpriseAgentStateEvent(
                configuration.configurationVersionId(),
                tenantId,
                agent.enterpriseAgentId(),
                resultingStateVersion,
                "CONFIGURATION_CREATED",
                EnterpriseAgentStatus.DRAFT,
                EnterpriseAgentStatus.DRAFT,
                configuration.configurationVersionId(),
                command.requestHash(),
                command.idempotencyKey(),
                actorId,
                now
        ));
        return new CommandOutcome<>(buildDetail(agent.enterpriseAgentId(), accessContext), false);
    }

    @Override
    @Transactional
    public CommandOutcome<EnterpriseAgentDetail> activate(
            ActivateEnterpriseAgentCommand command,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(command, "command must not be null");
        requirePermission(accessContext, EmployeePermissions.ENTERPRISE_AGENT_ACTIVATE);
        UUID tenantId = accessContext.tenantId().value();
        UUID actorId = accessContext.actorId().value();

        var replay = employeeRepository.findConfigurationByActivationIdempotency(
                tenantId,
                actorId,
                command.idempotencyKey()
        );
        if (replay.isPresent()) {
            requireSameActivationIntent(replay.get(), command);
            return new CommandOutcome<>(buildDetail(command.enterpriseAgentId(), accessContext), true);
        }

        var agent = employeeRepository.lockAgent(tenantId, command.enterpriseAgentId())
                .orElseThrow(EmployeeResourceNotDiscoverableException::new);
        if (agent.stateVersion() != command.expectedStateVersion()) {
            var concurrentReplay = employeeRepository.findConfigurationByActivationIdempotency(
                    tenantId,
                    actorId,
                    command.idempotencyKey()
            );
            if (concurrentReplay.isPresent()) {
                requireSameActivationIntent(concurrentReplay.get(), command);
                return new CommandOutcome<>(buildDetail(command.enterpriseAgentId(), accessContext), true);
            }
            throw new EmployeePreconditionFailedException();
        }
        requireDraftAgent(agent);
        lockPublishedBinding(agent, tenantId);
        var configuration = employeeRepository.findConfiguration(
                        tenantId,
                        agent.enterpriseAgentId(),
                        command.configurationVersionId()
                )
                .filter(candidate -> candidate.status() == EnterpriseAgentConfigurationStatus.DRAFT)
                .orElseThrow(EmployeeResourceNotDiscoverableException::new);

        Instant now = clock.instant();
        long resultingStateVersion = Math.addExact(agent.stateVersion(), 1);
        if (!employeeRepository.activateConfiguration(
                tenantId,
                agent.enterpriseAgentId(),
                configuration.configurationVersionId(),
                actorId,
                command.requestHash(),
                command.idempotencyKey(),
                resultingStateVersion,
                now
        )) {
            throw new EmployeeCommandConflictException(
                    "ENTERPRISE_AGENT_CONFIGURATION_NOT_ACTIVATABLE",
                    "configuration version is no longer draft"
            );
        }
        if (!employeeRepository.activateAgent(
                tenantId,
                agent.enterpriseAgentId(),
                configuration.configurationVersionId(),
                configuration.displayNameSnapshot(),
                actorId,
                agent.stateVersion(),
                now
        )) {
            throw new EmployeePreconditionFailedException();
        }
        employeeRepository.insertStateEvent(new EnterpriseAgentStateEvent(
                idGenerator.get(),
                tenantId,
                agent.enterpriseAgentId(),
                resultingStateVersion,
                "ACTIVATED",
                EnterpriseAgentStatus.DRAFT,
                EnterpriseAgentStatus.ACTIVE,
                configuration.configurationVersionId(),
                command.requestHash(),
                command.idempotencyKey(),
                actorId,
                now
        ));
        return new CommandOutcome<>(buildDetail(agent.enterpriseAgentId(), accessContext), false);
    }

    @Override
    @Transactional(readOnly = true)
    public List<PublishedAgentVersion> listPublished(PlatformAccessContext accessContext) {
        requirePlatformPermission(accessContext, EmployeePermissions.PLATFORM_TEMPLATE_READ);
        return employeeRepository.listPublishedVersions(MANAGEMENT_LIST_LIMIT).stream()
                .map(AgentVersion::toPublishedView)
                .toList();
    }

    @Override
    @Transactional(readOnly = true)
    public List<PublishedAgentVersion> listRecruitable(AccessContext accessContext) {
        requirePermission(accessContext, EmployeePermissions.ENTERPRISE_AGENT_HIRE);
        return employeeRepository.listRecruitableVersions(
                        accessContext.tenantId().value(),
                        MANAGEMENT_LIST_LIMIT
                ).stream()
                .map(AgentVersion::toPublishedView)
                .toList();
    }

    @Override
    @Transactional(readOnly = true)
    public List<EnterpriseAgentSummary> listManaged(AccessContext accessContext) {
        requirePermission(accessContext, EmployeePermissions.ENTERPRISE_AGENT_READ);
        return employeeRepository.listManagedAgents(
                accessContext.tenantId().value(),
                MANAGEMENT_LIST_LIMIT
        );
    }

    @Override
    @Transactional(readOnly = true)
    public EnterpriseAgentDetail getManagedDetail(UUID enterpriseAgentId, AccessContext accessContext) {
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        requirePermission(accessContext, EmployeePermissions.ENTERPRISE_AGENT_READ);
        return buildDetail(enterpriseAgentId, accessContext);
    }

    @Override
    @Transactional(readOnly = true)
    public List<ExecutableAgentSummary> listExecutableForOffice(AccessContext accessContext) {
        requirePermission(accessContext, EmployeePermissions.ENTERPRISE_AGENT_READ);
        return employeeRepository.listExecutableAgents(
                accessContext.tenantId().value(),
                OFFICE_AGENT_LIMIT
        );
    }

    @Override
    @Transactional(readOnly = true)
    public ExecutableAgentSummary requireExecutableForTask(
            UUID enterpriseAgentId,
            AccessContext accessContext
    ) {
        return requireExecutableForTask(enterpriseAgentId, null, accessContext);
    }

    @Override
    @Transactional(readOnly = true)
    public ExecutableAgentSummary requireExecutableForTask(
            UUID enterpriseAgentId,
            String requiredCapabilityCode,
            AccessContext accessContext
    ) {
        Objects.requireNonNull(enterpriseAgentId, "enterpriseAgentId must not be null");
        requirePermission(accessContext, EmployeePermissions.ENTERPRISE_AGENT_EXECUTE);
        var summary = employeeRepository.findExecutableAgent(
                        accessContext.tenantId().value(),
                        enterpriseAgentId
                )
                .orElseThrow(EmployeeResourceNotDiscoverableException::new);
        if (requiredCapabilityCode != null) {
            String normalizedCapability = requiredCapabilityCode.trim();
            if (normalizedCapability.isEmpty() || !summary.capabilityCode().equals(normalizedCapability)) {
                throw new EmployeeResourceNotDiscoverableException();
            }
        }
        return summary;
    }

    private static void requirePermission(AccessContext accessContext, String permission) {
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        if (!accessContext.authorities().contains(permission)) {
            throw new EmployeeAccessDeniedException(permission);
        }
    }

    private static void requirePlatformPermission(PlatformAccessContext accessContext, String permission) {
        Objects.requireNonNull(accessContext, "accessContext must not be null");
        if (!accessContext.authorities().contains(permission)) {
            throw new EmployeeAccessDeniedException(permission);
        }
    }

    private static void requireSameRequest(String storedRequestHash, String incomingRequestHash) {
        if (!Objects.equals(storedRequestHash, incomingRequestHash)) {
            throw new EmployeeCommandConflictException(
                    "IDEMPOTENCY_REQUEST_CONFLICT",
                    "the idempotency key was already used with a different request"
            );
        }
    }

    private EnterpriseAgentDetail buildDetail(UUID enterpriseAgentId, AccessContext accessContext) {
        UUID tenantId = accessContext.tenantId().value();
        var agent = employeeRepository.findAgent(tenantId, enterpriseAgentId)
                .orElseThrow(EmployeeResourceNotDiscoverableException::new);
        var version = employeeRepository.findVersion(agent.agentVersionId())
                .orElseThrow(EmployeeResourceNotDiscoverableException::new);
        var latestConfiguration = employeeRepository.findLatestConfiguration(tenantId, enterpriseAgentId);

        List<EnterpriseAgentReadinessBlocker> blockers = new ArrayList<>();
        if (version.status() != AgentVersionStatus.PUBLISHED) {
            blockers.add(new EnterpriseAgentReadinessBlocker(
                    "AGENT_VERSION_NOT_PUBLISHED",
                    "员工绑定的模板版本已不可用。"
            ));
        }
        if (agent.status() == EnterpriseAgentStatus.DRAFT) {
            if (latestConfiguration.isEmpty()) {
                blockers.add(new EnterpriseAgentReadinessBlocker(
                        "CONFIGURATION_REQUIRED",
                        "请先创建企业员工配置版本。"
                ));
            } else if (latestConfiguration.get().status() != EnterpriseAgentConfigurationStatus.DRAFT) {
                blockers.add(new EnterpriseAgentReadinessBlocker(
                        "DRAFT_CONFIGURATION_REQUIRED",
                        "没有可激活的草稿配置版本。"
                ));
            }
        } else if (agent.status() != EnterpriseAgentStatus.ACTIVE) {
            blockers.add(new EnterpriseAgentReadinessBlocker(
                    "EMPLOYEE_STATUS_NOT_READY",
                    "当前员工状态不可激活或执行。"
            ));
        }

        var readiness = new EnterpriseAgentReadiness(blockers.isEmpty(), blockers);
        var allowedActions = EnumSet.of(EnterpriseAgentAllowedAction.VIEW);
        if (agent.status() == EnterpriseAgentStatus.DRAFT
                && version.status() == AgentVersionStatus.PUBLISHED
                && accessContext.authorities().contains(EmployeePermissions.ENTERPRISE_AGENT_CONFIGURE)) {
            allowedActions.add(EnterpriseAgentAllowedAction.CREATE_CONFIGURATION_VERSION);
        }
        if (agent.status() == EnterpriseAgentStatus.DRAFT
                && readiness.ready()
                && accessContext.authorities().contains(EmployeePermissions.ENTERPRISE_AGENT_ACTIVATE)) {
            allowedActions.add(EnterpriseAgentAllowedAction.ACTIVATE);
        }

        return new EnterpriseAgentDetail(
                agent.toSummary(),
                new EnterpriseAgentTemplateSnapshot(
                        version.templateName(),
                        version.templateDescription(),
                        version.version(),
                        version.status()
                ),
                latestConfiguration.map(EmployeeApplicationService::toConfigurationSummary).orElse(null),
                readiness,
                allowedActions
        );
    }

    private static EnterpriseAgentConfigurationSummary toConfigurationSummary(
            EnterpriseAgentConfigurationVersion configuration
    ) {
        return new EnterpriseAgentConfigurationSummary(
                configuration.configurationVersionId(),
                configuration.revision(),
                configuration.displayNameSnapshot(),
                configuration.profile(),
                configuration.enterpriseInstructions(),
                configuration.modelPolicyMode(),
                configuration.knowledgeScopeMode(),
                configuration.visibilityScope(),
                configuration.status(),
                configuration.createdBy(),
                configuration.createdAt(),
                configuration.activatedBy(),
                configuration.activatedAt()
        );
    }

    private void lockPublishedBinding(EnterpriseAgent agent, UUID tenantId) {
        if (employeeRepository.lockRecruitableVersion(agent.agentVersionId(), tenantId).isEmpty()) {
            throw new EmployeeCommandConflictException(
                    "AGENT_VERSION_NOT_PUBLISHED",
                    "enterprise agent configuration requires its bound version to remain published"
            );
        }
    }

    private static void requireDraftAgent(EnterpriseAgent agent) {
        if (agent.status() != EnterpriseAgentStatus.DRAFT) {
            throw new EmployeeCommandConflictException(
                    "ENTERPRISE_AGENT_NOT_DRAFT",
                    "only draft enterprise agents can be configured or activated"
            );
        }
    }

    private static void requireSameConfigurationIntent(
            EnterpriseAgentConfigurationVersion stored,
            UUID enterpriseAgentId,
            String incomingRequestHash
    ) {
        if (!stored.enterpriseAgentId().equals(enterpriseAgentId)) {
            throw new EmployeeCommandConflictException(
                    "IDEMPOTENCY_REQUEST_CONFLICT",
                    "the idempotency key was already used for another enterprise employee"
            );
        }
        requireSameRequest(stored.createRequestHash(), incomingRequestHash);
    }

    private static void requireSameActivationIntent(
            EnterpriseAgentConfigurationVersion stored,
            ActivateEnterpriseAgentCommand command
    ) {
        if (!stored.enterpriseAgentId().equals(command.enterpriseAgentId())
                || !stored.configurationVersionId().equals(command.configurationVersionId())) {
            throw new EmployeeCommandConflictException(
                    "IDEMPOTENCY_REQUEST_CONFLICT",
                    "the idempotency key was already used for another activation"
            );
        }
        requireSameRequest(stored.activationRequestHash(), command.requestHash());
    }
}

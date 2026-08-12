package com.dianlian.platform.employee.application;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.employee.api.AgentVersionStatus;
import com.dianlian.platform.employee.api.ActivateEnterpriseAgentCommand;
import com.dianlian.platform.employee.api.CreateEnterpriseAgentConfigurationCommand;
import com.dianlian.platform.employee.api.EmployeeAccessDeniedException;
import com.dianlian.platform.employee.api.EmployeeCommandConflictException;
import com.dianlian.platform.employee.api.EmployeePermissions;
import com.dianlian.platform.employee.api.EmployeePreconditionFailedException;
import com.dianlian.platform.employee.api.EmployeeResourceNotDiscoverableException;
import com.dianlian.platform.employee.api.EnterpriseAgentStatus;
import com.dianlian.platform.employee.api.EnterpriseAgentAllowedAction;
import com.dianlian.platform.employee.api.EnterpriseAgentConfigurationStatus;
import com.dianlian.platform.employee.api.EnterpriseAgentKnowledgeScopeMode;
import com.dianlian.platform.employee.api.EnterpriseAgentModelPolicyMode;
import com.dianlian.platform.employee.api.EnterpriseAgentSummary;
import com.dianlian.platform.employee.api.EnterpriseAgentVisibilityScope;
import com.dianlian.platform.employee.api.EnterpriseVisibility;
import com.dianlian.platform.employee.api.ExecutableAgentSummary;
import com.dianlian.platform.employee.api.ExecutionExecutorType;
import com.dianlian.platform.employee.api.ExecutionStepDescriptor;
import com.dianlian.platform.employee.api.ExecutionTemplateDescriptor;
import com.dianlian.platform.employee.api.HireEnterpriseAgentCommand;
import com.dianlian.platform.employee.api.InputSchemaDescriptor;
import com.dianlian.platform.employee.api.PublishAgentVersionCommand;
import com.dianlian.platform.employee.domain.AgentTemplate;
import com.dianlian.platform.employee.domain.AgentVersion;
import com.dianlian.platform.employee.domain.EnterpriseAgent;
import com.dianlian.platform.employee.domain.EnterpriseAgentConfigurationVersion;
import com.dianlian.platform.employee.domain.EnterpriseAgentStateEvent;
import com.dianlian.platform.identity.api.AccessContext;
import com.dianlian.platform.identity.api.AccessContextFixtures;
import com.dianlian.platform.identity.api.PlatformAccessContext;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class EmployeeApplicationServiceTests {

    private static final UUID PLATFORM_ACTOR = UUID.fromString("10000000-0000-0000-0000-000000000002");
    private static final UUID ENTERPRISE_A = UUID.fromString("20000000-0000-0000-0000-000000000001");
    private static final UUID ENTERPRISE_B = UUID.fromString("30000000-0000-0000-0000-000000000001");
    private static final UUID ENTERPRISE_ACTOR = UUID.fromString("20000000-0000-0000-0000-000000000002");

    private InMemoryEmployeeRepository repository;
    private EmployeeApplicationService service;

    @BeforeEach
    void setUp() {
        repository = new InMemoryEmployeeRepository();
        AtomicLong sequence = new AtomicLong(10);
        service = new EmployeeApplicationService(
                repository,
                new EmployeeContractValidator(new ObjectMapper()),
                Clock.fixed(Instant.parse("2026-08-11T02:00:00Z"), ZoneOffset.UTC),
                () -> new UUID(0, sequence.getAndIncrement())
        );
    }

    @Test
    void publishedVersionIsIdempotentAndAppendOnly() {
        PlatformAccessContext publisher = platformContext(
                PLATFORM_ACTOR,
                EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH
        );
        PublishAgentVersionCommand command = publishCommand(
                EnterpriseVisibility.allEnterprises(),
                "publish-quotation-v1",
                "sha256:quotation-v1"
        );

        var first = service.publishVersion(command, publisher);
        var replay = service.publishVersion(command, publisher);

        assertThat(first.replayed()).isFalse();
        assertThat(replay.replayed()).isTrue();
        assertThat(replay.resource().agentVersionId()).isEqualTo(first.resource().agentVersionId());
        assertThat(replay.resource().capabilityCode()).isEqualTo("QUOTATION");
        assertThat(replay.resource().executionTemplate().steps()).hasSize(3);

        PublishAgentVersionCommand sameKeyDifferentRequest = publishCommand(
                EnterpriseVisibility.allEnterprises(),
                "publish-quotation-v1",
                "sha256:changed"
        );
        assertThatThrownBy(() -> service.publishVersion(sameKeyDifferentRequest, publisher))
                .isInstanceOf(EmployeeCommandConflictException.class)
                .extracting("code")
                .isEqualTo("IDEMPOTENCY_REQUEST_CONFLICT");

        PublishAgentVersionCommand overwriteVersion = new PublishAgentVersionCommand(
                command.templateCode(),
                "被修改的名称",
                command.templateDescription(),
                command.version(),
                command.capabilityCode(),
                command.inputSchema(),
                command.executionTemplate(),
                command.pointEstimate(),
                command.enterpriseVisibility(),
                "publish-quotation-v1-second-key",
                "sha256:second-key"
        );
        assertThatThrownBy(() -> service.publishVersion(overwriteVersion, publisher))
                .isInstanceOf(EmployeeCommandConflictException.class)
                .extracting("code")
                .isEqualTo("AGENT_VERSION_ALREADY_EXISTS");
        assertThat(repository.versions.values())
                .singleElement()
                .extracting(AgentVersion::templateName)
                .isEqualTo("报价专员");
    }

    @Test
    void enterpriseVisibilityAndTenantFiltersAreEnforcedBeforeDiscovery() {
        var published = service.publishVersion(
                publishCommand(
                        EnterpriseVisibility.allowlist(Set.of(ENTERPRISE_A)),
                        "publish-allowlist-v1",
                        "sha256:allowlist-v1"
                ),
                platformContext(PLATFORM_ACTOR, EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH)
        ).resource();

        assertThatThrownBy(() -> service.hire(
                hireCommand(published.agentVersionId(), "hire-b"),
                context(ENTERPRISE_B, ENTERPRISE_ACTOR, EmployeePermissions.ENTERPRISE_AGENT_HIRE)
        )).isInstanceOf(EmployeeResourceNotDiscoverableException.class);

        var hired = service.hire(
                hireCommand(published.agentVersionId(), "hire-a"),
                context(ENTERPRISE_A, ENTERPRISE_ACTOR, EmployeePermissions.ENTERPRISE_AGENT_HIRE)
        ).resource();
        activate(hired);

        var officeAgents = service.listExecutableForOffice(
                context(ENTERPRISE_A, ENTERPRISE_ACTOR, EmployeePermissions.ENTERPRISE_AGENT_READ)
        );
        assertThat(officeAgents)
                .extracting(ExecutableAgentSummary::enterpriseAgentId)
                .containsExactly(hired.enterpriseAgentId());
        assertThat(service.listExecutableForOffice(
                context(ENTERPRISE_B, ENTERPRISE_ACTOR, EmployeePermissions.ENTERPRISE_AGENT_READ)
        )).isEmpty();

        var executionProfile = service.requireExecutableForTask(
                hired.enterpriseAgentId(),
                context(ENTERPRISE_A, ENTERPRISE_ACTOR, EmployeePermissions.ENTERPRISE_AGENT_EXECUTE)
        );
        assertThat(executionProfile.inputSchema().schemaId()).isEqualTo("quotation.input");
        assertThat(executionProfile.roleName()).isEqualTo("报价专员");
        assertThat(executionProfile.profile()).isEqualTo("基于授权依据和确定性规则形成可复算成果");
        assertThat(executionProfile.enterpriseInstructions()).isEqualTo("仅使用企业已授权的数据。");
        assertThat(executionProfile.skillLabels()).isEmpty();
        assertThat(executionProfile.avatarUrl()).isNull();
        assertThat(executionProfile.executionTemplate().steps())
                .extracting(ExecutionStepDescriptor::stepKey)
                .containsExactly("understand", "calculate", "review");
        assertThat(executionProfile.pointEstimate()).isEqualTo(350);

        assertThatThrownBy(() -> service.requireExecutableForTask(
                hired.enterpriseAgentId(),
                "CONTRACT_REVIEW",
                context(ENTERPRISE_A, ENTERPRISE_ACTOR, EmployeePermissions.ENTERPRISE_AGENT_EXECUTE)
        )).isInstanceOf(EmployeeResourceNotDiscoverableException.class);
        assertThatThrownBy(() -> service.requireExecutableForTask(
                hired.enterpriseAgentId(),
                context(ENTERPRISE_B, ENTERPRISE_ACTOR, EmployeePermissions.ENTERPRISE_AGENT_EXECUTE)
        )).isInstanceOf(EmployeeResourceNotDiscoverableException.class);
    }

    @Test
    void permissionAndExecutableStatusFailClosed() {
        assertThatThrownBy(() -> service.publishVersion(
                publishCommand(EnterpriseVisibility.allEnterprises(), "publish-denied", "sha256:denied"),
                platformContext(PLATFORM_ACTOR)
        )).isInstanceOf(EmployeeAccessDeniedException.class);

        var published = service.publishVersion(
                publishCommand(EnterpriseVisibility.allEnterprises(), "publish-draft", "sha256:draft"),
                platformContext(PLATFORM_ACTOR, EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH)
        ).resource();
        var draftAgent = service.hire(
                hireCommand(published.agentVersionId(), "hire-draft"),
                context(ENTERPRISE_A, ENTERPRISE_ACTOR, EmployeePermissions.ENTERPRISE_AGENT_HIRE)
        ).resource();

        assertThat(service.listExecutableForOffice(
                context(ENTERPRISE_A, ENTERPRISE_ACTOR, EmployeePermissions.ENTERPRISE_AGENT_READ)
        )).isEmpty();
        assertThatThrownBy(() -> service.requireExecutableForTask(
                draftAgent.enterpriseAgentId(),
                context(ENTERPRISE_A, ENTERPRISE_ACTOR, EmployeePermissions.ENTERPRISE_AGENT_EXECUTE)
        )).isInstanceOf(EmployeeResourceNotDiscoverableException.class);
    }

    @Test
    void configurationAndActivationReplayBeforeStalePreconditionAndFreezeExecutionSnapshot() {
        var published = service.publishVersion(
                publishCommand(EnterpriseVisibility.allEnterprises(), "publish-config-flow", "sha256:publish-flow"),
                platformContext(PLATFORM_ACTOR, EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH)
        ).resource();
        var hired = service.hire(
                hireCommand(published.agentVersionId(), "hire-config-flow"),
                context(ENTERPRISE_A, ENTERPRISE_ACTOR, EmployeePermissions.ENTERPRISE_AGENT_HIRE)
        ).resource();
        var access = context(
                ENTERPRISE_A,
                ENTERPRISE_ACTOR,
                EmployeePermissions.ENTERPRISE_AGENT_READ,
                EmployeePermissions.ENTERPRISE_AGENT_CONFIGURE,
                EmployeePermissions.ENTERPRISE_AGENT_ACTIVATE,
                EmployeePermissions.ENTERPRISE_AGENT_EXECUTE
        );
        var createCommand = new CreateEnterpriseAgentConfigurationCommand(
                hired.enterpriseAgentId(),
                0,
                "企业报价顾问",
                "按企业规范形成可复核成果",
                "引用依据并标明假设。",
                EnterpriseAgentModelPolicyMode.PLATFORM_DEFAULT,
                EnterpriseAgentKnowledgeScopeMode.NONE,
                EnterpriseAgentVisibilityScope.TENANT,
                "configure-flow-00000001",
                "sha256:configure-flow"
        );

        var configured = service.createConfigurationVersion(createCommand, access);
        var configureReplay = service.createConfigurationVersion(createCommand, access);

        assertThat(configured.replayed()).isFalse();
        assertThat(configured.resource().agent().stateVersion()).isEqualTo(1);
        assertThat(configureReplay.replayed()).isTrue();
        assertThat(configureReplay.resource().agent().stateVersion()).isEqualTo(1);
        assertThat(configured.resource().allowedActions())
                .contains(EnterpriseAgentAllowedAction.ACTIVATE);

        assertThatThrownBy(() -> service.createConfigurationVersion(
                new CreateEnterpriseAgentConfigurationCommand(
                        hired.enterpriseAgentId(),
                        0,
                        "过期写入",
                        "过期写入",
                        "",
                        EnterpriseAgentModelPolicyMode.PLATFORM_DEFAULT,
                        EnterpriseAgentKnowledgeScopeMode.NONE,
                        EnterpriseAgentVisibilityScope.TENANT,
                        "configure-flow-00000002",
                        "sha256:configure-stale"
                ),
                access
        )).isInstanceOf(EmployeePreconditionFailedException.class);

        var activateCommand = new ActivateEnterpriseAgentCommand(
                hired.enterpriseAgentId(),
                configured.resource().latestConfiguration().configurationVersionId(),
                1,
                "activate-flow-00000001",
                "sha256:activate-flow"
        );
        var activated = service.activate(activateCommand, access);
        var activationReplay = service.activate(activateCommand, access);

        assertThat(activated.resource().agent().status()).isEqualTo(EnterpriseAgentStatus.ACTIVE);
        assertThat(activated.resource().agent().stateVersion()).isEqualTo(2);
        assertThat(activationReplay.replayed()).isTrue();
        var executable = service.requireExecutableForTask(hired.enterpriseAgentId(), access);
        assertThat(executable.configurationVersionId())
                .isEqualTo(configured.resource().latestConfiguration().configurationVersionId());
        assertThat(executable.displayName()).isEqualTo("企业报价顾问");
        assertThat(executable.profile()).isEqualTo("按企业规范形成可复核成果");
        assertThat(executable.enterpriseInstructions()).isEqualTo("引用依据并标明假设。");

        assertThatThrownBy(() -> service.getManagedDetail(
                hired.enterpriseAgentId(),
                context(ENTERPRISE_B, ENTERPRISE_ACTOR, EmployeePermissions.ENTERPRISE_AGENT_READ)
        )).isInstanceOf(EmployeeResourceNotDiscoverableException.class);
    }

    @Test
    void executionTemplateRejectsDependencyCycles() {
        assertThatThrownBy(() -> new ExecutionTemplateDescriptor(
                "cyclic.template",
                "1.0.0",
                List.of(
                        step("first", ExecutionExecutorType.MODEL, List.of("second"), false),
                        step("second", ExecutionExecutorType.TOOL, List.of("first"), false)
                )
        )).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("cycle");
    }

    @Test
    void managementQueriesRespectPlatformTenantAndPermissionBoundaries() {
        var published = service.publishVersion(
                publishCommand(EnterpriseVisibility.allowlist(Set.of(ENTERPRISE_A)), "publish-management", "hash-a"),
                platformContext(PLATFORM_ACTOR, EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH)
        ).resource();
        service.hire(
                hireCommand(published.agentVersionId(), "hire-management"),
                context(ENTERPRISE_A, ENTERPRISE_ACTOR, EmployeePermissions.ENTERPRISE_AGENT_HIRE)
        );

        assertThat(service.listPublished(platformContext(
                PLATFORM_ACTOR,
                EmployeePermissions.PLATFORM_TEMPLATE_READ,
                EmployeePermissions.PLATFORM_TEMPLATE_PUBLISH
        ))).extracting(item -> item.agentVersionId()).containsExactly(published.agentVersionId());
        assertThat(service.listRecruitable(context(
                ENTERPRISE_A,
                ENTERPRISE_ACTOR,
                EmployeePermissions.ENTERPRISE_AGENT_HIRE
        ))).hasSize(1);
        assertThat(service.listRecruitable(context(
                ENTERPRISE_B,
                ENTERPRISE_ACTOR,
                EmployeePermissions.ENTERPRISE_AGENT_HIRE
        ))).isEmpty();
        assertThat(service.listManaged(context(
                ENTERPRISE_A,
                ENTERPRISE_ACTOR,
                EmployeePermissions.ENTERPRISE_AGENT_READ
        ))).extracting(EnterpriseAgentSummary::agentVersionId).containsExactly(published.agentVersionId());
        assertThatThrownBy(() -> service.listManaged(context(ENTERPRISE_A, ENTERPRISE_ACTOR)))
                .isInstanceOf(EmployeeAccessDeniedException.class);
    }

    @Test
    void publicCodesFollowTheFrozenOpenApiPatterns() {
        assertThatThrownBy(() -> new InputSchemaDescriptor(
                "Quotation.Input",
                "1.0.0",
                "{\"type\":\"object\"}"
        )).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("public contract");

        var valid = publishCommand(
                EnterpriseVisibility.allEnterprises(),
                "invalid-capability",
                "sha256:invalid-capability"
        );
        assertThatThrownBy(() -> new PublishAgentVersionCommand(
                valid.templateCode(),
                valid.templateName(),
                valid.templateDescription(),
                valid.version(),
                "quotation",
                valid.inputSchema(),
                valid.executionTemplate(),
                valid.pointEstimate(),
                valid.enterpriseVisibility(),
                valid.idempotencyKey(),
                valid.requestHash()
        )).isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("public contract");
    }

    private static PublishAgentVersionCommand publishCommand(
            EnterpriseVisibility visibility,
            String idempotencyKey,
            String requestHash
    ) {
        return new PublishAgentVersionCommand(
                "quotation-specialist",
                "报价专员",
                "基于授权依据和确定性规则形成可复算成果",
                "1.0.0",
                "QUOTATION",
                new InputSchemaDescriptor(
                        "quotation.input",
                        "1.0.0",
                        "{\"type\":\"object\",\"additionalProperties\":false}"
                ),
                new ExecutionTemplateDescriptor(
                        "quotation.standard",
                        "1.0.0",
                        List.of(
                                step("understand", ExecutionExecutorType.MODEL, List.of(), false),
                                step("calculate", ExecutionExecutorType.RULE_ENGINE, List.of("understand"), false),
                                step("review", ExecutionExecutorType.HUMAN_CHECKPOINT, List.of("calculate"), true)
                        )
                ),
                350,
                visibility,
                idempotencyKey,
                requestHash
        );
    }

    private static HireEnterpriseAgentCommand hireCommand(UUID versionId, String idempotencyKey) {
        return new HireEnterpriseAgentCommand(
                versionId,
                "quotation-001",
                "报价专员小联",
                idempotencyKey,
                "sha256:" + idempotencyKey
        );
    }

    private void activate(EnterpriseAgentSummary hired) {
        var access = context(
                ENTERPRISE_A,
                ENTERPRISE_ACTOR,
                EmployeePermissions.ENTERPRISE_AGENT_CONFIGURE,
                EmployeePermissions.ENTERPRISE_AGENT_ACTIVATE
        );
        var configured = service.createConfigurationVersion(
                new CreateEnterpriseAgentConfigurationCommand(
                        hired.enterpriseAgentId(),
                        hired.stateVersion(),
                        hired.displayName(),
                        "基于授权依据和确定性规则形成可复算成果",
                        "仅使用企业已授权的数据。",
                        EnterpriseAgentModelPolicyMode.PLATFORM_DEFAULT,
                        EnterpriseAgentKnowledgeScopeMode.NONE,
                        EnterpriseAgentVisibilityScope.TENANT,
                        "configure-quotation-0001",
                        "sha256:configure-quotation-0001"
                ),
                access
        ).resource();
        service.activate(
                new ActivateEnterpriseAgentCommand(
                        hired.enterpriseAgentId(),
                        configured.latestConfiguration().configurationVersionId(),
                        configured.agent().stateVersion(),
                        "activate-quotation-0001",
                        "sha256:activate-quotation-0001"
                ),
                access
        );
    }

    private static ExecutionStepDescriptor step(
            String stepKey,
            ExecutionExecutorType executorType,
            List<String> dependsOn,
            boolean humanCheckpoint
    ) {
        return new ExecutionStepDescriptor(
                stepKey,
                stepKey,
                executorType,
                dependsOn,
                null,
                null,
                humanCheckpoint
        );
    }

    private static AccessContext context(UUID tenantId, UUID actorId, String... permissions) {
        return AccessContextFixtures.authenticated(tenantId, actorId, permissions);
    }

    private static PlatformAccessContext platformContext(UUID actorId, String... permissions) {
        return PlatformAccessContext.fromAuthenticatedPrincipal(
                AccessContextFixtures.platformPrincipal(actorId, permissions)
        );
    }

    private static final class InMemoryEmployeeRepository implements EmployeeRepository {

        private final Map<String, AgentTemplate> templatesByNaturalKey = new HashMap<>();
        private final Map<UUID, AgentVersion> versions = new LinkedHashMap<>();
        private final Map<UUID, EnterpriseAgent> agents = new LinkedHashMap<>();
        private final Map<UUID, EnterpriseAgentConfigurationVersion> configurations = new LinkedHashMap<>();

        @Override
        public Optional<AgentVersion> findVersionByIdempotency(
                UUID actorId,
                String idempotencyKey
        ) {
            return versions.values().stream()
                    .filter(version -> version.publishedBy().equals(actorId))
                    .filter(version -> version.publishIdempotencyKey().equals(idempotencyKey))
                    .findFirst();
        }

        @Override
        public AgentTemplate getOrCreateTemplate(AgentTemplate proposedTemplate) {
            return templatesByNaturalKey.computeIfAbsent(
                    proposedTemplate.templateCode(),
                    ignored -> proposedTemplate
            );
        }

        @Override
        public Optional<AgentVersion> findVersionByTemplateAndLabel(
                UUID templateId,
                String version
        ) {
            return versions.values().stream()
                    .filter(candidate -> candidate.templateId().equals(templateId))
                    .filter(candidate -> candidate.version().equals(version))
                    .findFirst();
        }

        @Override
        public boolean insertVersionIfAbsent(AgentVersion version) {
            if (versions.putIfAbsent(version.agentVersionId(), version) != null) {
                return false;
            }
            return true;
        }

        @Override
        public List<AgentVersion> listPublishedVersions(int limit) {
            return versions.values().stream()
                    .filter(version -> version.status() == AgentVersionStatus.PUBLISHED)
                    .limit(limit)
                    .toList();
        }

        @Override
        public List<AgentVersion> listRecruitableVersions(UUID enterpriseTenantId, int limit) {
            return versions.values().stream()
                    .filter(version -> version.status() == AgentVersionStatus.PUBLISHED)
                    .filter(version -> version.enterpriseVisibility().includes(enterpriseTenantId))
                    .limit(limit)
                    .toList();
        }

        @Override
        public Optional<AgentVersion> findRecruitableVersion(UUID agentVersionId, UUID enterpriseTenantId) {
            return Optional.ofNullable(versions.get(agentVersionId))
                    .filter(version -> version.status() == AgentVersionStatus.PUBLISHED)
                    .filter(version -> version.enterpriseVisibility().includes(enterpriseTenantId));
        }

        @Override
        public Optional<AgentVersion> lockRecruitableVersion(UUID agentVersionId, UUID enterpriseTenantId) {
            return findRecruitableVersion(agentVersionId, enterpriseTenantId);
        }

        @Override
        public Optional<AgentVersion> findVersion(UUID agentVersionId) {
            return Optional.ofNullable(versions.get(agentVersionId));
        }

        @Override
        public Optional<EnterpriseAgent> findAgentByIdempotency(
                UUID tenantId,
                UUID actorId,
                String idempotencyKey
        ) {
            return agents.values().stream()
                    .filter(agent -> agent.tenantId().equals(tenantId))
                    .filter(agent -> agent.hiredBy().equals(actorId))
                    .filter(agent -> agent.hireIdempotencyKey().equals(idempotencyKey))
                    .findFirst();
        }

        @Override
        public boolean insertAgentIfAbsent(EnterpriseAgent agent) {
            if (agents.values().stream()
                    .anyMatch(existing -> existing.tenantId().equals(agent.tenantId())
                            && existing.employeeCode().equals(agent.employeeCode()))) {
                return false;
            }
            return agents.putIfAbsent(agent.enterpriseAgentId(), agent) == null;
        }

        @Override
        public boolean existsAgentByCode(UUID tenantId, String employeeCode) {
            return agents.values().stream()
                    .anyMatch(agent -> agent.tenantId().equals(tenantId)
                            && agent.employeeCode().equals(employeeCode));
        }

        @Override
        public Optional<EnterpriseAgent> findAgent(UUID tenantId, UUID enterpriseAgentId) {
            return Optional.ofNullable(agents.get(enterpriseAgentId))
                    .filter(agent -> agent.tenantId().equals(tenantId));
        }

        @Override
        public Optional<EnterpriseAgent> lockAgent(UUID tenantId, UUID enterpriseAgentId) {
            return findAgent(tenantId, enterpriseAgentId);
        }

        @Override
        public Optional<EnterpriseAgentConfigurationVersion> findConfigurationByCreateIdempotency(
                UUID tenantId,
                UUID actorId,
                String idempotencyKey
        ) {
            return configurations.values().stream()
                    .filter(configuration -> configuration.tenantId().equals(tenantId))
                    .filter(configuration -> configuration.createdBy().equals(actorId))
                    .filter(configuration -> configuration.createIdempotencyKey().equals(idempotencyKey))
                    .findFirst();
        }

        @Override
        public Optional<EnterpriseAgentConfigurationVersion> findConfigurationByActivationIdempotency(
                UUID tenantId,
                UUID actorId,
                String idempotencyKey
        ) {
            return configurations.values().stream()
                    .filter(configuration -> configuration.tenantId().equals(tenantId))
                    .filter(configuration -> actorId.equals(configuration.activatedBy()))
                    .filter(configuration -> idempotencyKey.equals(configuration.activationIdempotencyKey()))
                    .findFirst();
        }

        @Override
        public Optional<EnterpriseAgentConfigurationVersion> findConfiguration(
                UUID tenantId,
                UUID enterpriseAgentId,
                UUID configurationVersionId
        ) {
            return Optional.ofNullable(configurations.get(configurationVersionId))
                    .filter(configuration -> configuration.tenantId().equals(tenantId))
                    .filter(configuration -> configuration.enterpriseAgentId().equals(enterpriseAgentId));
        }

        @Override
        public Optional<EnterpriseAgentConfigurationVersion> findLatestConfiguration(
                UUID tenantId,
                UUID enterpriseAgentId
        ) {
            return configurations.values().stream()
                    .filter(configuration -> configuration.tenantId().equals(tenantId))
                    .filter(configuration -> configuration.enterpriseAgentId().equals(enterpriseAgentId))
                    .max(Comparator.comparingLong(EnterpriseAgentConfigurationVersion::revision));
        }

        @Override
        public long nextConfigurationRevision(UUID tenantId, UUID enterpriseAgentId) {
            return findLatestConfiguration(tenantId, enterpriseAgentId)
                    .map(EnterpriseAgentConfigurationVersion::revision)
                    .orElse(0L) + 1;
        }

        @Override
        public boolean insertConfigurationIfAbsent(EnterpriseAgentConfigurationVersion configuration) {
            if (findConfigurationByCreateIdempotency(
                    configuration.tenantId(),
                    configuration.createdBy(),
                    configuration.createIdempotencyKey()
            ).isPresent()) {
                return false;
            }
            return configurations.putIfAbsent(configuration.configurationVersionId(), configuration) == null;
        }

        @Override
        public void supersedeOtherDraftConfigurations(
                UUID tenantId,
                UUID enterpriseAgentId,
                UUID retainedConfigurationVersionId,
                Instant now
        ) {
            configurations.values().stream()
                    .filter(configuration -> configuration.tenantId().equals(tenantId))
                    .filter(configuration -> configuration.enterpriseAgentId().equals(enterpriseAgentId))
                    .filter(configuration -> !configuration.configurationVersionId()
                            .equals(retainedConfigurationVersionId))
                    .filter(configuration -> configuration.status() == EnterpriseAgentConfigurationStatus.DRAFT)
                    .toList()
                    .forEach(configuration -> configurations.put(
                            configuration.configurationVersionId(),
                            copyConfiguration(
                                    configuration,
                                    EnterpriseAgentConfigurationStatus.SUPERSEDED,
                                    null,
                                    null,
                                    null,
                                    null,
                                    null
                            )
                    ));
        }

        @Override
        public boolean advanceAgentConfigurationState(
                UUID tenantId,
                UUID enterpriseAgentId,
                long expectedStateVersion,
                Instant now
        ) {
            var agent = findAgent(tenantId, enterpriseAgentId).orElse(null);
            if (agent == null || agent.status() != EnterpriseAgentStatus.DRAFT
                    || agent.stateVersion() != expectedStateVersion) {
                return false;
            }
            agents.put(enterpriseAgentId, copyAgent(
                    agent,
                    agent.displayName(),
                    EnterpriseAgentStatus.DRAFT,
                    expectedStateVersion + 1,
                    null,
                    null,
                    null
            ));
            return true;
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
            var configuration = findConfiguration(tenantId, enterpriseAgentId, configurationVersionId).orElse(null);
            if (configuration == null || configuration.status() != EnterpriseAgentConfigurationStatus.DRAFT) {
                return false;
            }
            configurations.put(configurationVersionId, copyConfiguration(
                    configuration,
                    EnterpriseAgentConfigurationStatus.ACTIVE,
                    requestHash,
                    idempotencyKey,
                    actorId,
                    now,
                    activationResultStateVersion
            ));
            return true;
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
            var agent = findAgent(tenantId, enterpriseAgentId).orElse(null);
            if (agent == null || agent.status() != EnterpriseAgentStatus.DRAFT
                    || agent.stateVersion() != expectedStateVersion) {
                return false;
            }
            agents.put(enterpriseAgentId, copyAgent(
                    agent,
                    displayName,
                    EnterpriseAgentStatus.ACTIVE,
                    expectedStateVersion + 1,
                    configurationVersionId,
                    actorId,
                    now
            ));
            return true;
        }

        @Override
        public void insertStateEvent(EnterpriseAgentStateEvent event) {
            // State events are covered by the JDBC integration slice; the in-memory port keeps behavior only.
        }

        @Override
        public List<EnterpriseAgentSummary> listManagedAgents(UUID tenantId, int limit) {
            return agents.values().stream()
                    .filter(agent -> agent.tenantId().equals(tenantId))
                    .map(EnterpriseAgent::toSummary)
                    .limit(limit)
                    .toList();
        }

        @Override
        public Optional<ExecutableAgentSummary> findExecutableAgent(UUID tenantId, UUID enterpriseAgentId) {
            return Optional.ofNullable(agents.get(enterpriseAgentId))
                    .filter(agent -> agent.tenantId().equals(tenantId))
                    .filter(agent -> agent.status().executable())
                    .flatMap(this::toExecutable);
        }

        @Override
        public List<ExecutableAgentSummary> listExecutableAgents(UUID tenantId, int limit) {
            return agents.values().stream()
                    .filter(agent -> agent.tenantId().equals(tenantId))
                    .filter(agent -> agent.status().executable())
                    .map(this::toExecutable)
                    .flatMap(Optional::stream)
                    .sorted(Comparator.comparing(ExecutableAgentSummary::displayName))
                    .limit(limit)
                    .toList();
        }

        private Optional<ExecutableAgentSummary> toExecutable(EnterpriseAgent agent) {
            return Optional.ofNullable(versions.get(agent.agentVersionId()))
                    .filter(version -> version.status() == AgentVersionStatus.PUBLISHED)
                    .flatMap(version -> findConfiguration(
                            agent.tenantId(),
                            agent.enterpriseAgentId(),
                            agent.activeConfigurationVersionId()
                    ).filter(configuration -> configuration.status() == EnterpriseAgentConfigurationStatus.ACTIVE)
                    .map(configuration -> new ExecutableAgentSummary(
                            agent.enterpriseAgentId(),
                            agent.templateId(),
                            agent.agentVersionId(),
                            configuration.configurationVersionId(),
                            version.templateCode(),
                            configuration.displayNameSnapshot(),
                            version.templateName(),
                            configuration.profile(),
                            configuration.enterpriseInstructions(),
                            configuration.modelPolicyMode(),
                            configuration.knowledgeScopeMode(),
                            List.of(),
                            null,
                            version.capabilityCode(),
                            version.inputSchema(),
                            version.executionTemplate(),
                            version.pointEstimate(),
                            agent.status(),
                            version.status()
                    )));
        }

        private static EnterpriseAgent copyAgent(
                EnterpriseAgent source,
                String displayName,
                EnterpriseAgentStatus status,
                long stateVersion,
                UUID activeConfigurationVersionId,
                UUID activatedBy,
                Instant activatedAt
        ) {
            return new EnterpriseAgent(
                    source.enterpriseAgentId(),
                    source.tenantId(),
                    source.templateId(),
                    source.agentVersionId(),
                    source.employeeCode(),
                    displayName,
                    source.capabilityCode(),
                    status,
                    stateVersion,
                    activeConfigurationVersionId,
                    activatedBy,
                    activatedAt,
                    source.requestHash(),
                    source.hireIdempotencyKey(),
                    source.hiredBy(),
                    source.hiredAt()
            );
        }

        private static EnterpriseAgentConfigurationVersion copyConfiguration(
                EnterpriseAgentConfigurationVersion source,
                EnterpriseAgentConfigurationStatus status,
                String activationRequestHash,
                String activationIdempotencyKey,
                UUID activatedBy,
                Instant activatedAt,
                Long activationResultStateVersion
        ) {
            return new EnterpriseAgentConfigurationVersion(
                    source.configurationVersionId(),
                    source.tenantId(),
                    source.enterpriseAgentId(),
                    source.revision(),
                    source.displayNameSnapshot(),
                    source.profile(),
                    source.enterpriseInstructions(),
                    source.modelPolicyMode(),
                    source.knowledgeScopeMode(),
                    source.visibilityScope(),
                    status,
                    source.createRequestHash(),
                    source.createIdempotencyKey(),
                    source.createdBy(),
                    source.createdAt(),
                    source.createResultStateVersion(),
                    activationRequestHash,
                    activationIdempotencyKey,
                    activatedBy,
                    activatedAt,
                    activationResultStateVersion
            );
        }
    }
}

package com.dianlian.platform.integration.infrastructure.runtime;

import static com.dianlian.platform.identity.api.AccessContextFixtures.authenticated;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.task.api.AgentRuntimePort;
import com.dianlian.platform.task.api.RuntimeUnavailableException;
import com.dianlian.platform.task.application.TaskExecutionApplicationService;
import com.dianlian.platform.task.domain.ExecutionGeneration;
import com.dianlian.platform.task.domain.TaskStepExecution;
import java.time.Instant;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;

class DisabledAgentRuntimePortTests {

    private final ApplicationContextRunner contextRunner = new ApplicationContextRunner()
            .withUserConfiguration(RuntimeIntegrationConfiguration.class)
            .withPropertyValues("runtime.enabled=false");

    @Test
    void failsClosedWithoutChangingThePreparedExecution() {
        var execution = TaskStepExecution.prepare(
                UUID.fromString("10000000-0000-0000-0000-000000000001"),
                ExecutionGeneration.initial(),
                UUID.fromString("20000000-0000-0000-0000-000000000001"),
                Instant.parse("2026-01-01T00:00:00Z")
        );
        var before = execution;

        contextRunner.run(context -> {
            assertThat(context).hasNotFailed();
            var service = new TaskExecutionApplicationService(context.getBean(AgentRuntimePort.class));

            assertThatThrownBy(() -> service.start(
                    execution,
                    "runtime-disabled-test",
                    "request-hash",
                    authenticated()
            ))
                    .isInstanceOf(RuntimeUnavailableException.class)
                    .hasMessage("Python Agent Runtime is disabled");

            assertThat(execution).isEqualTo(before);
        });
    }
}

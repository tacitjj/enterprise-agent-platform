package com.dianlian.platform.task.infrastructure;

import com.dianlian.platform.task.application.TaskExecutionApplicationService;
import java.lang.management.ManagementFactory;
import java.util.UUID;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "dianlian.task", name = "worker-enabled", havingValue = "true")
public class TaskExecutionWorker {

    private final TaskExecutionApplicationService service;
    private final String workerId = ManagementFactory.getRuntimeMXBean().getName() + ":" + UUID.randomUUID();

    public TaskExecutionWorker(TaskExecutionApplicationService service) {
        this.service = service;
    }

    @Scheduled(fixedDelayString = "${dianlian.task.worker-delay-ms:1000}")
    void poll() {
        int processed = 0;
        while (processed < 20 && service.processNext(workerId)) {
            processed++;
        }
    }
}

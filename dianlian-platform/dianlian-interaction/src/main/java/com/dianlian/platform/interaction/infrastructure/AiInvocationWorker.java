package com.dianlian.platform.interaction.infrastructure;

import com.dianlian.platform.interaction.application.AiInvocationProcessor;
import java.lang.management.ManagementFactory;
import java.util.UUID;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "dianlian.interaction", name = "worker-enabled", havingValue = "true")
public class AiInvocationWorker {

    private final AiInvocationProcessor processor;
    private final String workerId = ManagementFactory.getRuntimeMXBean().getName() + ":" + UUID.randomUUID();

    public AiInvocationWorker(AiInvocationProcessor processor) {
        this.processor = processor;
    }

    @Scheduled(fixedDelayString = "${dianlian.interaction.worker-delay-ms:1000}")
    void poll() {
        int processed = 0;
        while (processed < 20 && processor.processNext(workerId)) {
            processed++;
        }
    }
}

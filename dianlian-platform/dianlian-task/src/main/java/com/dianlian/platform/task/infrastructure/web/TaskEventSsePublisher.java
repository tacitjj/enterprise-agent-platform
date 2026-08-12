package com.dianlian.platform.task.infrastructure.web;

import com.dianlian.platform.identity.api.AccessContext;
import java.util.UUID;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

public interface TaskEventSsePublisher {

    SseEmitter open(UUID taskId, String afterEventId, UUID sessionId, AccessContext accessContext);
}

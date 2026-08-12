package com.dianlian.platform.task.application;

import com.dianlian.platform.task.api.CreateTaskCommand;
import java.util.List;
import java.util.UUID;

public interface TaskPayloadSerializer {

    HashedTaskRequest hash(CreateTaskCommand command);

    String serialize(Object value);

    List<UUID> readUuidList(String json);
}

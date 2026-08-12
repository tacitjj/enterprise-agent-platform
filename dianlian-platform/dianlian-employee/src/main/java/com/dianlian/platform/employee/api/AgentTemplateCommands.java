package com.dianlian.platform.employee.api;

import com.dianlian.platform.identity.api.PlatformAccessContext;

public interface AgentTemplateCommands {

    CommandOutcome<PublishedAgentVersion> publishVersion(
            PublishAgentVersionCommand command,
            PlatformAccessContext accessContext
    );
}

@org.springframework.modulith.ApplicationModule(
        displayName = "Integration",
        allowedDependencies = {
                "identity :: api",
                "task :: api",
                "context :: api",
                "knowledge :: api",
                "memory :: api"
        }
)
package com.dianlian.platform.integration;

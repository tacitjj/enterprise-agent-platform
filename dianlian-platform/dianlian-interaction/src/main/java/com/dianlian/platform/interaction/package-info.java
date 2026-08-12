@org.springframework.modulith.ApplicationModule(
        displayName = "Interaction",
        allowedDependencies = {
                "identity :: api",
                "employee :: api",
                "billing :: api",
                "memory :: api",
                "context :: api",
                "model :: api"
        }
)
package com.dianlian.platform.interaction;

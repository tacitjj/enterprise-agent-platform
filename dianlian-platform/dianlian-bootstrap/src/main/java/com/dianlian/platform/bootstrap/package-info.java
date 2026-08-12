@org.springframework.modulith.ApplicationModule(
        displayName = "Bootstrap",
        allowedDependencies = {
                "identity :: api",
                "employee :: api",
                "billing :: api",
                "task :: api",
                "context :: api",
                "model :: api",
                "interaction :: api"
        }
)
package com.dianlian.platform.bootstrap;

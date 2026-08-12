@org.springframework.modulith.ApplicationModule(
        displayName = "Task",
        allowedDependencies = {"identity :: api", "employee :: api", "billing :: api", "model :: api"}
)
package com.dianlian.platform.task;

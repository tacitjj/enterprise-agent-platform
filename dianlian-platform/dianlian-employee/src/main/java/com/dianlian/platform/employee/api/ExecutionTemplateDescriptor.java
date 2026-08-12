package com.dianlian.platform.employee.api;

import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

public record ExecutionTemplateDescriptor(
        String templateCode,
        String version,
        List<ExecutionStepDescriptor> steps
) {

    public ExecutionTemplateDescriptor {
        templateCode = EmployeeValueChecks.stableCode(templateCode, "templateCode", 96);
        version = EmployeeValueChecks.nonBlank(version, "version", 32);
        steps = List.copyOf(Objects.requireNonNull(steps, "steps must not be null"));
        if (steps.isEmpty()) {
            throw new IllegalArgumentException("execution template requires at least one step");
        }
        validateGraph(steps);
    }

    private static void validateGraph(List<ExecutionStepDescriptor> steps) {
        Map<String, ExecutionStepDescriptor> byKey = new HashMap<>();
        for (ExecutionStepDescriptor step : steps) {
            if (byKey.put(step.stepKey(), step) != null) {
                throw new IllegalArgumentException("duplicate execution step: " + step.stepKey());
            }
        }
        for (ExecutionStepDescriptor step : steps) {
            for (String dependency : step.dependsOn()) {
                if (!byKey.containsKey(dependency)) {
                    throw new IllegalArgumentException("unknown execution dependency: " + dependency);
                }
                if (dependency.equals(step.stepKey())) {
                    throw new IllegalArgumentException("execution step cannot depend on itself: " + dependency);
                }
            }
        }
        Set<String> visiting = new HashSet<>();
        Set<String> visited = new HashSet<>();
        for (String stepKey : byKey.keySet()) {
            ensureAcyclic(stepKey, byKey, visiting, visited);
        }
    }

    private static void ensureAcyclic(
            String stepKey,
            Map<String, ExecutionStepDescriptor> byKey,
            Set<String> visiting,
            Set<String> visited
    ) {
        if (visited.contains(stepKey)) {
            return;
        }
        if (!visiting.add(stepKey)) {
            throw new IllegalArgumentException("execution template contains a dependency cycle");
        }
        for (String dependency : byKey.get(stepKey).dependsOn()) {
            ensureAcyclic(dependency, byKey, visiting, visited);
        }
        visiting.remove(stepKey);
        visited.add(stepKey);
    }
}

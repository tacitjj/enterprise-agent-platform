package com.dianlian.platform.employee.application;

import com.dianlian.platform.employee.api.InputSchemaDescriptor;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Objects;

final class EmployeeContractValidator {

    private final ObjectMapper objectMapper;

    EmployeeContractValidator(ObjectMapper objectMapper) {
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
    }

    void requireObjectSchema(InputSchemaDescriptor inputSchema) {
        try {
            var root = objectMapper.readTree(inputSchema.jsonSchema());
            if (root == null || !root.isObject()) {
                throw new IllegalArgumentException("inputSchema.jsonSchema must be a JSON object");
            }
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("inputSchema.jsonSchema must be valid JSON", exception);
        }
    }
}

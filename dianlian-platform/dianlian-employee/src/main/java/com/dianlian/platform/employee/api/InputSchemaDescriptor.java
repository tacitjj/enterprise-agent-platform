package com.dianlian.platform.employee.api;

public record InputSchemaDescriptor(String schemaId, String version, String jsonSchema) {

    public InputSchemaDescriptor {
        schemaId = EmployeeValueChecks.schemaId(schemaId);
        version = EmployeeValueChecks.nonBlank(version, "version", 32);
        jsonSchema = EmployeeValueChecks.nonBlank(jsonSchema, "jsonSchema", 64_000);
    }
}

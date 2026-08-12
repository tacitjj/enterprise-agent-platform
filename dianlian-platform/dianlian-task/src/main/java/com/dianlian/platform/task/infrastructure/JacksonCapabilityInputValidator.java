package com.dianlian.platform.task.infrastructure;

import com.dianlian.platform.employee.api.InputSchemaDescriptor;
import com.dianlian.platform.task.api.CapabilityInput;
import com.dianlian.platform.task.api.TaskAdmissionRejectedException;
import com.dianlian.platform.task.application.CapabilityInputValidator;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.math.BigDecimal;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.regex.PatternSyntaxException;
import org.springframework.stereotype.Component;

@Component
public class JacksonCapabilityInputValidator implements CapabilityInputValidator {

    private static final String ERROR_CODE = "CAPABILITY_INPUT_INVALID";

    private final ObjectMapper objectMapper;

    public JacksonCapabilityInputValidator(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    public void validate(CapabilityInput input, InputSchemaDescriptor schemaDescriptor) {
        try {
            var schema = objectMapper.readTree(schemaDescriptor.jsonSchema());
            var value = objectMapper.valueToTree(input.values());
            if (!schema.isObject() || !declaresType(schema, "object")) {
                reject("Employee input schema must declare a root object");
            }
            validateNode(value, schema, "$");
        } catch (JsonProcessingException | PatternSyntaxException exception) {
            throw new TaskAdmissionRejectedException(
                    ERROR_CODE,
                    "Capability input could not be validated against the employee input schema"
            );
        }
    }

    private void validateNode(JsonNode value, JsonNode schema, String path) {
        validateEnum(value, schema, path);
        validateType(value, schema, path);
        if (value == null || value.isNull()) {
            return;
        }
        if (value.isObject()) {
            validateObject(value, schema, path);
        } else if (value.isTextual()) {
            validateString(value.textValue(), schema, path);
        } else if (value.isNumber()) {
            validateNumber(value.decimalValue(), schema, path);
        } else if (value.isArray() && schema.has("items")) {
            for (var index = 0; index < value.size(); index++) {
                validateNode(value.get(index), schema.get("items"), path + "[" + index + "]");
            }
        }
    }

    private void validateObject(JsonNode value, JsonNode schema, String path) {
        var properties = schema.path("properties");
        if (!properties.isMissingNode() && !properties.isObject()) {
            reject(path + " schema properties must be an object");
        }
        var required = requiredProperties(schema, path);
        for (var requiredName : required) {
            if (!value.has(requiredName)) {
                reject(path + "." + requiredName + " is required");
            }
        }
        var allowAdditional = !schema.has("additionalProperties")
                || !schema.get("additionalProperties").isBoolean()
                || schema.get("additionalProperties").booleanValue();
        var fields = value.properties().iterator();
        while (fields.hasNext()) {
            var field = fields.next();
            var propertySchema = properties.get(field.getKey());
            if (propertySchema == null) {
                if (!allowAdditional) {
                    reject(path + "." + field.getKey() + " is not allowed");
                }
                continue;
            }
            if (!propertySchema.isObject()) {
                reject(path + "." + field.getKey() + " schema must be an object");
            }
            validateNode(field.getValue(), propertySchema, path + "." + field.getKey());
        }
    }

    private Set<String> requiredProperties(JsonNode schema, String path) {
        var requiredNode = schema.path("required");
        if (requiredNode.isMissingNode()) {
            return Set.of();
        }
        if (!requiredNode.isArray()) {
            reject(path + " schema required must be an array");
        }
        var required = new HashSet<String>();
        for (var item : requiredNode) {
            if (!item.isTextual()) {
                reject(path + " schema required items must be strings");
            }
            required.add(item.textValue());
        }
        return Set.copyOf(required);
    }

    private void validateType(JsonNode value, JsonNode schema, String path) {
        var typeNode = schema.get("type");
        if (typeNode == null) {
            return;
        }
        if (typeNode.isTextual()) {
            if (!matchesType(value, typeNode.textValue())) {
                reject(path + " must be of type " + typeNode.textValue());
            }
            return;
        }
        if (typeNode.isArray()) {
            for (var candidate : typeNode) {
                if (candidate.isTextual() && matchesType(value, candidate.textValue())) {
                    return;
                }
            }
            reject(path + " does not match any allowed type");
        }
        reject(path + " schema type must be a string or string array");
    }

    private boolean declaresType(JsonNode schema, String expectedType) {
        var typeNode = schema.get("type");
        if (typeNode == null) {
            return false;
        }
        if (typeNode.isTextual()) {
            return expectedType.equals(typeNode.textValue());
        }
        if (typeNode.isArray()) {
            for (var candidate : typeNode) {
                if (candidate.isTextual() && expectedType.equals(candidate.textValue())) {
                    return true;
                }
            }
        }
        return false;
    }

    private boolean matchesType(JsonNode value, String type) {
        return switch (type) {
            case "null" -> value == null || value.isNull();
            case "object" -> value != null && value.isObject();
            case "array" -> value != null && value.isArray();
            case "string" -> value != null && value.isTextual();
            case "number" -> value != null && value.isNumber();
            case "integer" -> value != null && value.isIntegralNumber();
            case "boolean" -> value != null && value.isBoolean();
            default -> false;
        };
    }

    private void validateString(String value, JsonNode schema, String path) {
        var minLength = integerConstraint(schema, "minLength", path);
        var maxLength = integerConstraint(schema, "maxLength", path);
        if (minLength != null && value.length() < minLength) {
            reject(path + " is shorter than minLength");
        }
        if (maxLength != null && value.length() > maxLength) {
            reject(path + " exceeds maxLength");
        }
        if (schema.has("pattern")) {
            if (!schema.get("pattern").isTextual()) {
                reject(path + " schema pattern must be a string");
            }
            if (!Pattern.compile(schema.get("pattern").textValue()).matcher(value).find()) {
                reject(path + " does not match pattern");
            }
        }
    }

    private void validateNumber(BigDecimal value, JsonNode schema, String path) {
        var minimum = decimalConstraint(schema, "minimum", path);
        var maximum = decimalConstraint(schema, "maximum", path);
        if (minimum != null && value.compareTo(minimum) < 0) {
            reject(path + " is below minimum");
        }
        if (maximum != null && value.compareTo(maximum) > 0) {
            reject(path + " exceeds maximum");
        }
    }

    private void validateEnum(JsonNode value, JsonNode schema, String path) {
        var enumNode = schema.get("enum");
        if (enumNode == null) {
            return;
        }
        if (!enumNode.isArray() || enumNode.isEmpty()) {
            reject(path + " schema enum must be a non-empty array");
        }
        for (var candidate : enumNode) {
            if (candidate.equals(value)) {
                return;
            }
        }
        reject(path + " is not one of the allowed enum values");
    }

    private Integer integerConstraint(JsonNode schema, String name, String path) {
        var node = schema.get(name);
        if (node == null) {
            return null;
        }
        if (!node.canConvertToInt() || node.intValue() < 0) {
            reject(path + " schema " + name + " must be a non-negative integer");
        }
        return node.intValue();
    }

    private BigDecimal decimalConstraint(JsonNode schema, String name, String path) {
        var node = schema.get(name);
        if (node == null) {
            return null;
        }
        if (!node.isNumber()) {
            reject(path + " schema " + name + " must be a number");
        }
        return node.decimalValue();
    }

    private void reject(String message) {
        throw new TaskAdmissionRejectedException(ERROR_CODE, message);
    }
}

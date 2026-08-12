package com.dianlian.platform.task.infrastructure;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.dianlian.platform.employee.api.InputSchemaDescriptor;
import com.dianlian.platform.task.api.CapabilityInput;
import com.dianlian.platform.task.api.TaskAdmissionRejectedException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class JacksonCapabilityInputValidatorTests {

    private final JacksonCapabilityInputValidator validator =
            new JacksonCapabilityInputValidator(new ObjectMapper());

    @Test
    void acceptsTheSupportedDeterministicJsonSchemaSubset() {
        assertThatCode(() -> validator.validate(
                input(Map.of(
                        "name", "DL-2026",
                        "count", 3,
                        "ratio", 1.5,
                        "mode", "STANDARD"
                )),
                schema()
        )).doesNotThrowAnyException();
    }

    @Test
    void rejectsRequiredTypeRangePatternEnumAndAdditionalPropertyViolations() {
        var invalidValues = List.of(
                Map.<String, Object>of("count", 3, "ratio", 1.5, "mode", "STANDARD"),
                Map.<String, Object>of("name", "bad", "count", 3, "ratio", 1.5, "mode", "STANDARD"),
                Map.<String, Object>of("name", "DL-2026", "count", 3.5, "ratio", 1.5, "mode", "STANDARD"),
                Map.<String, Object>of("name", "DL-2026", "count", 11, "ratio", 1.5, "mode", "STANDARD"),
                Map.<String, Object>of("name", "DL-2026", "count", 3, "ratio", 1.5, "mode", "UNKNOWN"),
                Map.<String, Object>of(
                        "name", "DL-2026",
                        "count", 3,
                        "ratio", 1.5,
                        "mode", "STANDARD",
                        "unexpected", true
                )
        );

        for (var values : invalidValues) {
            assertThatThrownBy(() -> validator.validate(input(values), schema()))
                    .isInstanceOfSatisfying(TaskAdmissionRejectedException.class, exception ->
                            org.assertj.core.api.Assertions.assertThat(exception.errorCode())
                                    .isEqualTo("CAPABILITY_INPUT_INVALID")
                    );
        }
    }

    private CapabilityInput input(Map<String, Object> values) {
        return new CapabilityInput("generic.schema", "1", values);
    }

    private InputSchemaDescriptor schema() {
        return new InputSchemaDescriptor(
                "generic.schema",
                "1",
                """
                {
                  "type": "object",
                  "additionalProperties": false,
                  "required": ["name", "count", "ratio", "mode"],
                  "properties": {
                    "name": {
                      "type": "string",
                      "minLength": 4,
                      "maxLength": 20,
                      "pattern": "^DL-[0-9]{4}$"
                    },
                    "count": {"type": "integer", "minimum": 1, "maximum": 10},
                    "ratio": {"type": "number", "minimum": 0.5, "maximum": 2.0},
                    "mode": {"type": "string", "enum": ["STANDARD", "EXPRESS"]}
                  }
                }
                """
        );
    }
}

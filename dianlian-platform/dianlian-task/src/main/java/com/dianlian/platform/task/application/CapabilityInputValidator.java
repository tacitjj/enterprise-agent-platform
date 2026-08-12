package com.dianlian.platform.task.application;

import com.dianlian.platform.employee.api.InputSchemaDescriptor;
import com.dianlian.platform.task.api.CapabilityInput;

public interface CapabilityInputValidator {

    void validate(CapabilityInput input, InputSchemaDescriptor schemaDescriptor);
}

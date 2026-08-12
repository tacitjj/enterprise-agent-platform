package com.dianlian.platform.employee.api;

public final class EmployeePreconditionRequiredException extends RuntimeException {

    public EmployeePreconditionRequiredException() {
        super("If-Match is required for this employee state transition");
    }
}

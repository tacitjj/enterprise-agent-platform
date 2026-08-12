package com.dianlian.platform.employee.api;

public final class EmployeePreconditionFailedException extends RuntimeException {

    public EmployeePreconditionFailedException() {
        super("employee state version no longer matches If-Match");
    }
}

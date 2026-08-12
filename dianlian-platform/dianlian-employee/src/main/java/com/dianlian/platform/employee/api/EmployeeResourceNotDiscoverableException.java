package com.dianlian.platform.employee.api;

public final class EmployeeResourceNotDiscoverableException extends RuntimeException {

    public EmployeeResourceNotDiscoverableException() {
        super("employee resource is unavailable or not discoverable");
    }
}

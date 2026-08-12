package com.dianlian.platform.employee.api;

public final class EmployeeAccessDeniedException extends RuntimeException {

    public EmployeeAccessDeniedException(String permission) {
        super("missing employee permission: " + permission);
    }
}

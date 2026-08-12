package com.dianlian.platform.employee.api;

public final class EmployeeCommandConflictException extends RuntimeException {

    private final String code;

    public EmployeeCommandConflictException(String code, String message) {
        super(message);
        this.code = code;
    }

    public String code() {
        return code;
    }
}

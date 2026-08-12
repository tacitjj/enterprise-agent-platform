package com.dianlian.platform.model.api;

public class ModelCommandConflictException extends RuntimeException {
    private final String code;

    public ModelCommandConflictException(String code, String message) {
        super(message);
        this.code = code;
    }

    public String code() {
        return code;
    }
}

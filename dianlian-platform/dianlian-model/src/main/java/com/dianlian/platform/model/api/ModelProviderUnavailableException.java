package com.dianlian.platform.model.api;

public class ModelProviderUnavailableException extends RuntimeException {
    private final String code;

    public ModelProviderUnavailableException(String code, String message, Throwable cause) {
        super(message, cause);
        this.code = code;
    }

    public String code() {
        return code;
    }
}

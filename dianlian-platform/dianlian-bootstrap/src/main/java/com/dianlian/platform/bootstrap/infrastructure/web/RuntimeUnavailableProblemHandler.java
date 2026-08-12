package com.dianlian.platform.bootstrap.infrastructure.web;

import com.dianlian.platform.task.api.RuntimeUnavailableException;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class RuntimeUnavailableProblemHandler {

    private static final URI TYPE = URI.create("urn:dianlian:problem:runtime-unavailable");

    @ExceptionHandler(RuntimeUnavailableException.class)
    ResponseEntity<ProblemDetail> handleRuntimeUnavailable(
            RuntimeUnavailableException exception,
            HttpServletRequest request
    ) {
        var problem = ProblemDetail.forStatusAndDetail(
                HttpStatus.SERVICE_UNAVAILABLE,
                exception.getMessage()
        );
        problem.setType(TYPE);
        problem.setTitle("Agent Runtime unavailable");
        problem.setInstance(URI.create(request.getRequestURI()));
        problem.setProperty("code", exception.errorCode());
        return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(problem);
    }
}

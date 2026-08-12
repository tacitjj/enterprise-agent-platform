package com.dianlian.platform.bootstrap.infrastructure.web;

import com.dianlian.platform.employee.api.EmployeeAccessDeniedException;
import com.dianlian.platform.identity.api.ActiveTenantRequiredException;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = OfficeController.class)
public final class OfficeProblemHandler {

    @ExceptionHandler({EmployeeAccessDeniedException.class, ActiveTenantRequiredException.class})
    ResponseEntity<ProblemDetail> handleTenantAccessDenied(
            RuntimeException exception,
            HttpServletRequest request
    ) {
        var traceId = RequestTraceFilter.traceId(request);
        var problem = ProblemDetail.forStatusAndDetail(HttpStatus.FORBIDDEN, exception.getMessage());
        problem.setType(URI.create("urn:dianlian:problem:tenant-access-denied"));
        problem.setTitle("Forbidden");
        problem.setInstance(URI.create(request.getRequestURI()));
        problem.setProperty("code", "TENANT_ACCESS_DENIED");
        problem.setProperty("traceId", traceId);
        problem.setProperty("retryable", false);
        problem.setProperty("action", "CONTACT_ADMIN");
        return ResponseEntity.status(HttpStatus.FORBIDDEN)
                .header(RequestTraceFilter.TRACE_HEADER, traceId)
                .body(problem);
    }
}

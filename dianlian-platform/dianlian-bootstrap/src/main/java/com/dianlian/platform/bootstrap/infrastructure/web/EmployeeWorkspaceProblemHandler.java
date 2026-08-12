package com.dianlian.platform.bootstrap.infrastructure.web;

import com.dianlian.platform.employee.api.EmployeeAccessDeniedException;
import com.dianlian.platform.employee.api.EmployeeResourceNotDiscoverableException;
import com.dianlian.platform.identity.api.ActiveTenantRequiredException;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = EmployeeWorkspaceController.class)
public final class EmployeeWorkspaceProblemHandler {

    @ExceptionHandler({EmployeeAccessDeniedException.class, ActiveTenantRequiredException.class})
    ResponseEntity<ProblemDetail> handleTenantAccessDenied(RuntimeException exception, HttpServletRequest request) {
        return problem(
                HttpStatus.FORBIDDEN,
                "TENANT_ACCESS_DENIED",
                "当前身份无权使用该数字员工。",
                "CONTACT_ADMIN",
                request
        );
    }

    @ExceptionHandler(EmployeeResourceNotDiscoverableException.class)
    ResponseEntity<ProblemDetail> handleNotDiscoverable(
            EmployeeResourceNotDiscoverableException exception,
            HttpServletRequest request
    ) {
        return problem(
                HttpStatus.NOT_FOUND,
                "RESOURCE_NOT_FOUND_OR_FORBIDDEN",
                "数字员工不存在、未启用或当前身份无权访问。",
                "RETURN_SAFE_PAGE",
                request
        );
    }

    private ResponseEntity<ProblemDetail> problem(
            HttpStatus status,
            String code,
            String detail,
            String action,
            HttpServletRequest request
    ) {
        var traceId = RequestTraceFilter.traceId(request);
        var problem = ProblemDetail.forStatusAndDetail(status, detail);
        problem.setType(URI.create("https://dianlian.example/problems/" + code.toLowerCase().replace('_', '-')));
        problem.setTitle(status.getReasonPhrase());
        problem.setInstance(URI.create(request.getRequestURI()));
        problem.setProperty("code", code);
        problem.setProperty("traceId", traceId);
        problem.setProperty("retryable", false);
        problem.setProperty("action", action);
        return ResponseEntity.status(status)
                .header(RequestTraceFilter.TRACE_HEADER, traceId)
                .body(problem);
    }
}

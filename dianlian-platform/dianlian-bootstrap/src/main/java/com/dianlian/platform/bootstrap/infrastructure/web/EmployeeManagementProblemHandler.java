package com.dianlian.platform.bootstrap.infrastructure.web;

import com.dianlian.platform.employee.api.EmployeeAccessDeniedException;
import com.dianlian.platform.employee.api.EmployeeCommandConflictException;
import com.dianlian.platform.employee.api.EmployeeResourceNotDiscoverableException;
import com.dianlian.platform.employee.api.EmployeePreconditionFailedException;
import com.dianlian.platform.employee.api.EmployeePreconditionRequiredException;
import com.dianlian.platform.identity.api.ActiveTenantRequiredException;
import com.dianlian.platform.identity.api.PlatformAccessRequiredException;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(basePackages = "com.dianlian.platform.employee.infrastructure.web")
public class EmployeeManagementProblemHandler {

    @ExceptionHandler(EmployeeAccessDeniedException.class)
    ResponseEntity<ProblemDetail> handleAccessDenied(
            EmployeeAccessDeniedException exception,
            HttpServletRequest request
    ) {
        return problem(
                HttpStatus.FORBIDDEN,
                "EMPLOYEE_MANAGEMENT_ACCESS_DENIED",
                "无权管理数字员工",
                "当前身份没有执行此员工管理操作的权限。",
                "CONTACT_ADMIN",
                request
        );
    }

    @ExceptionHandler(ActiveTenantRequiredException.class)
    ResponseEntity<ProblemDetail> handleTenantRequired(
            ActiveTenantRequiredException exception,
            HttpServletRequest request
    ) {
        return problem(
                HttpStatus.FORBIDDEN,
                "ACTIVE_TENANT_REQUIRED",
                "尚未选择企业",
                "请先选择有权管理的企业。",
                "REFRESH_SESSION",
                request
        );
    }

    @ExceptionHandler(PlatformAccessRequiredException.class)
    ResponseEntity<ProblemDetail> handlePlatformAccessRequired(
            PlatformAccessRequiredException exception,
            HttpServletRequest request
    ) {
        return problem(
                HttpStatus.FORBIDDEN,
                "PLATFORM_ACCESS_REQUIRED",
                "需要平台运营身份",
                "企业会话不能访问平台全局员工模板。",
                "REFRESH_SESSION",
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
                "无法访问该员工模板",
                "模板不存在、未发布或当前企业不在可见范围。",
                "RETURN_SAFE_PAGE",
                request
        );
    }

    @ExceptionHandler(EmployeeCommandConflictException.class)
    ResponseEntity<ProblemDetail> handleConflict(
            EmployeeCommandConflictException exception,
            HttpServletRequest request
    ) {
        boolean idempotencyConflict = "IDEMPOTENCY_REQUEST_CONFLICT".equals(exception.code());
        return problem(
                HttpStatus.CONFLICT,
                exception.code(),
                idempotencyConflict ? "重复请求内容不一致" : "员工管理状态已变化",
                idempotencyConflict
                        ? "同一幂等键已用于不同请求，请创建新的操作意图。"
                        : "请刷新模板或员工状态后重试。",
                idempotencyConflict ? "CREATE_NEW_INTENT" : "REFRESH_RESOURCE",
                request
        );
    }

    @ExceptionHandler(EmployeePreconditionRequiredException.class)
    ResponseEntity<ProblemDetail> handlePreconditionRequired(
            EmployeePreconditionRequiredException exception,
            HttpServletRequest request
    ) {
        return problem(
                HttpStatus.PRECONDITION_REQUIRED,
                "EMPLOYEE_IF_MATCH_REQUIRED",
                "需要员工版本条件",
                "请先读取员工详情，并携带响应中的 ETag 作为 If-Match。",
                "REFRESH_RESOURCE",
                request
        );
    }

    @ExceptionHandler(EmployeePreconditionFailedException.class)
    ResponseEntity<ProblemDetail> handlePreconditionFailed(
            EmployeePreconditionFailedException exception,
            HttpServletRequest request
    ) {
        return problem(
                HttpStatus.PRECONDITION_FAILED,
                "EMPLOYEE_STATE_VERSION_MISMATCH",
                "员工状态已变化",
                "请刷新员工详情并基于最新 ETag 重试。",
                "REFRESH_RESOURCE",
                request
        );
    }

    @ExceptionHandler({
            IllegalArgumentException.class,
            HttpMessageNotReadableException.class,
            MissingRequestHeaderException.class
    })
    ResponseEntity<ProblemDetail> handleValidation(Exception exception, HttpServletRequest request) {
        return problem(
                HttpStatus.BAD_REQUEST,
                "VALIDATION_FAILED",
                "请求内容不符合要求",
                "请检查员工模板、招聘字段和幂等键后重试。",
                "NONE",
                request
        );
    }

    private ResponseEntity<ProblemDetail> problem(
            HttpStatus status,
            String code,
            String title,
            String detail,
            String action,
            HttpServletRequest request
    ) {
        var traceId = RequestTraceFilter.traceId(request);
        var problem = ProblemDetail.forStatusAndDetail(status, detail);
        problem.setType(URI.create("https://dianlian.example/problems/" + code.toLowerCase().replace('_', '-')));
        problem.setTitle(title);
        problem.setInstance(URI.create(request.getRequestURI()));
        problem.setProperty("code", code);
        problem.setProperty("traceId", traceId);
        problem.setProperty("retryable", false);
        problem.setProperty("action", action);
        return ResponseEntity.status(status)
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .header(RequestTraceFilter.TRACE_HEADER, traceId)
                .body(problem);
    }
}

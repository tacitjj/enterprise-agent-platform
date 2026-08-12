package com.dianlian.platform.bootstrap.infrastructure.web;

import com.dianlian.platform.model.api.ModelAccessDeniedException;
import com.dianlian.platform.model.api.ModelCommandConflictException;
import com.dianlian.platform.model.api.ModelProviderUnavailableException;
import com.dianlian.platform.model.api.ModelRouteUnavailableException;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(basePackages = "com.dianlian.platform.model.infrastructure.web")
public class ModelProblemHandler {

    @ExceptionHandler(ModelAccessDeniedException.class)
    ResponseEntity<ProblemDetail> accessDenied(ModelAccessDeniedException exception, HttpServletRequest request) {
        return problem(HttpStatus.FORBIDDEN, "MODEL_ACCESS_DENIED", "无权管理模型",
                "当前身份没有管理模型目录或员工模型路由的权限。", false, "CONTACT_ADMIN", request);
    }

    @ExceptionHandler(ModelCommandConflictException.class)
    ResponseEntity<ProblemDetail> conflict(ModelCommandConflictException exception, HttpServletRequest request) {
        return problem(HttpStatus.CONFLICT, exception.code(), "模型配置状态已变化",
                "请刷新模型目录或创建新的配置意图。", false, "CREATE_NEW_INTENT", request);
    }

    @ExceptionHandler(ModelRouteUnavailableException.class)
    ResponseEntity<ProblemDetail> routeUnavailable(ModelRouteUnavailableException exception, HttpServletRequest request) {
        return problem(HttpStatus.UNPROCESSABLE_ENTITY, "MODEL_ROUTE_UNAVAILABLE", "模型路由不可用",
                "该数字员工尚未配置可用的模型路由，未发起模型调用。", false, "CONTACT_ADMIN", request);
    }

    @ExceptionHandler(ModelProviderUnavailableException.class)
    ResponseEntity<ProblemDetail> providerUnavailable(
            ModelProviderUnavailableException exception,
            HttpServletRequest request
    ) {
        return problem(HttpStatus.SERVICE_UNAVAILABLE, exception.code(), "模型服务暂不可用",
                "模型调用未完成，请稍后重试或切换已配置的模型。", true, "RETRY_LATER", request);
    }

    private ResponseEntity<ProblemDetail> problem(
            HttpStatus status,
            String code,
            String title,
            String detail,
            boolean retryable,
            String action,
            HttpServletRequest request
    ) {
        String traceId = RequestTraceFilter.traceId(request);
        var problem = ProblemDetail.forStatusAndDetail(status, detail);
        problem.setType(URI.create("https://dianlian.example/problems/" + code.toLowerCase().replace('_', '-')));
        problem.setTitle(title);
        problem.setInstance(URI.create(request.getRequestURI()));
        problem.setProperty("code", code);
        problem.setProperty("traceId", traceId);
        problem.setProperty("retryable", retryable);
        problem.setProperty("action", action);
        return ResponseEntity.status(status)
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .header(RequestTraceFilter.TRACE_HEADER, traceId)
                .body(problem);
    }
}

package com.dianlian.platform.bootstrap.infrastructure.web;

import com.dianlian.platform.billing.api.InsufficientPointsException;
import com.dianlian.platform.billing.api.PointAccountUnavailableException;
import com.dianlian.platform.employee.api.EmployeeAccessDeniedException;
import com.dianlian.platform.employee.api.EmployeeResourceNotDiscoverableException;
import com.dianlian.platform.interaction.api.ConversationCommandConflictException;
import com.dianlian.platform.interaction.api.ConversationNotDiscoverableException;
import com.dianlian.platform.interaction.api.InteractionAccessDeniedException;
import com.dianlian.platform.model.api.ModelRouteUnavailableException;
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

@RestControllerAdvice(basePackages = "com.dianlian.platform.interaction.infrastructure.web")
public class InteractionProblemHandler {

    @ExceptionHandler({InteractionAccessDeniedException.class, EmployeeAccessDeniedException.class})
    ResponseEntity<ProblemDetail> accessDenied(RuntimeException exception, HttpServletRequest request) {
        return problem(HttpStatus.FORBIDDEN, "CONVERSATION_ACCESS_DENIED", "无权访问消息",
                "当前身份没有执行此会话操作或调用该数字员工的权限。", false, "CONTACT_ADMIN", request);
    }

    @ExceptionHandler({ConversationNotDiscoverableException.class, EmployeeResourceNotDiscoverableException.class})
    ResponseEntity<ProblemDetail> notFound(RuntimeException exception, HttpServletRequest request) {
        return problem(HttpStatus.NOT_FOUND, "RESOURCE_NOT_FOUND_OR_FORBIDDEN", "无法访问该会话",
                "会话不存在、成员关系已变化或资源不在当前企业范围。", false, "RETURN_SAFE_PAGE", request);
    }

    @ExceptionHandler(ConversationCommandConflictException.class)
    ResponseEntity<ProblemDetail> conflict(
            ConversationCommandConflictException exception,
            HttpServletRequest request
    ) {
        return problem(HttpStatus.CONFLICT, exception.code(), "会话状态已变化",
                exception.getMessage(), false, "REFRESH_CONVERSATION", request);
    }

    @ExceptionHandler({InsufficientPointsException.class, PointAccountUnavailableException.class})
    ResponseEntity<ProblemDetail> quota(RuntimeException exception, HttpServletRequest request) {
        return problem(HttpStatus.UNPROCESSABLE_ENTITY, "QUOTA_INSUFFICIENT", "智点不可用",
                "数字员工未开始调用模型，请联系企业管理员检查智点账户。", false, "CONTACT_POINT_ADMIN", request);
    }

    @ExceptionHandler(ModelRouteUnavailableException.class)
    ResponseEntity<ProblemDetail> route(ModelRouteUnavailableException exception, HttpServletRequest request) {
        return problem(HttpStatus.UNPROCESSABLE_ENTITY, "MODEL_ROUTE_UNAVAILABLE", "员工模型尚未配置",
                "该数字员工没有符合其配置策略的可用模型，消息未调用 AI。", false, "CONTACT_ADMIN", request);
    }

    @ExceptionHandler({
            IllegalArgumentException.class,
            HttpMessageNotReadableException.class,
            MissingRequestHeaderException.class
    })
    ResponseEntity<ProblemDetail> validation(Exception exception, HttpServletRequest request) {
        return problem(HttpStatus.BAD_REQUEST, "VALIDATION_FAILED", "消息请求不符合要求",
                "请检查会话成员、数字员工目标、协作模式、版本和幂等键。", false, "NONE", request);
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

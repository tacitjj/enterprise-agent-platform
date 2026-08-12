package com.dianlian.platform.task.infrastructure.web;

import com.dianlian.platform.billing.api.InsufficientPointsException;
import com.dianlian.platform.billing.api.PointAccountUnavailableException;
import com.dianlian.platform.billing.api.PointReservationConflictException;
import com.dianlian.platform.employee.api.EmployeeAccessDeniedException;
import com.dianlian.platform.employee.api.EmployeeResourceNotDiscoverableException;
import com.dianlian.platform.identity.api.AuthenticationRequiredException;
import com.dianlian.platform.task.api.IdempotencyRequestConflictException;
import com.dianlian.platform.task.api.TaskAdmissionRejectedException;
import com.dianlian.platform.task.api.TaskAccessDeniedException;
import com.dianlian.platform.task.api.TaskEventStreamUnavailableException;
import com.dianlian.platform.task.api.TaskNotFoundException;
import com.dianlian.platform.task.api.TaskPermissions;
import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import java.util.UUID;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

@RestControllerAdvice(assignableTypes = TaskController.class)
public class TaskProblemHandler {

    @ExceptionHandler(AuthenticationRequiredException.class)
    ResponseEntity<ProblemDetail> handleAuthenticationRequired(
            AuthenticationRequiredException exception,
            HttpServletRequest request
    ) {
        return problem(
                HttpStatus.UNAUTHORIZED,
                "AUTHENTICATION_REQUIRED",
                "登录状态已失效",
                "请重新登录后继续。",
                false,
                "REAUTHENTICATE",
                request
        );
    }

    @ExceptionHandler(IdempotencyRequestConflictException.class)
    ResponseEntity<ProblemDetail> handleIdempotencyConflict(
            IdempotencyRequestConflictException exception,
            HttpServletRequest request
    ) {
        return problem(
                HttpStatus.CONFLICT,
                exception.errorCode(),
                "重复请求内容不一致",
                "同一幂等键已用于不同请求，请检查客户端命令。",
                false,
                "CREATE_NEW_INTENT",
                request
        );
    }

    @ExceptionHandler(PointReservationConflictException.class)
    ResponseEntity<ProblemDetail> handlePointReservationConflict(
            PointReservationConflictException exception,
            HttpServletRequest request
    ) {
        return problem(
                HttpStatus.CONFLICT,
                exception.errorCode(),
                "智点预占状态已变化",
                "任务没有重复扣取智点，请刷新任务状态后重试。",
                false,
                "REFRESH_TASK",
                request
        );
    }

    @ExceptionHandler(TaskAdmissionRejectedException.class)
    ResponseEntity<ProblemDetail> handleAdmission(
            TaskAdmissionRejectedException exception,
            HttpServletRequest request
    ) {
        if ("TASK_OWNER_MISMATCH".equals(exception.errorCode())) {
            return problem(
                    HttpStatus.FORBIDDEN,
                    exception.errorCode(),
                    "任务归属与当前身份不一致",
                    "任务创建人必须是当前登录用户，请刷新会话后重试。",
                    false,
                    "REFRESH_SESSION",
                    request
            );
        }
        return problem(
                HttpStatus.UNPROCESSABLE_ENTITY,
                exception.errorCode(),
                "任务暂时无法开始",
                "当前任务配置不满足执行条件，请调整后重试。",
                false,
                "RETURN_SAFE_PAGE",
                request
        );
    }

    @ExceptionHandler(InsufficientPointsException.class)
    ResponseEntity<ProblemDetail> handleInsufficientPoints(
            InsufficientPointsException exception,
            HttpServletRequest request
    ) {
        return problem(
                HttpStatus.UNPROCESSABLE_ENTITY,
                "QUOTA_INSUFFICIENT",
                "智点不足",
                "当前智点不足，任务未调用模型或工具。",
                false,
                "CONTACT_POINT_ADMIN",
                request
        );
    }

    @ExceptionHandler(PointAccountUnavailableException.class)
    ResponseEntity<ProblemDetail> handlePointAccountUnavailable(
            PointAccountUnavailableException exception,
            HttpServletRequest request
    ) {
        return problem(
                HttpStatus.UNPROCESSABLE_ENTITY,
                exception.errorCode(),
                "智点账户不可用",
                "当前计费范围没有可用的智点账户，请联系企业管理员。",
                false,
                "CONTACT_POINT_ADMIN",
                request
        );
    }

    @ExceptionHandler({TaskNotFoundException.class, EmployeeResourceNotDiscoverableException.class})
    ResponseEntity<ProblemDetail> handleNotDiscoverable(RuntimeException exception, HttpServletRequest request) {
        return problem(
                HttpStatus.NOT_FOUND,
                "RESOURCE_NOT_FOUND_OR_FORBIDDEN",
                "无法访问该资源",
                "资源不存在或你没有访问权限。",
                false,
                "RETURN_SAFE_PAGE",
                request
        );
    }

    @ExceptionHandler(EmployeeAccessDeniedException.class)
    ResponseEntity<ProblemDetail> handleEmployeeAccessDenied(
            EmployeeAccessDeniedException exception,
            HttpServletRequest request
    ) {
        return problem(
                HttpStatus.FORBIDDEN,
                "TENANT_ACCESS_DENIED",
                "无权使用该数字员工",
                "当前身份没有使用该数字员工的权限。",
                false,
                "RETURN_SAFE_PAGE",
                request
        );
    }

    @ExceptionHandler(TaskAccessDeniedException.class)
    ResponseEntity<ProblemDetail> handleTaskAccessDenied(
            TaskAccessDeniedException exception,
            HttpServletRequest request
    ) {
        var reading = TaskPermissions.READ.equals(exception.permission());
        return problem(
                HttpStatus.FORBIDDEN,
                "TASK_ACCESS_DENIED",
                reading ? "无权访问任务" : "无权创建任务",
                reading ? "当前身份没有查看任务动态的权限。" : "当前身份没有创建任务并预占智点的权限。",
                false,
                "CONTACT_ADMIN",
                request
        );
    }

    @ExceptionHandler(TaskEventStreamUnavailableException.class)
    ResponseEntity<ProblemDetail> handleTaskEventStreamUnavailable(
            TaskEventStreamUnavailableException exception,
            HttpServletRequest request
    ) {
        return problem(
                HttpStatus.SERVICE_UNAVAILABLE,
                "TASK_EVENT_STREAM_UNAVAILABLE",
                "任务动态连接暂不可用",
                "请暂时使用任务快照并稍后重新连接。",
                true,
                "POLL_TASK",
                request
        );
    }

    @ExceptionHandler({
            IllegalArgumentException.class,
            HttpMessageNotReadableException.class,
            MissingRequestHeaderException.class,
            MethodArgumentTypeMismatchException.class
    })
    ResponseEntity<ProblemDetail> handleValidation(Exception exception, HttpServletRequest request) {
        return problem(
                HttpStatus.BAD_REQUEST,
                "VALIDATION_FAILED",
                "请求内容不符合要求",
                "请检查请求字段、标识和请求头后重试。",
                false,
                "NONE",
                request
        );
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
        var traceId = UUID.randomUUID().toString();
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
                .header("X-Trace-Id", traceId)
                .body(problem);
    }
}

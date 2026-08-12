package com.dianlian.platform.bootstrap.infrastructure.web;

import com.dianlian.platform.bootstrap.infrastructure.security.ApiSecurityProblemWriter;
import com.dianlian.platform.identity.api.InvalidCredentialsException;
import com.dianlian.platform.identity.api.InvalidRefreshTokenException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = AuthenticationController.class)
public final class AuthenticationProblemHandler {

    private final ApiSecurityProblemWriter problemWriter;

    public AuthenticationProblemHandler(ApiSecurityProblemWriter problemWriter) {
        this.problemWriter = problemWriter;
    }

    @ExceptionHandler(InvalidCredentialsException.class)
    void invalidCredentials(HttpServletRequest request, HttpServletResponse response) throws IOException {
        problemWriter.write(
                request,
                response,
                401,
                "INVALID_CREDENTIALS",
                "账号或密码错误",
                "账号或密码不正确，请重新输入。",
                false,
                "RETRY_LOGIN"
        );
    }

    @ExceptionHandler(InvalidRefreshTokenException.class)
    void invalidRefreshToken(HttpServletRequest request, HttpServletResponse response) throws IOException {
        problemWriter.write(
                request,
                response,
                401,
                "REFRESH_TOKEN_INVALID",
                "登录状态已失效",
                "请重新登录后继续。",
                false,
                "REAUTHENTICATE"
        );
    }
}

package com.dianlian.platform.bootstrap.infrastructure.security;

import com.dianlian.platform.bootstrap.infrastructure.web.RequestTraceFilter;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Objects;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;

@Component
public final class ApiSecurityProblemWriter {

    private final ObjectMapper objectMapper;

    public ApiSecurityProblemWriter(ObjectMapper objectMapper) {
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
    }

    public void write(
            HttpServletRequest request,
            HttpServletResponse response,
            int status,
            String code,
            String title,
            String detail,
            boolean retryable,
            String action
    ) throws IOException {
        var traceId = RequestTraceFilter.traceId(request);
        response.setStatus(status);
        response.setCharacterEncoding("UTF-8");
        response.setContentType(MediaType.APPLICATION_PROBLEM_JSON_VALUE);
        response.setHeader("Cache-Control", "no-store");
        response.setHeader(RequestTraceFilter.TRACE_HEADER, traceId);
        objectMapper.writeValue(response.getOutputStream(), new SecurityProblem(
                "https://dianlian.example/problems/" + code.toLowerCase().replace('_', '-'),
                title,
                status,
                detail,
                request.getRequestURI(),
                code,
                traceId,
                retryable,
                action
        ));
    }

    private record SecurityProblem(
            String type,
            String title,
            int status,
            String detail,
            String instance,
            String code,
            String traceId,
            boolean retryable,
            String action
    ) {
    }
}

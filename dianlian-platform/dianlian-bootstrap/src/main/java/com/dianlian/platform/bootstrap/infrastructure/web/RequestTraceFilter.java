package com.dianlian.platform.bootstrap.infrastructure.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public final class RequestTraceFilter extends OncePerRequestFilter {

    public static final String TRACE_HEADER = "X-Trace-Id";
    private static final String TRACE_ATTRIBUTE = RequestTraceFilter.class.getName() + ".traceId";

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        var traceId = UUID.randomUUID().toString();
        request.setAttribute(TRACE_ATTRIBUTE, traceId);
        response.setHeader(TRACE_HEADER, traceId);
        filterChain.doFilter(request, response);
    }

    public static String traceId(HttpServletRequest request) {
        var value = request.getAttribute(TRACE_ATTRIBUTE);
        return value instanceof String traceId && !traceId.isBlank()
                ? traceId
                : UUID.randomUUID().toString();
    }
}

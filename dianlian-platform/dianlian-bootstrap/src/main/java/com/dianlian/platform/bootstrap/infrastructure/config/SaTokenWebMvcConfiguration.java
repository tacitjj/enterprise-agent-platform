package com.dianlian.platform.bootstrap.infrastructure.config;

import com.dianlian.platform.bootstrap.infrastructure.security.SaTokenAuthenticationInterceptor;
import java.util.Objects;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration(proxyBeanMethods = false)
public class SaTokenWebMvcConfiguration implements WebMvcConfigurer {

    private final SaTokenAuthenticationInterceptor authenticationInterceptor;

    public SaTokenWebMvcConfiguration(SaTokenAuthenticationInterceptor authenticationInterceptor) {
        this.authenticationInterceptor = Objects.requireNonNull(
                authenticationInterceptor,
                "authenticationInterceptor must not be null"
        );
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(authenticationInterceptor)
                .addPathPatterns("/api/v1/**")
                .excludePathPatterns(
                        "/api/v1/auth/login",
                        "/api/v1/auth/refresh"
                );
    }
}

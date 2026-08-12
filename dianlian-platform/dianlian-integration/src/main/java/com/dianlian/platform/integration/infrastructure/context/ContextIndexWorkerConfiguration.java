package com.dianlian.platform.integration.infrastructure.context;

import com.dianlian.platform.context.api.ContextIndexDispatch;
import com.dianlian.platform.integration.infrastructure.security.InternalServiceJwtIssuer;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.http.HttpClient;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.web.client.RestClient;

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(
        prefix = "dianlian.context-index-worker",
        name = "enabled",
        havingValue = "true"
)
@EnableConfigurationProperties(ContextIndexWorkerProperties.class)
class ContextIndexWorkerConfiguration {

    @Bean
    ContextIndexingRuntimeClient contextIndexingRuntimeClient(
            ContextIndexWorkerProperties properties,
            ObjectProvider<InternalServiceJwtIssuer> jwtIssuerProvider,
            ObjectMapper objectMapper
    ) {
        InternalServiceJwtIssuer jwtIssuer = jwtIssuerProvider.getIfAvailable();
        if (jwtIssuer == null) {
            throw new IllegalStateException(
                    "dianlian.context-index-worker.enabled=true requires an InternalServiceJwtIssuer"
            );
        }
        var httpClient = HttpClient.newBuilder()
                .connectTimeout(properties.connectTimeout())
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
        var requestFactory = new JdkClientHttpRequestFactory(httpClient);
        requestFactory.setReadTimeout(properties.readTimeout());
        var strictObjectMapper = objectMapper.copy()
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES);
        var restClient = RestClient.builder()
                .baseUrl(properties.baseUrl())
                .requestFactory(requestFactory)
                .messageConverters(converters -> {
                    converters.clear();
                    converters.add(new MappingJackson2HttpMessageConverter(strictObjectMapper));
                })
                .build();
        return new HttpContextIndexingRuntimeClient(restClient, jwtIssuer);
    }

    @Bean
    ContextIndexWorkerProcessor contextIndexWorkerProcessor(
            ContextIndexDispatch dispatch,
            ContextIndexingRuntimeClient runtimeClient,
            ContextIndexWorkerProperties properties
    ) {
        return new ContextIndexWorkerProcessor(dispatch, runtimeClient, properties.leaseDuration());
    }

    @Bean
    ContextIndexWorker contextIndexWorker(ContextIndexWorkerProcessor processor) {
        return new ContextIndexWorker(processor);
    }
}

package com.dianlian.platform.integration.infrastructure.context;

import com.dianlian.platform.context.api.AuthorizedContextRetrievalPort;
import com.dianlian.platform.integration.infrastructure.security.InternalServiceJwtIssuer;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import java.net.http.HttpClient;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(
        prefix = "dianlian.context-retrieval-client",
        name = "enabled",
        havingValue = "true"
)
@EnableConfigurationProperties(ContextRetrievalClientProperties.class)
class ContextRetrievalClientConfiguration {

    @Bean
    AuthorizedContextRetrievalPort authorizedContextRetrievalPort(
            ContextRetrievalClientProperties properties,
            ObjectProvider<InternalServiceJwtIssuer> jwtIssuerProvider,
            ObjectMapper objectMapper
    ) {
        InternalServiceJwtIssuer jwtIssuer = jwtIssuerProvider.getIfAvailable();
        if (jwtIssuer == null) {
            throw new IllegalStateException(
                    "dianlian.context-retrieval-client.enabled=true requires an InternalServiceJwtIssuer"
            );
        }
        var httpClient = HttpClient.newBuilder()
                .connectTimeout(properties.connectTimeout())
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
        var strictObjectMapper = objectMapper.copy()
                .setPropertyNamingStrategy(PropertyNamingStrategies.LOWER_CAMEL_CASE)
                .disable(DeserializationFeature.ACCEPT_FLOAT_AS_INT)
                .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
                .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
        return new HttpAuthorizedContextRetrievalPort(
                httpClient,
                properties.baseUrl(),
                strictObjectMapper,
                jwtIssuer,
                properties.readTimeout()
        );
    }
}

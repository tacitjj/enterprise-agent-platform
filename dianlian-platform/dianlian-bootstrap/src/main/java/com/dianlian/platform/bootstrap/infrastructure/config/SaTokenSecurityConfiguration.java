package com.dianlian.platform.bootstrap.infrastructure.config;

import cn.dev33.satoken.jwt.StpLogicJwtForSimple;
import cn.dev33.satoken.stp.StpLogic;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
public class SaTokenSecurityConfiguration {

    @Bean
    StpLogic stpLogic() {
        return new StpLogicJwtForSimple();
    }

}

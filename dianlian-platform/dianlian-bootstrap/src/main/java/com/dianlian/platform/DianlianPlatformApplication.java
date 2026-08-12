package com.dianlian.platform;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.security.servlet.UserDetailsServiceAutoConfiguration;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication(exclude = UserDetailsServiceAutoConfiguration.class)
@ConfigurationPropertiesScan(basePackages = "com.dianlian.platform.bootstrap.infrastructure.config")
@EnableScheduling
public class DianlianPlatformApplication {

    public static void main(String[] args) {
        SpringApplication.run(DianlianPlatformApplication.class, args);
    }
}

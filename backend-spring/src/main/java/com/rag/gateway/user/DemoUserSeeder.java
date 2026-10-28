package com.rag.gateway.user;

import com.rag.gateway.security.GatewaySecurityProperties;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class DemoUserSeeder {
    @Bean
    ApplicationRunner seedDemoUser(UserService userService, GatewaySecurityProperties properties) {
        return args -> {
            if (Boolean.TRUE.equals(properties.seedDemoUser())) {
                userService.ensureDemoUser(properties.demoUsername(), properties.demoPassword());
            }
        };
    }
}

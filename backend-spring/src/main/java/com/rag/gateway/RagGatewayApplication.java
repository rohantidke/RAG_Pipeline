package com.rag.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@ConfigurationPropertiesScan
public class RagGatewayApplication {
    public static void main(String[] args) {
        SpringApplication.run(RagGatewayApplication.class, args);
    }
}

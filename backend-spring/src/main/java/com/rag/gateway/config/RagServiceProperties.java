package com.rag.gateway.config;

import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "rag.service")
public record RagServiceProperties(
        String baseUrl,
        Duration requestTimeout
) {
    public RagServiceProperties {
        if (baseUrl == null || baseUrl.isBlank()) {
            baseUrl = "http://127.0.0.1:8000";
        }
        if (requestTimeout == null) {
            requestTimeout = Duration.ofSeconds(60);
        }
    }
}

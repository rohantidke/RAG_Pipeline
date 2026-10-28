package com.rag.gateway.ratelimit;

import java.time.Duration;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "gateway.rate-limit")
public record RateLimitProperties(
        Boolean enabled,
        int capacity,
        int refillTokens,
        Duration refillPeriod
) {
    public RateLimitProperties {
        enabled = enabled == null ? Boolean.TRUE : enabled;
        capacity = capacity <= 0 ? 30 : capacity;
        refillTokens = refillTokens <= 0 ? capacity : refillTokens;
        refillPeriod = refillPeriod == null ? Duration.ofMinutes(1) : refillPeriod;
    }
}

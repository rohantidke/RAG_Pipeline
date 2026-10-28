package com.rag.gateway.ratelimit;

record RateLimitDecision(
        boolean allowed,
        int limit,
        int remaining,
        long retryAfterSeconds
) {
}

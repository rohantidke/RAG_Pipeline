package com.rag.gateway.ratelimit;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;

class TokenBucket {
    private final int capacity;
    private final int refillTokens;
    private final Duration refillPeriod;
    private final Clock clock;
    private int tokens;
    private Instant lastRefillAt;

    TokenBucket(int capacity, int refillTokens, Duration refillPeriod, Clock clock) {
        this.capacity = capacity;
        this.refillTokens = refillTokens;
        this.refillPeriod = refillPeriod;
        this.clock = clock;
        this.tokens = capacity;
        this.lastRefillAt = Instant.now(clock);
    }

    synchronized RateLimitDecision tryConsume() {
        refill();

        if (tokens <= 0) {
            long retryAfterSeconds = Math.max(1, refillPeriod.minus(Duration.between(lastRefillAt, Instant.now(clock))).toSeconds());
            return new RateLimitDecision(false, capacity, 0, retryAfterSeconds);
        }

        tokens -= 1;
        return new RateLimitDecision(true, capacity, tokens, 0);
    }

    private void refill() {
        Instant now = Instant.now(clock);
        long elapsedPeriods = Duration.between(lastRefillAt, now).dividedBy(refillPeriod);
        if (elapsedPeriods <= 0) {
            return;
        }

        long newTokens = (long) refillTokens * elapsedPeriods;
        tokens = (int) Math.min(capacity, tokens + newTokens);
        lastRefillAt = lastRefillAt.plus(refillPeriod.multipliedBy(elapsedPeriods));
    }
}

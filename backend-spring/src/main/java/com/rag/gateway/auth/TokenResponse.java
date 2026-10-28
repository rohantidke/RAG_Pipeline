package com.rag.gateway.auth;

import java.time.Instant;

public record TokenResponse(
        String accessToken,
        String tokenType,
        Instant expiresAt
) {
}

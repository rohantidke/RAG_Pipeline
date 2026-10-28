package com.rag.gateway.user;

import com.fasterxml.jackson.annotation.JsonProperty;

public record UserResponse(
        String id,
        String username,
        String email,
        @JsonProperty("created_at") String createdAt
) {
    public static UserResponse fromEntity(UserEntity user) {
        return new UserResponse(
                user.getId(),
                user.getUsername(),
                user.getEmail(),
                user.getCreatedAt().toString()
        );
    }
}

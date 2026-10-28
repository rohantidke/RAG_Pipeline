package com.rag.gateway.chat;

import java.util.Map;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;

public record ChatRequest(
        @NotBlank String message,
        @Min(1) @Max(20) Integer topK,
        Map<String, Object> filters
) {
}

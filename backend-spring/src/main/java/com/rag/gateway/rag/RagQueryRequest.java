package com.rag.gateway.rag;

import java.util.Map;

import com.fasterxml.jackson.annotation.JsonProperty;

public record RagQueryRequest(
        String query,
        @JsonProperty("top_k") Integer topK,
        Map<String, Object> filters,
        @JsonProperty("use_cache") boolean useCache
) {
}

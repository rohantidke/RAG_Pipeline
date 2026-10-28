package com.rag.gateway.rag;

import com.fasterxml.jackson.annotation.JsonProperty;

public record RagCitation(
        @JsonProperty("chunk_id") String chunkId,
        @JsonProperty("document_id") Object documentId,
        Object filename,
        @JsonProperty("page_number") Object pageNumber,
        @JsonProperty("page_count") Object pageCount,
        Object source,
        @JsonProperty("text_preview") String textPreview,
        @JsonProperty("rerank_score") Double rerankScore
) {
}
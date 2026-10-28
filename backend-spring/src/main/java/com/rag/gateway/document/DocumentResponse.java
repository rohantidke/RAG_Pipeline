package com.rag.gateway.document;

import com.fasterxml.jackson.annotation.JsonProperty;

public record DocumentResponse(
        @JsonProperty("document_id") String documentId,
        @JsonProperty("user_id") String userId,
        String filename,
        @JsonProperty("content_type") String contentType,
        @JsonProperty("size_bytes") long sizeBytes,
        String source,
        String status,
        @JsonProperty("chunk_count") int chunkCount,
        @JsonProperty("page_count") int pageCount,
        @JsonProperty("text_char_count") int textCharCount,
        @JsonProperty("content_hash") String contentHash,
        @JsonProperty("duplicate_of") String duplicateOf,
        String preview,
        @JsonProperty("error_message") String errorMessage,
        @JsonProperty("created_at") String createdAt,
        @JsonProperty("updated_at") String updatedAt
) {
    static DocumentResponse fromEntity(DocumentEntity entity) {
        return new DocumentResponse(
                entity.getId(),
                entity.getUser().getId(),
                entity.getFilename(),
                entity.getContentType(),
                entity.getSizeBytes(),
                entity.getSource(),
                entity.getStatus(),
                entity.getChunkCount(),
                entity.getPageCount(),
                entity.getTextCharCount(),
                entity.getContentHash(),
                entity.getDuplicateOf(),
                entity.getPreview(),
                entity.getErrorMessage(),
                entity.getCreatedAt().toString(),
                entity.getUpdatedAt().toString()
        );
    }
}

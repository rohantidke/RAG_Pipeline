package com.rag.gateway.chat;

public record Citation(
        String chunkId,
        Object documentId,
        Object filename,
        Object pageNumber,
        Object pageCount,
        Object source,
        String textPreview,
        Double rerankScore
) {
}
package com.rag.gateway.rag;

import java.util.List;

public record RagQueryResponse(
        String query,
        String answer,
        boolean abstained,
        double confidence,
        List<RagCitation> citations
) {
}

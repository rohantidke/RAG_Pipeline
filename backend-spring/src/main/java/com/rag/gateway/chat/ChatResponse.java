package com.rag.gateway.chat;

import java.util.List;

public record ChatResponse(
        String answer,
        boolean abstained,
        double confidence,
        List<Citation> citations
) {
}

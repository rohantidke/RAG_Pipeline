package com.rag.gateway.rag;

import java.util.Map;
import java.util.function.Consumer;

public interface RagClient {
    RagQueryResponse query(String message, Integer topK, Map<String, Object> filters);

    void streamQuery(String message, Integer topK, Map<String, Object> filters, Consumer<String> eventConsumer);
}

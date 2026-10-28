package com.rag.gateway.rag;

import org.springframework.http.HttpStatusCode;

public class RagServiceException extends RuntimeException {
    private final HttpStatusCode statusCode;

    public RagServiceException(HttpStatusCode statusCode, String message) {
        super(message);
        this.statusCode = statusCode;
    }

    public HttpStatusCode statusCode() {
        return statusCode;
    }
}

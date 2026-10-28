package com.rag.gateway.error;

import com.rag.gateway.rag.RagServiceException;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.bind.MethodArgumentNotValidException;

import java.time.Instant;
import java.util.concurrent.TimeoutException;

@RestControllerAdvice
public class GlobalExceptionHandler {
    @ExceptionHandler(RagServiceException.class)
    ResponseEntity<ApiError> handleRagServiceException(RagServiceException exception, HttpServletRequest request) {
        HttpStatus status = HttpStatus.valueOf(exception.statusCode().value());
        return ResponseEntity
                .status(status)
                .body(error(status, "RAG service error: " + exception.getMessage(), request));
    }

    @ExceptionHandler(TimeoutException.class)
    ResponseEntity<ApiError> handleTimeout(TimeoutException exception, HttpServletRequest request) {
        HttpStatus status = HttpStatus.GATEWAY_TIMEOUT;
        return ResponseEntity
                .status(status)
                .body(error(status, "RAG service timed out", request));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<ApiError> handleValidation(MethodArgumentNotValidException exception, HttpServletRequest request) {
        HttpStatus status = HttpStatus.BAD_REQUEST;
        String message = exception.getBindingResult().getFieldErrors()
                .stream()
                .findFirst()
                .map(fieldError -> fieldError.getField() + " " + fieldError.getDefaultMessage())
                .orElse("Invalid request");

        return ResponseEntity
                .status(status)
                .body(error(status, message, request));
    }

    private ApiError error(HttpStatus status, String message, HttpServletRequest request) {
        return new ApiError(
                Instant.now(),
                status.value(),
                status.getReasonPhrase(),
                message,
                request.getRequestURI()
        );
    }
}

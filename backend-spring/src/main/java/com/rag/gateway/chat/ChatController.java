package com.rag.gateway.chat;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import com.rag.gateway.rag.RagClient;
import com.rag.gateway.rag.RagQueryResponse;
import com.rag.gateway.user.UserEntity;
import com.rag.gateway.user.UserService;
import jakarta.validation.Valid;
import org.springframework.http.MediaType;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/chat")
public class ChatController {
    private final RagClient ragGatewayClient;
    private final UserService userService;

    public ChatController(RagClient ragGatewayClient, UserService userService) {
        this.ragGatewayClient = ragGatewayClient;
        this.userService = userService;
    }

    @PostMapping
    public ChatResponse chat(
            @Valid @RequestBody ChatRequest request,
            @AuthenticationPrincipal Jwt jwt
    ) {
        return toChatResponse(ragGatewayClient.query(request.message(), request.topK(), mergeFilters(request, jwt)));
    }

    @PostMapping(path = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter stream(
            @Valid @RequestBody ChatRequest request,
            @AuthenticationPrincipal Jwt jwt
    ) {
        SseEmitter emitter = new SseEmitter(0L);
        Map<String, Object> filters = mergeFilters(request, jwt);

        Thread.ofVirtual().start(() -> {
            try {
                ragGatewayClient.streamQuery(
                        request.message(),
                        request.topK(),
                        filters,
                        token -> send(emitter, "token", token)
                );
                send(emitter, "done", "");
                emitter.complete();
            } catch (Exception exception) {
                send(emitter, "token", "{\"token\":\"The RAG service could not answer right now. Make sure a document is indexed, then try again.\"}");
                send(emitter, "done", "");
                emitter.complete();
            }
        });

        return emitter;
    }

    private Map<String, Object> mergeFilters(ChatRequest request, Jwt jwt) {
        Map<String, Object> filters = new HashMap<>();
        if (request.filters() != null) {
            filters.putAll(request.filters());
        }
        if (jwt != null) {
            UserEntity user = userService.requireByUsername(jwt.getSubject());
            filters.put("user_id", user.getId());
        }
        return filters;
    }

    private void send(SseEmitter emitter, String eventName, String data) {
        try {
            emitter.send(SseEmitter.event().name(eventName).data(data));
        } catch (Exception exception) {
            emitter.completeWithError(exception);
        }
    }

    private ChatResponse toChatResponse(RagQueryResponse response) {
        List<Citation> citations = response.citations() == null
                ? List.of()
                : response.citations()
                        .stream()
                        .map(citation -> new Citation(
                                citation.chunkId(),
                                citation.documentId(),
                                citation.filename(),
                                citation.pageNumber(),
                                citation.pageCount(),
                                citation.source(),
                                citation.textPreview(),
                                citation.rerankScore()
                        ))
                        .toList();

        return new ChatResponse(
                response.answer(),
                response.abstained(),
                response.confidence(),
                citations
        );
    }
}

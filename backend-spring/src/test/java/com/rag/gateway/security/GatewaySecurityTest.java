package com.rag.gateway.security;

import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rag.gateway.rag.RagCitation;
import com.rag.gateway.rag.RagClient;
import com.rag.gateway.rag.RagQueryResponse;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
        "gateway.rate-limit.capacity=1",
        "gateway.rate-limit.refill-tokens=1",
        "gateway.rate-limit.refill-period=1h"
})
@ActiveProfiles("test")
@AutoConfigureMockMvc
@Import(GatewaySecurityTest.FakeRagClientConfig.class)
class GatewaySecurityTest {
    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Test
    void healthEndpointIsPublic() throws Exception {
        mockMvc.perform(get("/actuator/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"));
    }

    @Test
    void chatRequiresBearerToken() throws Exception {
        mockMvc.perform(post("/api/chat")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(chatPayload()))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.message").value("Missing or invalid bearer token"));
    }

    @Test
    void tokenEndpointIssuesJwt() throws Exception {
        mockMvc.perform(post("/api/auth/token")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                        {
                          "username": "demo",
                          "password": "demo123"
                        }
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.accessToken").isString())
                .andExpect(jsonPath("$.tokenType").value("Bearer"))
                .andExpect(jsonPath("$.expiresAt").exists());
    }

    @Test
    @DirtiesContext(methodMode = DirtiesContext.MethodMode.BEFORE_METHOD)
    void chatAcceptsJwtAndAppliesRateLimit() throws Exception {
        String token = token();

        mockMvc.perform(post("/api/chat")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(chatPayload()))
                .andExpect(status().isOk())
                .andExpect(header().string("X-RateLimit-Limit", "1"))
                .andExpect(header().string("X-RateLimit-Remaining", "0"))
                .andExpect(jsonPath("$.answer").value("secured answer"));

        mockMvc.perform(post("/api/chat")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(chatPayload()))
                .andExpect(status().isTooManyRequests())
                .andExpect(header().exists("Retry-After"))
                .andExpect(jsonPath("$.message").value("Rate limit exceeded"));
    }

    @Test
    @DirtiesContext(methodMode = DirtiesContext.MethodMode.BEFORE_METHOD)
    void streamAcceptsJwtAndReturnsSseEvents() throws Exception {
        String token = token();

        mockMvc.perform(post("/api/chat/stream")
                        .header("Authorization", "Bearer " + token)
                        .contentType(MediaType.APPLICATION_JSON)
                        .accept(MediaType.TEXT_EVENT_STREAM)
                        .content(chatPayload()))
                .andExpect(status().isOk())
                .andExpect(header().string("X-RateLimit-Limit", "1"))
                .andExpect(request().asyncStarted())
                .andDo(result -> mockMvc.perform(asyncDispatch(result))
                        .andExpect(status().isOk())
                        .andExpect(content().string(containsString("event:token")))
                        .andExpect(content().string(containsString("secured")))
                        .andExpect(content().string(containsString("event:done"))));
    }

    @Test
    void tokenEndpointRejectsBadCredentials() throws Exception {
        mockMvc.perform(post("/api/auth/token")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                        {
                          "username": "demo",
                          "password": "wrong"
                        }
                        """))
                .andExpect(status().isUnauthorized());
    }

    private String token() throws Exception {
        String json = mockMvc.perform(post("/api/auth/token")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                        {
                          "username": "demo",
                          "password": "demo123"
                        }
                        """))
                .andExpect(status().isOk())
                .andReturn()
                .getResponse()
                .getContentAsString();

        JsonNode node = objectMapper.readTree(json);
        return node.get("accessToken").asText();
    }

    private String chatPayload() {
        return """
                {
                  "message": "How does RAG help?",
                  "topK": 3,
                  "filters": {"source": "book"}
                }
                """;
    }

    @TestConfiguration
    static class FakeRagClientConfig {
        @Bean
        @Primary
        RagClient ragClient() {
            return new RagClient() {
                @Override
                public RagQueryResponse query(String message, Integer topK, Map<String, Object> filters) {
                    return new RagQueryResponse(
                            message,
                            "secured answer",
                            false,
                            0.9,
                            List.of(new RagCitation("chunk-1", "doc-1", "book.pdf", 12, 20, "book", "Relevant preview", 0.8))
                    );
                }

                @Override
                public void streamQuery(
                        String message,
                        Integer topK,
                        Map<String, Object> filters,
                        Consumer<String> eventConsumer
                ) {
                    eventConsumer.accept("{\"token\":\"secured \"}");
                    eventConsumer.accept("{\"token\":\"stream\"}");
                }
            };
        }
    }
}

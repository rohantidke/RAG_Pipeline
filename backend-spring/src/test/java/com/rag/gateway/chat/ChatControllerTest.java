package com.rag.gateway.chat;

import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

import com.rag.gateway.rag.RagClient;
import com.rag.gateway.rag.RagCitation;
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
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import static org.hamcrest.Matchers.containsString;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.request;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@ActiveProfiles("test")
@AutoConfigureMockMvc(addFilters = false)
@Import(ChatControllerTest.FakeRagClientConfig.class)
class ChatControllerTest {
    @Autowired
    private MockMvc mockMvc;

    @Test
    void chatReturnsMappedRagAnswer() throws Exception {
        mockMvc.perform(post("/api/chat")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                        {
                          "message": "How does RAG help?",
                          "topK": 3,
                          "filters": {"source": "book"}
                        }
                        """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.answer").value("RAG grounds answers in retrieved context."))
                .andExpect(jsonPath("$.abstained").value(false))
                .andExpect(jsonPath("$.confidence").value(0.82))
                .andExpect(jsonPath("$.citations[0].chunkId").value("chunk-1"))
                .andExpect(jsonPath("$.citations[0].pageNumber").value(12));
    }

    @Test
    void chatRejectsBlankMessage() throws Exception {
        mockMvc.perform(post("/api/chat")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                        {
                          "message": "",
                          "topK": 3
                        }
                        """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.message").exists());
    }

    @Test
    void streamProxiesTokenEvents() throws Exception {
        mockMvc.perform(post("/api/chat/stream")
                        .contentType(MediaType.APPLICATION_JSON)
                        .accept(MediaType.TEXT_EVENT_STREAM)
                        .content("""
                        {
                          "message": "Stream please",
                          "topK": 2,
                          "filters": {}
                        }
                        """))
                .andExpect(status().isOk())
                .andExpect(request().asyncStarted())
                .andDo(result -> mockMvc.perform(asyncDispatch(result))
                        .andExpect(status().isOk())
                        .andExpect(content().string(containsString("event:token")))
                        .andExpect(content().string(containsString("hello")))
                        .andExpect(content().string(containsString("event:done"))));
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
                            "RAG grounds answers in retrieved context.",
                            false,
                            0.82,
                            List.of(new RagCitation("chunk-1", "doc-1", "book.pdf", 12, 20, "book", "Relevant preview", 0.7))
                    );
                }

                @Override
                public void streamQuery(
                        String message,
                        Integer topK,
                        Map<String, Object> filters,
                        Consumer<String> eventConsumer
                ) {
                    eventConsumer.accept("{\"token\":\"hello \"}");
                    eventConsumer.accept("{\"token\":\"world\"}");
                }
            };
        }
    }
}

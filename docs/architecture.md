# 🏗️ System Architecture & Engineering Design

This document details the architecture, component interaction, and design patterns of the **Full-Stack Retrieval-Augmented Generation (RAG) Pipeline**.

---

## 📐 Architecture Diagrams

### 1. Detailed Monochrome System Architecture
![RAG Application Architecture](./images/system_architecture.png)

- **High-Resolution Image**: [`docs/images/system_architecture.png`](./images/system_architecture.png)
- **Editable Vector Source**: [`docs/images/architecture.svg`](./images/architecture.svg)

### 2. Multi-Tier Component Flow
![Architecture Component Flow](./images/architecture_flow.png)

- **Component Tier Image**: [`docs/images/architecture_flow.png`](./images/architecture_flow.png)

---

## 🧩 Architectural Topology

```mermaid
flowchart TD
    User["User / Client / Postman"]

    subgraph Frontend["Next.js 15 Frontend (:3000)"]
        UI["Dark Mode Chat UI"]
        NextAuth["/api/token & /api/register"]
        NextDocs["/api/documents proxy"]
        NextChat["/api/chat proxy"]
        NextStream["/api/chat/stream SSE proxy"]
    end

    subgraph Gateway["Spring Boot 3.4 Gateway (:8080)"]
        Auth["Register / Login Controller"]
        JWT["JWT Bearer Validation"]
        RateLimit["Token Bucket Rate Limiter"]
        DocAPI["Document Management API"]
        ChatAPI["Chat & Streaming Proxy"]
        MetadataDB[("PostgreSQL Metadata Store")]
    end

    subgraph RagService["FastAPI RAG Service (:8000)"]
        Upload["Upload & SHA-256 Validation"]
        Indexing["Asynchronous Document Indexing"]
        Chunking["Page-Aware Semantic Chunking"]
        Retrieval["Vector Similarity Retrieval"]
        Reranker["Cross-Encoder Reranking"]
        Prompt["Grounded Prompt Construction"]
        Answer["Markdown & Citation Formatting"]
    end

    subgraph VectorLayer["Vector & Model Engine"]
        Chroma[("ChromaDB Vector Store")]
        Embeddings["SentenceTransformers (all-mpnet-base-v2)"]
        RerankModel["MS-MARCO MiniLM Reranker"]
        LLM["Extractive Fallback or Local Ollama"]
    end

    User --> UI
    UI --> NextAuth
    UI --> NextDocs
    UI --> NextChat
    UI --> NextStream

    NextAuth --> Auth
    NextDocs --> JWT
    NextChat --> JWT
    NextStream --> JWT

    JWT --> RateLimit
    RateLimit --> DocAPI
    RateLimit --> ChatAPI
    Auth --> MetadataDB
    DocAPI --> MetadataDB

    DocAPI --> Upload
    Upload --> Indexing
    Indexing --> Chunking
    Chunking --> Embeddings
    Chunking --> Chroma

    ChatAPI --> Retrieval
    Retrieval --> Chroma
    Retrieval --> RerankModel
    Retrieval --> Prompt
    Prompt --> LLM
    LLM --> Answer
    Answer --> ChatAPI
    ChatAPI --> UI
```

---

## 🔄 End-to-End Request Lifecycles

### 1. Document Ingestion Lifecycle
```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Gateway as Spring Gateway (:8080)
    participant DB as PostgreSQL (:5432)
    participant RAG as FastAPI Service (:8000)
    participant Chroma as ChromaDB

    User->>Gateway: POST /api/documents/upload (Multipart File + JWT)
    Gateway->>Gateway: Validate JWT & User Principal
    Gateway->>Gateway: Enforce Rate Limiting (Token Bucket)
    Gateway->>DB: Record Document Metadata (status=processing)
    Gateway->>RAG: Forward Upload (filename, bytes, user_id)
    RAG->>RAG: Compute SHA-256 (De-duplication Check)
    RAG-->>Gateway: 200 OK (Document queued)
    Gateway-->>User: 200 OK (DocumentRecord)

    Note over RAG,Chroma: Async Background Task
    RAG->>RAG: Extract Text (PDF / TXT / Markdown)
    RAG->>RAG: Page-Aware Semantic Chunking
    RAG->>RAG: Generate Dense Embeddings (all-mpnet-base-v2)
    RAG->>Chroma: Upsert Vectors + Chunk Metadata
    RAG->>Gateway: Update Document Status (status=indexed, chunks=N)
```

### 2. Grounded Query & SSE Streaming Lifecycle
```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Frontend as Next.js (:3000)
    participant Gateway as Spring Gateway (:8080)
    participant RAG as FastAPI Service (:8000)
    participant Chroma as ChromaDB
    participant LLM as LLM / Extractive Engine

    User->>Frontend: Enter query in Chat Box
    Frontend->>Gateway: POST /api/chat/stream (Query + JWT)
    Gateway->>Gateway: Authenticate JWT & Rate Limit Check
    Gateway->>RAG: POST /query/stream (Query, user_id, top_k)
    RAG->>RAG: Encode Query Embedding
    RAG->>Chroma: Query Cosine Similarity (Filter: user_id)
    Chroma-->>RAG: Return Top-K Candidate Chunks
    RAG->>RAG: Cross-Encoder Reranking
    RAG->>RAG: Build Grounded Context Prompt
    RAG->>LLM: Stream Answer Tokens / Extract Grounded Sentences
    LLM-->>RAG: Token Stream
    RAG-->>Gateway: SSE (event: token, citations, done)
    Gateway-->>Frontend: SSE Stream Relay
    Frontend-->>User: Smooth Token Rendering with Citations
```

---

## 🛡️ Security, Reliability & Scaling Patterns

1. **Defense-in-Depth Authentication**:
   - Spring Security Resource Server with stateless JWT Bearer token verification.
   - Demo user seeder with BCrypt password hashing.
   - User isolation enforced in metadata database and propagated to vector retrieval filters (`user_id`).

2. **Traffic Governance**:
   - Token bucket rate limiting filter on API gateway preventing denial-of-service and abusive querying.
   - Configurable capacity, refill tokens, and refill time windows via environment variables.

3. **Fault Tolerance**:
   - Dual-mode generation: Local Ollama LLM support with automatic fallback to high-precision extractive grounding.
   - Asynchronous worker queues preventing large document indexing from blocking API gateway threads.

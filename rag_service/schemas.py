from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class IndexLoadRequest(BaseModel):
    csv_path: str | None = Field(default=None, description="Optional path to an embeddings CSV index.")
    embedding_model_name: str | None = Field(default=None, description="Override embedding model.")
    reranker_model_name: str | None = Field(default=None, description="Override reranker model. Use null to disable.")
    reset_vector_store: bool | None = Field(
        default=None,
        description="When true, rebuild the Chroma collection from the CSV import source.",
    )


class IndexStatus(BaseModel):
    loaded: bool
    chunk_count: int
    embedding_dim: int | None = None
    index_path: str | None = None
    vector_backend: str | None = None
    vector_store_path: str | None = None
    collection_name: str | None = None
    device: str | None = None


class DocumentRecord(BaseModel):
    document_id: str
    user_id: str | None = None
    filename: str
    content_type: str | None = None
    size_bytes: int
    source: str
    status: str
    chunk_count: int
    created_at: str
    updated_at: str | None = None
    page_count: int = 0
    text_char_count: int = 0
    content_hash: str | None = None
    duplicate_of: str | None = None
    preview: str = ""
    error_message: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentRecord]


class DocumentUploadResponse(DocumentRecord):
    message: str


class RetrievalRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)
    filters: dict[str, Any] | None = None
    use_cache: bool = True


class RetrievedChunk(BaseModel):
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    dense_score: float = 0.0
    bm25_score: float = 0.0
    fusion_score: float = 0.0
    rerank_score: float | None = None


class RetrievalResponse(BaseModel):
    query: str
    rewritten_query: str
    top_k: int
    confidence: float
    results: list[RetrievedChunk]


class QueryRequest(RetrievalRequest):
    max_context_chars: int | None = Field(default=None, ge=500, le=20000)


class Citation(BaseModel):
    chunk_id: str
    document_id: Any = None
    filename: Any = None
    page_number: Any = None
    page_count: Any = None
    source: Any = None
    text_preview: str | None = None
    rerank_score: float | None = None


class QueryResponse(BaseModel):
    query: str
    rewritten_query: str
    answer: str
    abstained: bool
    confidence: float
    citations: list[Citation]
    retrieval: RetrievalResponse


class ErrorResponse(BaseModel):
    detail: str
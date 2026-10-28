from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServiceSettings:
    index_path: Path
    documents_dir: Path
    documents_registry_path: Path
    vector_backend: str
    chroma_persist_dir: Path
    chroma_collection_name: str
    reset_vector_store_on_load: bool
    embedding_model_name: str
    reranker_model_name: str | None
    model_local_files_only: bool
    llm_provider: str
    ollama_base_url: str
    ollama_model: str
    request_timeout_seconds: float
    max_upload_bytes: int
    max_extracted_chars: int
    chunk_max_tokens: int
    chunk_overlap_sentences: int
    chunk_min_tokens: int
    index_worker_count: int


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _bool_env(name: str, default: bool) -> bool:
    value = _optional_env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def load_settings() -> ServiceSettings:
    reranker = _optional_env("RAG_RERANKER_MODEL") or "cross-encoder/ms-marco-MiniLM-L-6-v2"
    if reranker.lower() in {"none", "off", "false", "0"}:
        reranker = None

    return ServiceSettings(
        index_path=Path(os.getenv("RAG_INDEX_PATH", "text_chunks_and_embeddings_df.csv")),
        documents_dir=Path(os.getenv("RAG_DOCUMENTS_DIR", "documents")),
        documents_registry_path=Path(os.getenv("RAG_DOCUMENTS_REGISTRY", "documents/registry.json")),
        vector_backend=os.getenv("RAG_VECTOR_BACKEND", "chroma").strip().lower(),
        chroma_persist_dir=Path(os.getenv("CHROMA_PERSIST_DIR", "chroma_db")),
        chroma_collection_name=os.getenv("CHROMA_COLLECTION_NAME", "rag_chunks"),
        reset_vector_store_on_load=_bool_env("RAG_RESET_VECTOR_STORE_ON_LOAD", False),
        embedding_model_name=os.getenv("RAG_EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2"),
        reranker_model_name=reranker,
        model_local_files_only=_bool_env("RAG_MODEL_LOCAL_FILES_ONLY", True),
        llm_provider=os.getenv("RAG_LLM_PROVIDER", "extractive").strip().lower(),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2"),
        request_timeout_seconds=float(os.getenv("RAG_REQUEST_TIMEOUT_SECONDS", "120")),
        max_upload_bytes=int(os.getenv("RAG_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024))),
        max_extracted_chars=int(os.getenv("RAG_MAX_EXTRACTED_CHARS", "2000000")),
        chunk_max_tokens=int(os.getenv("RAG_CHUNK_MAX_TOKENS", "300")),
        chunk_overlap_sentences=int(os.getenv("RAG_CHUNK_OVERLAP_SENTENCES", "1")),
        chunk_min_tokens=int(os.getenv("RAG_CHUNK_MIN_TOKENS", "8")),
        index_worker_count=int(os.getenv("RAG_INDEX_WORKERS", "1")),
    )

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .config import load_settings
from .schemas import (
    DocumentListResponse,
    DocumentRecord,
    DocumentUploadResponse,
    IndexLoadRequest,
    IndexStatus,
    QueryRequest,
    QueryResponse,
    RetrievalRequest,
    RetrievalResponse,
)
from .service import RAGService


settings = load_settings()
rag_service = RAGService(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.index_path.exists():
        try:
            rag_service.load_index()
        except Exception:
            # Keep startup resilient. /index/load will return details when called explicitly.
            pass
    rag_service.enqueue_processing_documents()
    yield


app = FastAPI(
    title="RAG Service",
    version="0.1.0",
    description="Internal FastAPI service for retrieval, prompt construction, and grounded RAG answers.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "index": rag_service.status()}


@app.get("/index/status", response_model=IndexStatus)
def index_status() -> dict[str, object]:
    return rag_service.status()


@app.post("/index/load", response_model=IndexStatus)
def load_index(request: IndexLoadRequest) -> dict[str, object]:
    provided_fields = getattr(request, "model_fields_set", getattr(request, "__fields_set__", set()))
    reranker_model_name = (
        request.reranker_model_name
        if "reranker_model_name" in provided_fields
        else settings.reranker_model_name
    )
    try:
        return rag_service.load_index(
            csv_path=request.csv_path,
            embedding_model_name=request.embedding_model_name,
            reranker_model_name=reranker_model_name,
            use_default_reranker="reranker_model_name" not in provided_fields,
            reset_vector_store=request.reset_vector_store,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/documents", response_model=DocumentListResponse)
def list_documents(user_id: str | None = None) -> dict[str, object]:
    return rag_service.list_documents(user_id=user_id)


@app.get("/documents/{document_id}", response_model=DocumentRecord)
def get_document(document_id: str, user_id: str | None = None) -> dict[str, object]:
    try:
        return rag_service.get_document(document_id, user_id=user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    source: str | None = Form(default=None),
    user_id: str | None = Form(default=None),
) -> dict[str, object]:
    try:
        response = rag_service.upload_document(
            filename=file.filename or "document",
            content=await file.read(),
            content_type=file.content_type,
            source=source,
            user_id=user_id,
        )
        if response.get("status") == "processing":
            rag_service.enqueue_document_index(str(response["document_id"]))
        return response
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/documents/{document_id}", response_model=DocumentRecord)
def delete_document(document_id: str, user_id: str | None = None) -> dict[str, object]:
    try:
        return rag_service.delete_document(document_id, user_id=user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/retrieve", response_model=RetrievalResponse)
def retrieve(request: RetrievalRequest) -> dict[str, object]:
    try:
        return rag_service.retrieve(
            query=request.query,
            top_k=request.top_k,
            filters=request.filters,
            use_cache=request.use_cache,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> dict[str, object]:
    try:
        return rag_service.query(
            query=request.query,
            top_k=request.top_k,
            filters=request.filters,
            max_context_chars=request.max_context_chars,
            use_cache=request.use_cache,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _sse_stream(iterator: Iterator[str]) -> Iterator[str]:
    for chunk in iterator:
        if chunk:
            yield f"data: {json.dumps({'token': chunk})}\n\n"
    yield f"data: {json.dumps({'done': True})}\n\n"


@app.post("/query/stream")
def query_stream_endpoint(request: QueryRequest) -> StreamingResponse:
    try:
        iterator = rag_service.query_stream(
            query=request.query,
            top_k=request.top_k,
            filters=request.filters,
            max_context_chars=request.max_context_chars,
            use_cache=request.use_cache,
        )
        return StreamingResponse(_sse_stream(iterator), media_type="text/event-stream")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

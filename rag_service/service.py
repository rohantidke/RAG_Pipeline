from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, RLock
from typing import Any

import numpy as np
import torch

from advanced_rag import AdvancedRAGEngine, RAGConfig

from .config import ServiceSettings
from .llm import build_llm_callable
from .vector_store import ChromaVectorStore


ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown"}
ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
    "application/octet-stream",
}


class RAGService:
    def __init__(self, settings: ServiceSettings) -> None:
        self.settings = settings
        self._lock = Lock()
        self._registry_lock = RLock()
        self._engine: AdvancedRAGEngine | None = None
        self._vector_store: ChromaVectorStore | None = None
        self._index_path: Path | None = None
        self._index_executor = ThreadPoolExecutor(
            max_workers=max(1, self.settings.index_worker_count),
            thread_name_prefix="rag-index",
        )
        self._index_jobs: dict[str, Future[dict[str, Any]]] = {}
        self.settings.documents_dir.mkdir(parents=True, exist_ok=True)
        self.settings.documents_registry_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def engine(self) -> AdvancedRAGEngine:
        if self._engine is None:
            raise RuntimeError("RAG index is not loaded. Call /index/load first.")
        return self._engine

    def status(self) -> dict[str, Any]:
        if self._engine is None:
            return {
                "loaded": False,
                "chunk_count": 0,
                "embedding_dim": None,
                "index_path": str(self._index_path) if self._index_path else None,
                "vector_backend": self.settings.vector_backend,
                "vector_store_path": str(self.settings.chroma_persist_dir)
                if self.settings.vector_backend == "chroma"
                else None,
                "collection_name": self.settings.chroma_collection_name
                if self.settings.vector_backend == "chroma"
                else None,
                "device": "cuda" if torch.cuda.is_available() else "cpu",
            }

        embedding_dim = None
        if self._engine.embeddings is not None and self._engine.embeddings.ndim == 2:
            embedding_dim = int(self._engine.embeddings.shape[1])
        elif self._vector_store is not None:
            embedding_dim = self._vector_store.embedding_dim

        return {
            "loaded": True,
            "chunk_count": self._vector_store.count if self._vector_store is not None else len(self._engine.chunks),
            "embedding_dim": embedding_dim,
            "index_path": str(self._index_path) if self._index_path else None,
            "vector_backend": self.settings.vector_backend,
            "vector_store_path": str(self.settings.chroma_persist_dir)
            if self._vector_store is not None
            else None,
            "collection_name": self.settings.chroma_collection_name
            if self._vector_store is not None
            else None,
            "device": self._engine.device,
        }

    def load_index(
        self,
        csv_path: str | None = None,
        embedding_model_name: str | None = None,
        reranker_model_name: str | None = None,
        use_default_reranker: bool = True,
        reset_vector_store: bool | None = None,
    ) -> dict[str, Any]:
        path = Path(csv_path) if csv_path else self.settings.index_path
        resolved_reranker = self.settings.reranker_model_name if use_default_reranker else reranker_model_name
        config = RAGConfig(
            embedding_model_name=embedding_model_name or self.settings.embedding_model_name,
            reranker_model_name=resolved_reranker,
            model_local_files_only=self.settings.model_local_files_only,
        )

        engine = AdvancedRAGEngine(config=config)
        vector_store: ChromaVectorStore | None = None

        if self.settings.vector_backend == "chroma":
            vector_store = ChromaVectorStore(
                persist_dir=self.settings.chroma_persist_dir,
                collection_name=self.settings.chroma_collection_name,
            )
            vector_store.import_embeddings_csv(
                path,
                reset=self.settings.reset_vector_store_on_load
                if reset_vector_store is None
                else reset_vector_store,
            )
        elif self.settings.vector_backend == "memory":
            engine.load_index_from_csv(path)
        else:
            raise ValueError(f"Unsupported RAG_VECTOR_BACKEND: {self.settings.vector_backend}")

        with self._lock:
            self._engine = engine
            self._vector_store = vector_store
            self._index_path = path

        return self.status()

    def enqueue_document_index(self, document_id: str) -> bool:
        with self._lock:
            current = self._index_jobs.get(document_id)
            if current is not None and not current.done():
                return False
            future = self._index_executor.submit(self.index_document, document_id)
            self._index_jobs[document_id] = future
            future.add_done_callback(lambda _future: self._forget_index_job(document_id))
            return True

    def enqueue_processing_documents(self) -> int:
        queued = 0
        registry = self._load_registry()
        for document_id, record in registry.items():
            if record.get("status") != "processing":
                continue
            if self._find_saved_document_path(document_id) is None:
                self._mark_document_failed(
                    document_id,
                    record,
                    "Uploaded file is missing from document storage.",
                )
                continue
            if self.enqueue_document_index(document_id):
                queued += 1
        return queued

    def _forget_index_job(self, document_id: str) -> None:
        with self._lock:
            current = self._index_jobs.get(document_id)
            if current is not None and current.done():
                self._index_jobs.pop(document_id, None)

    def list_documents(self, user_id: str | None = None) -> dict[str, Any]:
        self.enqueue_processing_documents()
        records = list(self._load_registry().values())
        if user_id:
            records = [record for record in records if str(record.get("user_id")) == str(user_id)]
        records.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return {"documents": records}

    def get_document(self, document_id: str, user_id: str | None = None) -> dict[str, Any]:
        registry = self._load_registry()
        if document_id not in registry:
            raise KeyError(f"Document not found: {document_id}")
        record = registry[document_id]
        if user_id and str(record.get("user_id")) != str(user_id):
            raise KeyError(f"Document not found: {document_id}")
        return record

    def upload_document(
        self,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        source: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not content:
            raise ValueError("Uploaded document is empty.")
        if len(content) > self.settings.max_upload_bytes:
            max_mb = self.settings.max_upload_bytes / (1024 * 1024)
            raise ValueError(f"Uploaded document is too large. Max size is {max_mb:.0f} MB.")

        safe_filename = self._safe_filename(filename)
        self._validate_document_type(safe_filename, content_type)
        content_hash = hashlib.sha256(content).hexdigest()
        resolved_source = source.strip() if source and source.strip() else safe_filename
        resolved_user_id = user_id.strip() if user_id and user_id.strip() else "anonymous"
        registry = self._load_registry()

        duplicate = self._find_duplicate(registry, content_hash, resolved_user_id)
        if duplicate is not None:
            duplicate_id, duplicate_record = duplicate
            return {
                **duplicate_record,
                "duplicate_of": duplicate_id,
                "message": "Duplicate document detected. Existing indexed document was reused.",
            }

        document_id = uuid.uuid4().hex
        saved_path = self.settings.documents_dir / f"{document_id}-{safe_filename}"
        created_at = self._now()
        record = {
            "document_id": document_id,
            "user_id": resolved_user_id,
            "filename": safe_filename,
            "content_type": content_type,
            "size_bytes": len(content),
            "source": resolved_source,
            "status": "processing",
            "chunk_count": 0,
            "page_count": 0,
            "text_char_count": 0,
            "content_hash": content_hash,
            "duplicate_of": None,
            "preview": "",
            "error_message": None,
            "created_at": created_at,
            "updated_at": created_at,
        }
        with self._registry_lock:
            registry = self._load_registry()
            registry[document_id] = record
            self._save_registry(registry)
        saved_path.write_bytes(content)
        return {**record, "message": "Document uploaded. Indexing started in the background."}

    def index_document(self, document_id: str) -> dict[str, Any]:
        registry = self._load_registry()
        if document_id not in registry:
            raise KeyError(f"Document not found: {document_id}")

        base_record = registry[document_id]
        if base_record.get("status") == "indexed":
            return {**base_record, "message": "Document is already indexed."}

        saved_path = self._find_saved_document_path(document_id)
        if saved_path is None:
            return self._mark_document_failed(
                document_id,
                base_record,
                "Uploaded file is missing from document storage.",
            )

        try:
            extracted = self._extract_document_pages(saved_path, base_record.get("content_type"))
            pages = extracted["pages"]
            page_count = int(extracted["page_count"])
            text_char_count = sum(len(page["text"]) for page in pages)

            if not pages:
                raise ValueError("No readable text was found. Scanned/image-only PDFs need OCR before indexing.")
            if text_char_count > self.settings.max_extracted_chars:
                max_chars = self.settings.max_extracted_chars
                raise ValueError(f"Extracted text is too large to index safely. Max characters: {max_chars}.")

            preview = self._preview("\n\n".join(page["text"] for page in pages), limit=360)
            docs = [
                {
                    "text": page["text"],
                    "document_id": document_id,
                    "user_id": base_record.get("user_id") or "anonymous",
                    "filename": base_record["filename"],
                    "source": base_record["source"],
                    "page_number": page.get("page_number"),
                    "page_count": page_count,
                    "content_hash": base_record.get("content_hash"),
                }
                for page in pages
            ]

            engine = self._ensure_engine()
            chunks = engine.build_chunks_from_texts(
                docs,
                max_tokens=self.settings.chunk_max_tokens,
                overlap_sentences=self.settings.chunk_overlap_sentences,
                min_tokens=self.settings.chunk_min_tokens,
            )
            if not chunks:
                raise ValueError("Document text was too small to create searchable chunks.")

            for index, chunk in enumerate(chunks):
                chunk.chunk_id = f"{document_id}-chunk-{index:05d}"
                chunk.metadata["document_id"] = document_id
                chunk.metadata["user_id"] = base_record.get("user_id") or "anonymous"
                chunk.metadata["filename"] = base_record["filename"]
                chunk.metadata["source"] = base_record["source"]
                chunk.metadata["page_count"] = page_count
                chunk.metadata["chunk_index"] = index
                chunk.metadata["content_hash"] = base_record.get("content_hash")
                chunk.metadata["text_preview"] = self._preview(chunk.text)

            texts = [chunk.text for chunk in chunks]
            embeddings = engine._get_embedding_model().encode(
                texts,
                batch_size=32,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            embedding_matrix = AdvancedRAGEngine._normalize_embedding_matrix(
                [np.asarray(embedding, dtype=np.float32) for embedding in embeddings]
            )

            if self.settings.vector_backend == "chroma":
                vector_store = self._ensure_vector_store()
                vector_store.delete_document(document_id)
                vector_store.upsert_texts(
                    ids=[chunk.chunk_id for chunk in chunks],
                    documents=texts,
                    embeddings=[embedding.astype(np.float32).tolist() for embedding in embedding_matrix],
                    metadatas=[chunk.metadata for chunk in chunks],
                )
            elif self.settings.vector_backend == "memory":
                for index, embedding in enumerate(embedding_matrix):
                    chunks[index].embedding = embedding
                existing_chunks = [chunk for chunk in engine.chunks if chunk.metadata.get("document_id") != document_id]
                engine.build_index_from_chunks([*existing_chunks, *chunks])
            else:
                raise ValueError(f"Unsupported RAG_VECTOR_BACKEND: {self.settings.vector_backend}")

            record = {
                **base_record,
                "status": "indexed",
                "chunk_count": len(chunks),
                "page_count": page_count,
                "text_char_count": text_char_count,
                "preview": preview,
                "error_message": None,
                "updated_at": self._now(),
            }
            with self._registry_lock:
                registry = self._load_registry()
                registry[document_id] = record
                self._save_registry(registry)
            return {**record, "message": "Document indexed."}
        except Exception as exc:
            return self._mark_document_failed(document_id, base_record, self._friendly_error(exc))

    def delete_document(self, document_id: str, user_id: str | None = None) -> dict[str, Any]:
        with self._registry_lock:
            registry = self._load_registry()
            if document_id not in registry:
                raise KeyError(f"Document not found: {document_id}")

            record = registry[document_id]
            if user_id and str(record.get("user_id")) != str(user_id):
                raise KeyError(f"Document not found: {document_id}")

            removed = registry.pop(document_id)
            self._save_registry(registry)

        if self._vector_store is not None:
            self._vector_store.delete_document(document_id)
        elif self.settings.vector_backend == "chroma":
            self._ensure_vector_store().delete_document(document_id)

        for path in self.settings.documents_dir.glob(f"{document_id}-*"):
            path.unlink(missing_ok=True)

        return removed

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        if self._vector_store is not None:
            return self._retrieve_from_vector_store(
                query=query,
                top_k=top_k,
                filters=filters,
            )
        return self.engine.retrieve(query=query, top_k=top_k, filters=filters, use_cache=use_cache)

    def query(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
        max_context_chars: int | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        engine = self.engine
        original_max_context_chars = engine.config.max_context_chars
        if max_context_chars is not None:
            engine.config.max_context_chars = max_context_chars

        try:
            if self._vector_store is not None:
                return self._answer_from_vector_store(
                    query=query,
                    top_k=top_k,
                    filters=filters,
                    use_cache=use_cache,
                )

            llm_callable = build_llm_callable(self.settings)
            return engine.answer(
                query=query,
                llm_callable=llm_callable,
                filters=filters,
                top_k=top_k,
                use_cache=use_cache,
            )
        finally:
            engine.config.max_context_chars = original_max_context_chars

    def query_stream(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
        max_context_chars: int | None = None,
        use_cache: bool = True,
    ) -> Iterator[str]:
        engine = self.engine
        original_max_context_chars = engine.config.max_context_chars
        if max_context_chars is not None:
            engine.config.max_context_chars = max_context_chars

        try:
            if self._vector_store is not None:
                retrieval = self._retrieve_from_vector_store(query=query, top_k=top_k, filters=filters)
            else:
                retrieval = engine.retrieve(query=query, top_k=top_k, filters=filters, use_cache=use_cache)
                
            confidence = retrieval["confidence"]

            if not retrieval["results"] or confidence < engine.config.abstain_threshold:
                yield "I do not have enough grounded evidence in the retrieved context to answer reliably."
                return

            context = engine.build_cited_context(retrieval)
            prompt = (
                "You are a careful RAG assistant. Answer in polished Markdown, like a helpful ChatGPT response. "
                "Use only the cited context below. If the answer is not present, say so clearly. "
                "Keep the answer concise, direct, and grounded. Include useful bullets only when they improve readability.\n\n"
                f"Question: {query}\n\n"
                "CITED CONTEXT:\n"
                f"{context}\n\n"
                "Return Markdown with:\n"
                "- A direct answer first.\n"
                "- A short explanation grounded in the context.\n"
                "- Do not invent facts outside the context.\n"
            )

            from .llm import build_llm_stream_callable
            stream_callable = build_llm_stream_callable(self.settings)
            
            for chunk in stream_callable(prompt):
                yield chunk
            
            citations = [self._citation_from_result(item) for item in retrieval["results"]]
            source_text = self._format_markdown_answer("", citations)
            if source_text:
                yield f"\n\n{source_text}"

        finally:
            engine.config.max_context_chars = original_max_context_chars

    def _retrieve_from_vector_store(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        engine = self.engine
        if self._vector_store is None:
            raise RuntimeError("Vector store is not initialized.")

        rewritten_query = engine.rewrite_query(query)
        chosen_top_k = top_k or engine.adaptive_top_k(query)
        if chosen_top_k <= 0:
            raise ValueError("top_k must be greater than zero.")

        if self._vector_store.count == 0:
            return {
                "query": query,
                "rewritten_query": rewritten_query,
                "top_k": chosen_top_k,
                "confidence": 0.0,
                "results": [],
            }

        query_embedding = engine._get_embedding_model().encode(
            rewritten_query,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        candidate_top_k = min(
            max(chosen_top_k * engine.config.candidate_pool_multiplier, chosen_top_k),
            self._vector_store.count,
        )
        search_results = self._vector_store.query(
            query_embedding=query_embedding,
            top_k=candidate_top_k,
            filters=filters,
        )

        results = []
        for index, item in enumerate(search_results):
            text = engine._mask_pii(item.text) if engine.config.pii_masking_enabled else item.text
            results.append(
                {
                    "chunk_id": item.chunk_id,
                    "index": index,
                    "text": text,
                    "metadata": item.metadata,
                    "dense_score": item.score,
                    "bm25_score": 0.0,
                    "fusion_score": item.score,
                    "rerank_score": item.score,
                }
            )

        if engine.reranker is not None and len(results) > 0:
            results = engine._rerank(rewritten_query, results)

        selected = results[:chosen_top_k]
        confidence = 0.0
        if selected:
            confidence = float(sum(item["rerank_score"] for item in selected) / len(selected))

        return {
            "query": query,
            "rewritten_query": rewritten_query,
            "top_k": chosen_top_k,
            "confidence": confidence,
            "results": selected,
        }

    def _answer_from_vector_store(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        engine = self.engine
        retrieval = self._retrieve_from_vector_store(query=query, top_k=top_k, filters=filters)
        confidence = retrieval["confidence"]

        if not retrieval["results"] or confidence < engine.config.abstain_threshold:
            return {
                "query": query,
                "rewritten_query": retrieval["rewritten_query"],
                "answer": "I do not have enough grounded evidence in the retrieved context to answer reliably.",
                "abstained": True,
                "confidence": confidence,
                "citations": [],
                "retrieval": retrieval,
            }

        context = engine.build_cited_context(retrieval)
        prompt = (
            "You are a careful RAG assistant. Answer in polished Markdown, like a helpful ChatGPT response. "
            "Use only the cited context below. If the answer is not present, say so clearly. "
            "Keep the answer concise, direct, and grounded. Include useful bullets only when they improve readability.\n\n"
            f"Question: {query}\n\n"
            "CITED CONTEXT:\n"
            f"{context}\n\n"
            "Return Markdown with:\n"
            "- A direct answer first.\n"
            "- A short explanation grounded in the context.\n"
            "- Do not invent facts outside the context.\n"
        )

        raw_answer = build_llm_callable(self.settings)(prompt)
        citations = [self._citation_from_result(item) for item in retrieval["results"]]
        answer = self._format_markdown_answer(raw_answer, citations)

        return {
            "query": query,
            "rewritten_query": retrieval["rewritten_query"],
            "answer": answer,
            "abstained": False,
            "confidence": confidence,
            "citations": citations,
            "retrieval": retrieval,
        }

    def _ensure_engine(self) -> AdvancedRAGEngine:
        if self._engine is None:
            config = RAGConfig(
                embedding_model_name=self.settings.embedding_model_name,
                reranker_model_name=self.settings.reranker_model_name,
                model_local_files_only=self.settings.model_local_files_only,
            )
            with self._lock:
                if self._engine is None:
                    self._engine = AdvancedRAGEngine(config=config)
        return self._engine

    def _ensure_vector_store(self) -> ChromaVectorStore:
        if self._vector_store is None:
            with self._lock:
                if self._vector_store is None:
                    self._vector_store = ChromaVectorStore(
                        persist_dir=self.settings.chroma_persist_dir,
                        collection_name=self.settings.chroma_collection_name,
                    )
        return self._vector_store

    def _load_registry(self) -> dict[str, dict[str, Any]]:
        if not self.settings.documents_registry_path.exists():
            return {}
        with self.settings.documents_registry_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            return {}
        return {str(key): dict(value) for key, value in data.items()}

    def _save_registry(self, registry: dict[str, dict[str, Any]]) -> None:
        with self.settings.documents_registry_path.open("w", encoding="utf-8") as file:
            json.dump(registry, file, indent=2, sort_keys=True)

    @staticmethod
    def _safe_filename(filename: str) -> str:
        name = Path(filename or "document.txt").name
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
        return name or "document.txt"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _preview(text: str, limit: int = 240) -> str:
        collapsed = " ".join(text.split())
        if len(collapsed) <= limit:
            return collapsed
        return f"{collapsed[: limit - 1].rstrip()}..."

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        message = str(exc).strip()
        if not message:
            return "Document indexing failed. Check service logs for details."
        return message

    @staticmethod
    def _find_duplicate(
        registry: dict[str, dict[str, Any]],
        content_hash: str,
        user_id: str,
    ) -> tuple[str, dict[str, Any]] | None:
        for document_id, record in registry.items():
            if (
                record.get("content_hash") == content_hash
                and record.get("user_id") == user_id
                and record.get("status") != "failed"
            ):
                return document_id, record
        return None

    def _find_saved_document_path(self, document_id: str) -> Path | None:
        matches = sorted(self.settings.documents_dir.glob(f"{document_id}-*"))
        return matches[0] if matches else None

    def _mark_document_failed(
        self,
        document_id: str,
        base_record: dict[str, Any],
        message: str,
    ) -> dict[str, Any]:
        failed = {
            **base_record,
            "status": "failed",
            "error_message": message,
            "updated_at": self._now(),
        }
        with self._registry_lock:
            registry = self._load_registry()
            registry[document_id] = failed
            self._save_registry(registry)
        if self._vector_store is not None:
            self._vector_store.delete_document(document_id)
        return {**failed, "message": message}

    @staticmethod
    def _validate_document_type(filename: str, content_type: str | None) -> None:
        suffix = Path(filename).suffix.lower()
        normalized_type = (content_type or "").split(";")[0].strip().lower()
        if suffix in ALLOWED_EXTENSIONS:
            return
        if normalized_type.startswith("text/") or normalized_type in ALLOWED_CONTENT_TYPES:
            return
        raise ValueError("Unsupported document type. Upload PDF, TXT, or Markdown files.")

    @staticmethod
    def _extract_document_pages(path: Path, content_type: str | None = None) -> dict[str, Any]:
        suffix = path.suffix.lower()
        if suffix == ".pdf" or content_type == "application/pdf":
            try:
                import fitz
            except ImportError as exc:
                raise RuntimeError("PyMuPDF is required for PDF uploads.") from exc

            pages = []
            with fitz.open(path) as doc:
                page_count = int(doc.page_count)
                for page_index, page in enumerate(doc, start=1):
                    text = page.get_text("text").strip()
                    if text:
                        pages.append({"page_number": page_index, "text": text})
            return {"pages": pages, "page_count": page_count}

        if suffix in {".txt", ".md", ".markdown"} or (content_type or "").startswith("text/"):
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            pages = [{"page_number": 1, "text": text}] if text else []
            return {"pages": pages, "page_count": 1 if text else 0}

        raise ValueError("Unsupported document type. Upload PDF, TXT, or Markdown files.")

    @staticmethod
    def _citation_from_result(item: dict[str, Any]) -> dict[str, Any]:
        metadata = item.get("metadata", {}) or {}
        return {
            "chunk_id": item["chunk_id"],
            "document_id": metadata.get("document_id"),
            "filename": metadata.get("filename"),
            "page_number": metadata.get("page_number"),
            "page_count": metadata.get("page_count"),
            "source": metadata.get("source"),
            "text_preview": metadata.get("text_preview") or RAGService._preview(str(item.get("text", ""))),
            "rerank_score": item.get("rerank_score"),
        }

    @staticmethod
    def _format_markdown_answer(raw_answer: str, citations: list[dict[str, Any]]) -> str:
        answer = raw_answer.strip() or "I found relevant context, but no answer text was generated."
        if "## Sources" in answer or "Sources:" in answer:
            return answer

        unique_sources: list[str] = []
        seen = set()
        for citation in citations:
            filename = citation.get("filename") or citation.get("source") or "uploaded document"
            page = citation.get("page_number")
            label = f"{filename}, page {page}" if page not in (None, "", 0) else str(filename)
            if label in seen:
                continue
            seen.add(label)
            unique_sources.append(label)
            if len(unique_sources) == 4:
                break

        if not unique_sources:
            return answer

        source_lines = "\n".join(f"{index}. {label}" for index, label in enumerate(unique_sources, start=1))
        return f"{answer}\n\n## Sources\n{source_lines}"

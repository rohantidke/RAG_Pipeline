from __future__ import annotations

import hashlib
import json
import math
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd
import torch
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer, util


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)?\d{3}[\s.-]?\d{4}\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class RAGConfig:
    embedding_model_name: str = "sentence-transformers/all-mpnet-base-v2"
    reranker_model_name: str | None = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    model_local_files_only: bool = False
    device: str | None = None
    default_top_k: int = 5
    candidate_pool_multiplier: int = 5
    max_context_chars: int = 5000
    min_dense_score: float = 0.15
    abstain_threshold: float = 0.32
    rrf_k: int = 60
    pii_masking_enabled: bool = True
    source_allowlist: list[str] | None = None
    source_denylist: list[str] | None = None
    query_rewrite_enabled: bool = True


@dataclass
class ChunkRecord:
    chunk_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: np.ndarray | None = None


class AdvancedRAGEngine:
    def __init__(self, config: RAGConfig | None = None) -> None:
        self.config = config or RAGConfig()
        self.device = self.config.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.embedding_model: SentenceTransformer | None = None
        self.reranker: CrossEncoder | None = None
        self._embedding_model_load_failed = False
        self._reranker_load_failed = False

        self.chunks: list[ChunkRecord] = []
        self.embeddings: torch.Tensor | None = None
        self._bm25: BM25Okapi | None = None
        self._bm25_corpus_tokens: list[list[str]] = []

        # In-memory caches for fast iteration.
        self._rewrite_cache: dict[str, str] = {}
        self._retrieve_cache: dict[str, dict[str, Any]] = {}
        self._answer_cache: dict[str, dict[str, Any]] = {}

    def _get_embedding_model(self) -> SentenceTransformer:
        if self.embedding_model is not None:
            return self.embedding_model
        if self._embedding_model_load_failed:
            raise RuntimeError("Embedding model failed to load earlier in this process.")

        try:
            self.embedding_model = SentenceTransformer(
                self.config.embedding_model_name,
                device=self.device,
                local_files_only=self.config.model_local_files_only,
            )
        except Exception as exc:
            self._embedding_model_load_failed = True
            raise RuntimeError(
                "Could not load the embedding model. Make sure the model is available locally "
                "or network access to Hugging Face is configured."
            ) from exc

        return self.embedding_model

    @staticmethod
    def _tokenize_for_bm25(text: str) -> list[str]:
        return _WORD_RE.findall(text.lower())

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) else default
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _hash_dict(data: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    @staticmethod
    def _mask_pii(text: str) -> str:
        masked = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
        return _PHONE_RE.sub("[REDACTED_PHONE]", masked)

    @staticmethod
    def _parse_embedding_value(value: Any) -> np.ndarray:
        if isinstance(value, np.ndarray):
            return value.astype(np.float32)
        if isinstance(value, list):
            return np.asarray(value, dtype=np.float32)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                inner = stripped[1:-1].replace("\n", " ")
                parsed = np.fromstring(inner.replace(",", " "), sep=" ")
                if parsed.size > 0 and np.all(np.isfinite(parsed)):
                    return parsed.astype(np.float32)
        raise ValueError("Unsupported embedding format")

    @staticmethod
    def _clean_metadata_value(value: Any, default: Any = None) -> Any:
        if value is None:
            return default
        try:
            if pd.isna(value):
                return default
        except (TypeError, ValueError):
            pass
        return value

    @staticmethod
    def _normalize_embedding_matrix(vectors: list[np.ndarray]) -> np.ndarray:
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.ndim != 2:
            raise ValueError("Embeddings must form a 2D matrix.")

        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        if np.any(norms == 0):
            raise ValueError("Embedding matrix contains a zero vector.")

        return matrix / norms

    def rewrite_query(self, query: str) -> str:
        if not self.config.query_rewrite_enabled:
            return query
        if query in self._rewrite_cache:
            return self._rewrite_cache[query]

        rewrites = {
            r"\bllm\b": "large language model",
            r"\brag\b": "retrieval augmented generation",
            r"\bembeddings?\b": "text embeddings semantic representation",
            r"\bctx\b": "context",
        }

        rewritten = query.strip()
        for pattern, replacement in rewrites.items():
            rewritten = re.sub(pattern, replacement, rewritten, flags=re.IGNORECASE)

        # Keep both user phrasing and expanded phrasing to preserve intent.
        if rewritten.lower() != query.strip().lower():
            rewritten = f"{query.strip()} {rewritten}"

        self._rewrite_cache[query] = rewritten
        return rewritten

    def adaptive_top_k(self, query: str) -> int:
        q = query.strip()
        if not q:
            return self.config.default_top_k

        token_count = len(q.split())
        base = self.config.default_top_k

        if token_count <= 3:
            return min(base + 1, 6)
        if token_count >= 14:
            return min(base + 3, 10)
        if any(term in q.lower() for term in ["compare", "difference", "steps", "why", "how"]):
            return min(base + 2, 9)
        return base

    def build_chunks_from_texts(
        self,
        docs: Iterable[dict[str, Any]],
        max_tokens: int = 300,
        overlap_sentences: int = 1,
        min_tokens: int = 25,
    ) -> list[ChunkRecord]:
        built_chunks: list[ChunkRecord] = []

        def count_tokens(text: str) -> int:
            token_ids = self._get_embedding_model().tokenizer(text, add_special_tokens=True, truncation=False)[
                "input_ids"
            ]
            return len(token_ids)

        def split_overlong_sentence(sentence: str) -> list[str]:
            if count_tokens(sentence) <= max_tokens:
                return [sentence]

            words = sentence.split()
            if not words:
                return [sentence]

            segments: list[str] = []
            current_words: list[str] = []

            for word in words:
                candidate_words = current_words + [word]
                candidate_text = " ".join(candidate_words)
                if current_words and count_tokens(candidate_text) > max_tokens:
                    segments.append(" ".join(current_words))
                    current_words = [word]
                    continue

                current_words = candidate_words

            if current_words:
                segments.append(" ".join(current_words))

            return segments or [sentence]

        for doc_idx, doc in enumerate(docs):
            text = str(doc.get("text", "")).strip()
            if not text:
                continue

            sentences = [segment for s in _SENTENCE_SPLIT_RE.split(text) if s.strip() for segment in split_overlong_sentence(s.strip())]
            if not sentences:
                continue

            current: list[str] = []
            current_tokens = 0

            def flush_chunk() -> None:
                if not current:
                    return
                merged = " ".join(current).strip()
                token_len = count_tokens(merged)
                if token_len < min_tokens:
                    return
                chunk_id = f"doc{doc_idx:04d}-chunk{len(built_chunks):05d}"
                metadata = {k: v for k, v in doc.items() if k != "text"}
                metadata["token_count"] = token_len
                built_chunks.append(ChunkRecord(chunk_id=chunk_id, text=merged, metadata=metadata))

            for sentence in sentences:
                sentence_tokens = count_tokens(sentence)
                if current and current_tokens + sentence_tokens > max_tokens:
                    flush_chunk()
                    current = current[-overlap_sentences:] if overlap_sentences > 0 else []
                    current_tokens = sum(count_tokens(s) for s in current)

                current.append(sentence)
                current_tokens += sentence_tokens

            flush_chunk()

        return built_chunks

    def build_index_from_chunks(self, chunks: list[ChunkRecord], batch_size: int = 32) -> None:
        if not chunks:
            raise ValueError("Cannot build index with empty chunks.")

        texts = [chunk.text for chunk in chunks]
        embeddings = self._get_embedding_model().encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            show_progress_bar=True,
            normalize_embeddings=True,
        )

        embedding_matrix = self._normalize_embedding_matrix([np.asarray(emb, dtype=np.float32) for emb in embeddings])
        for idx, emb in enumerate(embedding_matrix):
            chunks[idx].embedding = emb

        self.chunks = chunks
        self.embeddings = torch.tensor(embedding_matrix, dtype=torch.float32, device="cpu")
        self._bm25_corpus_tokens = [self._tokenize_for_bm25(text) for text in texts]
        self._bm25 = BM25Okapi(self._bm25_corpus_tokens)

    def load_index_from_csv(self, csv_path: str | Path) -> None:
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Embedding index CSV not found: {path}")

        df = pd.read_csv(path)
        if df.empty:
            raise ValueError("Embedding index CSV is empty.")

        required_cols = {"sentence_chunk", "embedding"}
        if not required_cols.issubset(df.columns):
            raise ValueError(f"CSV must contain columns: {sorted(required_cols)}")

        chunks: list[ChunkRecord] = []
        vectors: list[np.ndarray] = []

        for idx, row in df.iterrows():
            try:
                emb = self._parse_embedding_value(row["embedding"])
            except ValueError as exc:
                raise ValueError(f"Failed to parse embedding at CSV row {idx}.") from exc

            text = str(row["sentence_chunk"]).strip()
            if not text:
                continue

            metadata = {
                "page_number": self._clean_metadata_value(row.get("page_number")),
                "chunk_char_count": self._clean_metadata_value(row.get("chunk_char_count")),
                "chunk_word_count": self._clean_metadata_value(row.get("chunk_word_count")),
                "chunk_token_count": self._clean_metadata_value(row.get("chunk_token_count")),
                "source": self._clean_metadata_value(row.get("source"), default="book"),
            }
            chunk_id = str(row.get("chunk_id", f"chunk-{idx:06d}"))
            chunks.append(ChunkRecord(chunk_id=chunk_id, text=text, metadata=metadata, embedding=emb))
            vectors.append(emb)

        if not chunks:
            raise ValueError("Embedding index CSV did not contain any usable chunks.")

        embedding_matrix = self._normalize_embedding_matrix(vectors)
        for chunk, emb in zip(chunks, embedding_matrix):
            chunk.embedding = emb

        self.chunks = chunks
        self.embeddings = torch.tensor(embedding_matrix, dtype=torch.float32, device="cpu")
        self._bm25_corpus_tokens = [self._tokenize_for_bm25(c.text) for c in chunks]
        self._bm25 = BM25Okapi(self._bm25_corpus_tokens)

    def _passes_filters(self, chunk: ChunkRecord, filters: dict[str, Any] | None) -> bool:
        if filters is None:
            filters = {}

        source = str(chunk.metadata.get("source", ""))

        if self.config.source_allowlist and source and source not in self.config.source_allowlist:
            return False
        if self.config.source_denylist and source and source in self.config.source_denylist:
            return False

        filter_source = filters.get("source")
        if filter_source and source != filter_source:
            return False

        min_page = filters.get("min_page")
        max_page = filters.get("max_page")
        page = chunk.metadata.get("page_number")
        if page is not None:
            page_num = self._safe_float(page, default=0.0)
            if min_page is not None and page_num < float(min_page):
                return False
            if max_page is not None and page_num > float(max_page):
                return False

        return True

    def _dense_search(self, query: str, pool_size: int) -> list[tuple[int, float]]:
        if self.embeddings is None:
            raise RuntimeError("Embeddings are not initialized.")

        query_emb = self._get_embedding_model().encode(query, convert_to_tensor=True, normalize_embeddings=True)
        query_emb = torch.as_tensor(query_emb, dtype=torch.float32).cpu()
        if query_emb.ndim == 1:
            query_emb = query_emb.unsqueeze(0)

        scores = util.dot_score(query_emb, self.embeddings)[0]
        top_k = min(pool_size, scores.shape[0])
        top_scores, top_indices = torch.topk(scores, k=top_k)

        return [(int(i), float(s)) for i, s in zip(top_indices.tolist(), top_scores.tolist())]

    def _bm25_search(self, query: str, pool_size: int) -> list[tuple[int, float]]:
        if self._bm25 is None:
            raise RuntimeError("BM25 index is not initialized.")

        tokens = self._tokenize_for_bm25(query)
        scores = self._bm25.get_scores(tokens)
        top_indices = np.argsort(scores)[::-1][:pool_size]
        return [(int(i), float(scores[i])) for i in top_indices]

    def _rrf_fusion(
        self,
        dense_ranked: list[tuple[int, float]],
        bm25_ranked: list[tuple[int, float]],
    ) -> dict[int, dict[str, float]]:
        fused: dict[int, dict[str, float]] = {}

        for rank, (idx, score) in enumerate(dense_ranked, start=1):
            state = fused.setdefault(idx, {"rrf": 0.0, "dense": 0.0, "bm25": 0.0})
            state["dense"] = score
            state["rrf"] += 1.0 / (self.config.rrf_k + rank)

        for rank, (idx, score) in enumerate(bm25_ranked, start=1):
            state = fused.setdefault(idx, {"rrf": 0.0, "dense": 0.0, "bm25": 0.0})
            state["bm25"] = score
            state["rrf"] += 1.0 / (self.config.rrf_k + rank)

        return fused

    def _get_reranker(self) -> CrossEncoder | None:
        if not self.config.reranker_model_name or self._reranker_load_failed:
            return None
        if self.reranker is not None:
            return self.reranker

        try:
            self.reranker = CrossEncoder(
                self.config.reranker_model_name,
                device=self.device,
                local_files_only=self.config.model_local_files_only,
            )
        except Exception as exc:  # pragma: no cover - model availability depends on local cache/network.
            self._reranker_load_failed = True
            warnings.warn(
                f"Reranker model could not be loaded; falling back to fused dense/BM25 ranking. Reason: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            return None

        return self.reranker

    def _rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not candidates:
            return candidates

        reranker = self._get_reranker()
        if reranker is None:
            for candidate in candidates:
                candidate["rerank_score"] = candidate["fusion_score"]
            candidates.sort(key=lambda x: x["fusion_score"], reverse=True)
            return candidates

        pairs = [[query, item["text"]] for item in candidates]
        rerank_scores = reranker.predict(pairs)

        for i, score in enumerate(rerank_scores):
            candidates[i]["rerank_score"] = float(score)

        candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
        return candidates

    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filters: dict[str, Any] | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        if not self.chunks:
            raise RuntimeError("Index is empty. Call load_index_from_csv() or build_index_from_chunks() first.")

        rewritten_query = self.rewrite_query(query)
        chosen_top_k = top_k or self.adaptive_top_k(query)
        if chosen_top_k <= 0:
            raise ValueError("top_k must be greater than zero.")

        pool_size = min(len(self.chunks), max(chosen_top_k * self.config.candidate_pool_multiplier, 20))

        cache_key = self._hash_dict(
            {"q": rewritten_query, "k": chosen_top_k, "filters": filters, "pool_size": pool_size}
        )
        if use_cache and cache_key in self._retrieve_cache:
            return self._retrieve_cache[cache_key]

        try:
            dense_ranked = self._dense_search(rewritten_query, pool_size=pool_size)
        except RuntimeError as exc:
            warnings.warn(
                f"Dense search is unavailable; falling back to BM25-only retrieval. Reason: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
            dense_ranked = []
        bm25_ranked = self._bm25_search(rewritten_query, pool_size=pool_size)
        fused = self._rrf_fusion(dense_ranked, bm25_ranked)

        candidates: list[dict[str, Any]] = []
        for idx, fused_scores in fused.items():
            chunk = self.chunks[idx]
            if not self._passes_filters(chunk, filters):
                continue
            if fused_scores["dense"] < self.config.min_dense_score and fused_scores["bm25"] <= 0:
                continue

            text = self._mask_pii(chunk.text) if self.config.pii_masking_enabled else chunk.text
            candidates.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "index": idx,
                    "text": text,
                    "metadata": chunk.metadata,
                    "dense_score": fused_scores["dense"],
                    "bm25_score": fused_scores["bm25"],
                    "fusion_score": fused_scores["rrf"],
                }
            )

        candidates.sort(key=lambda x: x["fusion_score"], reverse=True)
        candidates = candidates[: max(chosen_top_k * 2, chosen_top_k)]
        reranked = self._rerank(rewritten_query, candidates)
        selected = reranked[:chosen_top_k]

        confidence = 0.0
        if selected:
            clipped = [1.0 / (1.0 + math.exp(-item.get("rerank_score", 0.0))) for item in selected]
            confidence = float(np.mean(clipped))

        result = {
            "query": query,
            "rewritten_query": rewritten_query,
            "top_k": chosen_top_k,
            "confidence": confidence,
            "results": selected,
        }
        if use_cache:
            self._retrieve_cache[cache_key] = result
        return result

    def build_cited_context(self, retrieval_result: dict[str, Any], max_chars: int | None = None) -> str:
        max_len = max_chars or self.config.max_context_chars
        parts: list[str] = []
        total = 0

        for item in retrieval_result.get("results", []):
            page = item.get("metadata", {}).get("page_number", "?")
            snippet = f"[{item['chunk_id']} | page={page}] {item['text']}"
            if total + len(snippet) > max_len:
                break
            parts.append(snippet)
            total += len(snippet)

        return "\n\n".join(parts)

    def answer(
        self,
        query: str,
        llm_callable: Callable[[str], str],
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
        use_cache: bool = True,
    ) -> dict[str, Any]:
        cache_key = self._hash_dict({"q": query, "k": top_k, "filters": filters})
        if use_cache and cache_key in self._answer_cache:
            return self._answer_cache[cache_key]

        retrieval = self.retrieve(query=query, top_k=top_k, filters=filters, use_cache=use_cache)
        confidence = retrieval["confidence"]

        if not retrieval["results"] or confidence < self.config.abstain_threshold:
            abstain = {
                "query": query,
                "rewritten_query": retrieval["rewritten_query"],
                "answer": "I do not have enough grounded evidence in the retrieved context to answer reliably.",
                "abstained": True,
                "confidence": confidence,
                "citations": [],
                "retrieval": retrieval,
            }
            if use_cache:
                self._answer_cache[cache_key] = abstain
            return abstain

        context = self.build_cited_context(retrieval)
        prompt = (
            "You are a grounded assistant. Use only the cited context below. "
            "If the answer is not present, say so clearly.\n\n"
            f"Question: {query}\n\n"
            "CITED CONTEXT:\n"
            f"{context}\n\n"
            "Return:\n"
            "1) Direct answer\n"
            "2) Evidence bullets with chunk IDs\n"
            "3) Unknowns\n"
        )

        raw_answer = llm_callable(prompt)
        citations = [
            {
                "chunk_id": item["chunk_id"],
                "page_number": item.get("metadata", {}).get("page_number"),
                "source": item.get("metadata", {}).get("source"),
                "rerank_score": item.get("rerank_score"),
            }
            for item in retrieval["results"]
        ]

        response = {
            "query": query,
            "rewritten_query": retrieval["rewritten_query"],
            "answer": raw_answer,
            "abstained": False,
            "confidence": confidence,
            "citations": citations,
            "retrieval": retrieval,
        }
        if use_cache:
            self._answer_cache[cache_key] = response
        return response


def build_engine_from_embeddings_csv(
    csv_path: str | Path,
    config: RAGConfig | None = None,
) -> AdvancedRAGEngine:
    engine = AdvancedRAGEngine(config=config)
    engine.load_index_from_csv(csv_path)
    return engine

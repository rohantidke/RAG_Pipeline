from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from advanced_rag import AdvancedRAGEngine


@dataclass(frozen=True)
class VectorSearchResult:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    score: float
    distance: float | None = None


class ChromaVectorStore:
    def __init__(self, persist_dir: str | Path, collection_name: str) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError(
                "ChromaDB is not installed. Install dependencies with `pip install -r requirements.txt`."
            ) from exc

        self.persist_dir = Path(persist_dir)
        self.collection_name = collection_name
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def count(self) -> int:
        return int(self._collection.count())

    @property
    def embedding_dim(self) -> int | None:
        if self.count == 0:
            return None
        sample = self._collection.get(limit=1, include=["embeddings"])
        embeddings = sample.get("embeddings")
        if embeddings is None or len(embeddings) == 0:
            return None
        return int(len(embeddings[0]))

    def reset(self) -> None:
        try:
            self._client.delete_collection(self.collection_name)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def import_embeddings_csv(self, csv_path: str | Path, reset: bool = False, batch_size: int = 500) -> int:
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"Embedding index CSV not found: {path}")
        if reset:
            self.reset()
        if self.count > 0 and not reset:
            return self.count

        df = pd.read_csv(path)
        required_cols = {"sentence_chunk", "embedding"}
        if not required_cols.issubset(df.columns):
            raise ValueError(f"CSV must contain columns: {sorted(required_cols)}")

        ids: list[str] = []
        documents: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict[str, Any]] = []

        for idx, row in df.iterrows():
            text = str(row["sentence_chunk"]).strip()
            if not text:
                continue

            vector = AdvancedRAGEngine._parse_embedding_value(row["embedding"])
            metadata = {
                "page_number": self._clean_metadata_value(row.get("page_number")),
                "chunk_char_count": self._clean_metadata_value(row.get("chunk_char_count")),
                "chunk_word_count": self._clean_metadata_value(row.get("chunk_word_count")),
                "chunk_token_count": self._clean_metadata_value(row.get("chunk_token_count")),
                "source": self._clean_metadata_value(row.get("source"), default="book"),
            }
            metadata = {key: value for key, value in metadata.items() if value is not None}

            ids.append(str(row.get("chunk_id", f"chunk-{idx:06d}")))
            documents.append(text)
            embeddings.append(np.asarray(vector, dtype=np.float32).tolist())
            metadatas.append(metadata)

            if len(ids) >= batch_size:
                self._upsert_batch(ids, documents, embeddings, metadatas)
                ids, documents, embeddings, metadatas = [], [], [], []

        if ids:
            self._upsert_batch(ids, documents, embeddings, metadatas)

        return self.count

    def upsert_texts(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        batch_size: int = 500,
    ) -> int:
        if not (len(ids) == len(documents) == len(embeddings) == len(metadatas)):
            raise ValueError("ids, documents, embeddings, and metadatas must have the same length.")

        for start in range(0, len(ids), batch_size):
            end = start + batch_size
            self._upsert_batch(
                ids[start:end],
                documents[start:end],
                embeddings[start:end],
                metadatas[start:end],
            )
        return len(ids)

    def delete_document(self, document_id: str) -> None:
        try:
            self._collection.delete(where={"document_id": document_id})
        except Exception:
            pass

    def query(
        self,
        query_embedding: np.ndarray,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        where = self._build_where(filters)
        query_vector = np.asarray(query_embedding, dtype=np.float32).tolist()
        result = self._collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        search_results: list[VectorSearchResult] = []
        for chunk_id, text, metadata, distance in zip(ids, documents, metadatas, distances):
            score = max(0.0, 1.0 - float(distance)) if distance is not None else 0.0
            search_results.append(
                VectorSearchResult(
                    chunk_id=str(chunk_id),
                    text=str(text),
                    metadata=dict(metadata or {}),
                    score=score,
                    distance=float(distance) if distance is not None else None,
                )
            )
        return search_results

    def _upsert_batch(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        self._collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=[self._clean_upsert_metadata(metadata) for metadata in metadatas],
        )

    @staticmethod
    def _clean_upsert_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
        cleaned: dict[str, str | int | float | bool] = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, np.generic):
                value = value.item()
            if isinstance(value, (bool, int, float, str)):
                cleaned[key] = value
            else:
                cleaned[key] = str(value)
        return cleaned

    @staticmethod
    def _clean_metadata_value(value: Any, default: Any = None) -> Any:
        if value is None:
            return default
        try:
            if pd.isna(value):
                return default
        except (TypeError, ValueError):
            pass
        if isinstance(value, np.generic):
            return value.item()
        return value

    @staticmethod
    def _build_where(filters: dict[str, Any] | None) -> dict[str, Any] | None:
        if not filters:
            return None

        clauses: list[dict[str, Any]] = []
        document_id = filters.get("document_id")
        if document_id:
            clauses.append({"document_id": str(document_id)})

        user_id = filters.get("user_id")
        if user_id:
            clauses.append({"user_id": str(user_id)})

        content_hash = filters.get("content_hash")
        if content_hash:
            clauses.append({"content_hash": str(content_hash)})

        source = filters.get("source")
        if source:
            clauses.append({"source": str(source)})

        min_page = filters.get("min_page")
        if min_page is not None:
            clauses.append({"page_number": {"$gte": float(min_page)}})

        max_page = filters.get("max_page")
        if max_page is not None:
            clauses.append({"page_number": {"$lte": float(max_page)}})

        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

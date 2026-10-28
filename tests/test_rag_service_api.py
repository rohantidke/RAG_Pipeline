from fastapi.testclient import TestClient

from rag_service.main import app


def test_health_endpoint_reports_service_status():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "index" in payload


def test_retrieve_requires_loaded_index_when_not_loaded(monkeypatch):
    from rag_service import main

    monkeypatch.setattr(main.rag_service, "_engine", None)

    client = TestClient(app)
    response = client.post("/retrieve", json={"query": "What is RAG?", "top_k": 3})

    assert response.status_code == 409
    assert "RAG index is not loaded" in response.json()["detail"]


def test_document_endpoints_delegate_to_service(monkeypatch):
    from rag_service import main

    record = {
        "document_id": "doc-1",
        "filename": "notes.txt",
        "content_type": "text/plain",
        "size_bytes": 13,
        "source": "notes",
        "status": "indexed",
        "chunk_count": 1,
        "created_at": "2026-05-21T00:00:00+00:00",
    }

    monkeypatch.setattr(main.rag_service, "list_documents", lambda user_id=None: {"documents": [record]})
    monkeypatch.setattr(
        main.rag_service,
        "get_document",
        lambda document_id, user_id=None: {**record, "document_id": document_id},
    )
    monkeypatch.setattr(
        main.rag_service,
        "delete_document",
        lambda document_id, user_id=None: {**record, "document_id": document_id},
    )

    def upload_document(filename, content, content_type=None, source=None, user_id=None):
        return {
            **record,
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(content),
            "source": source,
            "message": "Document uploaded and indexed.",
        }

    monkeypatch.setattr(main.rag_service, "upload_document", upload_document)

    client = TestClient(app)

    assert client.get("/documents").json()["documents"][0]["document_id"] == "doc-1"
    assert client.get("/documents/doc-2").json()["document_id"] == "doc-2"

    upload_response = client.post(
        "/documents/upload",
        files={"file": ("notes.txt", b"hello document", "text/plain")},
        data={"source": "notes"},
    )
    assert upload_response.status_code == 200
    assert upload_response.json()["filename"] == "notes.txt"
    assert upload_response.json()["size_bytes"] == 14

    delete_response = client.delete("/documents/doc-3")
    assert delete_response.status_code == 200
    assert delete_response.json()["document_id"] == "doc-3"


def test_upload_records_metadata_and_reuses_duplicate(tmp_path, monkeypatch):
    import numpy as np
    from dataclasses import replace
    from types import SimpleNamespace

    from rag_service.config import load_settings
    from rag_service.service import RAGService

    settings = replace(
        load_settings(),
        documents_dir=tmp_path / "documents",
        documents_registry_path=tmp_path / "documents" / "registry.json",
        vector_backend="chroma",
    )
    service = RAGService(settings)

    class FakeEmbeddingModel:
        def encode(self, texts, **kwargs):
            return np.asarray([[1.0, 0.0] for _ in texts], dtype=np.float32)

    class FakeEngine:
        def _get_embedding_model(self):
            return FakeEmbeddingModel()

        def build_chunks_from_texts(self, docs, **kwargs):
            return [
                SimpleNamespace(
                    chunk_id="",
                    text=doc["text"],
                    metadata={key: value for key, value in doc.items() if key != "text"},
                    embedding=None,
                )
                for doc in docs
            ]

    class FakeVectorStore:
        def __init__(self):
            self.upserts = []

        def upsert_texts(self, ids, documents, embeddings, metadatas):
            self.upserts.append((ids, documents, embeddings, metadatas))

        def delete_document(self, document_id):
            pass

    vector_store = FakeVectorStore()
    monkeypatch.setattr(service, "_ensure_engine", lambda: FakeEngine())
    monkeypatch.setattr(service, "_ensure_vector_store", lambda: vector_store)

    content = b"Retrieval augmented generation grounds answers in retrieved context."
    queued = service.upload_document("rag notes.txt", content, "text/plain", "notes")
    first = service.index_document(queued["document_id"])
    duplicate = service.upload_document("rag notes.txt", content, "text/plain", "notes")

    assert first["status"] == "indexed"
    assert first["page_count"] == 1
    assert first["chunk_count"] == 1
    assert first["content_hash"]
    assert first["preview"].startswith("Retrieval augmented generation")
    assert duplicate["document_id"] == first["document_id"]
    assert duplicate["duplicate_of"] == first["document_id"]
    assert len(vector_store.upserts) == 1
    assert vector_store.upserts[0][3][0]["filename"] == "rag_notes.txt"
    assert vector_store.upserts[0][3][0]["text_preview"]


def test_upload_failed_document_is_kept_with_error_reason(tmp_path):
    from dataclasses import replace

    from rag_service.config import load_settings
    from rag_service.service import RAGService

    settings = replace(
        load_settings(),
        documents_dir=tmp_path / "documents",
        documents_registry_path=tmp_path / "documents" / "registry.json",
    )
    service = RAGService(settings)

    queued = service.upload_document("scan.txt", b"   ", "text/plain", "scan")
    response = service.index_document(queued["document_id"])

    assert response["status"] == "failed"
    assert "No readable text" in response["error_message"]
    assert service.list_documents()["documents"][0]["status"] == "failed"

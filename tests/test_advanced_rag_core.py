import pytest
from advanced_rag import AdvancedRAGEngine, ChunkRecord, RAGConfig


class FakeEmbeddingModel:
    @staticmethod
    def tokenizer(text, add_special_tokens=True, truncation=False):
        return {"input_ids": text.split()}


def test_build_chunks_uses_sentence_overlap_and_preserves_metadata():
    engine = AdvancedRAGEngine(RAGConfig(reranker_model_name=None))
    engine.embedding_model = FakeEmbeddingModel()

    chunks = engine.build_chunks_from_texts(
        [
            {
                "text": "Alpha beta. Gamma delta. Epsilon zeta.",
                "source": "unit-test",
                "page_number": 7,
            }
        ],
        max_tokens=4,
        overlap_sentences=1,
        min_tokens=1,
    )

    assert len(chunks) == 2
    assert chunks[0].text == "Alpha beta. Gamma delta."
    assert chunks[1].text == "Gamma delta. Epsilon zeta."
    assert chunks[0].metadata["source"] == "unit-test"
    assert chunks[0].metadata["page_number"] == 7
    assert chunks[0].metadata["token_count"] == 4


def test_build_chunks_splits_overlong_sentences_before_embedding():
    engine = AdvancedRAGEngine(RAGConfig(reranker_model_name=None))
    engine.embedding_model = FakeEmbeddingModel()

    long_sentence = " ".join(f"word{i}" for i in range(12))

    chunks = engine.build_chunks_from_texts(
        [
            {
                "text": long_sentence,
                "source": "unit-test",
                "page_number": 3,
            }
        ],
        max_tokens=5,
        overlap_sentences=0,
        min_tokens=1,
    )

    assert len(chunks) >= 2
    assert all(chunk.metadata["token_count"] <= 5 for chunk in chunks)
    assert "word0" in chunks[0].text


def test_retrieve_falls_back_to_bm25_and_masks_pii(monkeypatch):
    engine = AdvancedRAGEngine(
        RAGConfig(
            reranker_model_name=None,
            min_dense_score=0.15,
            pii_masking_enabled=True,
        )
    )
    engine.chunks = [
        ChunkRecord(
            chunk_id="support",
            text="Retrieval grounded context helps RAG reduce hallucination. Contact owner@example.com.",
            metadata={"source": "book", "page_number": 1},
        ),
        ChunkRecord(
            chunk_id="other",
            text="Warranty purchase policy and shipping terms.",
            metadata={"source": "policy", "page_number": 2},
        ),
    ]
    monkeypatch.setattr(engine, "_dense_search", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(engine, "_bm25_search", lambda *args, **kwargs: [(0, 1.0), (1, 0.1)])

    with pytest.warns(RuntimeWarning, match="BM25-only retrieval"):
        result = engine.retrieve("How does RAG reduce hallucination?", top_k=1, use_cache=False)

    assert result["top_k"] == 1
    assert result["results"][0]["chunk_id"] == "support"
    assert "owner@example.com" not in result["results"][0]["text"]
    assert "[REDACTED_EMAIL]" in result["results"][0]["text"]
    assert result["confidence"] > 0


def test_retrieve_applies_source_and_page_filters(monkeypatch):
    engine = AdvancedRAGEngine(RAGConfig(reranker_model_name=None, min_dense_score=0.15))
    engine.chunks = [
        ChunkRecord(
            chunk_id="book-page",
            text="Retrieval augmented generation uses context.",
            metadata={"source": "book", "page_number": 5},
        ),
        ChunkRecord(
            chunk_id="notes-page",
            text="Retrieval augmented generation uses context.",
            metadata={"source": "notes", "page_number": 1},
        ),
    ]
    monkeypatch.setattr(engine, "_dense_search", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(engine, "_bm25_search", lambda *args, **kwargs: [(0, 1.0), (1, 1.0)])

    with pytest.warns(RuntimeWarning, match="BM25-only retrieval"):
        result = engine.retrieve(
            "RAG context",
            top_k=2,
            filters={"source": "book", "min_page": 2, "max_page": 10},
            use_cache=False,
        )

    assert [item["chunk_id"] for item in result["results"]] == ["book-page"]


def test_answer_formats_grounded_prompt_and_citations(monkeypatch):
    engine = AdvancedRAGEngine(RAGConfig(reranker_model_name=None, abstain_threshold=0.2))
    captured = {}

    retrieval = {
        "query": "What is RAG?",
        "rewritten_query": "What is retrieval augmented generation?",
        "top_k": 1,
        "confidence": 0.9,
        "results": [
            {
                "chunk_id": "chunk-1",
                "text": "RAG grounds generation in retrieved context.",
                "metadata": {"page_number": 12, "source": "book"},
                "rerank_score": 0.7,
            }
        ],
    }

    monkeypatch.setattr(engine, "retrieve", lambda **kwargs: retrieval)

    def fake_llm(prompt):
        captured["prompt"] = prompt
        return "RAG uses retrieved context to ground answers."

    response = engine.answer("What is RAG?", llm_callable=fake_llm, top_k=1, use_cache=False)

    assert response["abstained"] is False
    assert response["answer"] == "RAG uses retrieved context to ground answers."
    assert response["citations"] == [
        {
            "chunk_id": "chunk-1",
            "page_number": 12,
            "source": "book",
            "rerank_score": 0.7,
        }
    ]
    assert "Use only the cited context" in captured["prompt"]
    assert "[chunk-1 | page=12] RAG grounds generation in retrieved context." in captured["prompt"]


def test_answer_abstains_when_retrieval_confidence_is_low(monkeypatch):
    engine = AdvancedRAGEngine(RAGConfig(reranker_model_name=None, abstain_threshold=0.5))
    retrieval = {
        "query": "Unknown",
        "rewritten_query": "Unknown",
        "top_k": 1,
        "confidence": 0.1,
        "results": [],
    }
    monkeypatch.setattr(engine, "retrieve", lambda **kwargs: retrieval)

    response = engine.answer("Unknown", llm_callable=lambda prompt: pytest.fail("LLM should not be called"))

    assert response["abstained"] is True
    assert response["citations"] == []
    assert "not have enough grounded evidence" in response["answer"]

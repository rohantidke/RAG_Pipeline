from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from advanced_rag import AdvancedRAGEngine


@dataclass(frozen=True)
class GoldenCase:
    id: str
    query: str
    expected_keywords: list[str]
    expected_chunk_ids: list[str]
    expected_answer_contains: list[str]
    must_abstain: bool


def load_golden_set(path: str | Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, list):
        raise ValueError("Golden test set must be a JSON array.")
    return data


def normalize_golden_case(case: dict[str, Any], index: int) -> GoldenCase:
    query = str(case.get("query", "")).strip()
    if not query:
        raise ValueError(f"Golden case at index {index} is missing a query.")

    case_id = str(case.get("id") or f"case-{index:03d}")
    expected_keywords = [str(item).strip() for item in case.get("expected_keywords", []) if str(item).strip()]
    expected_chunk_ids = [str(item).strip() for item in case.get("expected_chunk_ids", []) if str(item).strip()]
    expected_answer_contains = [
        str(item).strip() for item in case.get("expected_answer_contains", []) if str(item).strip()
    ]
    must_abstain = bool(case.get("must_abstain", False))

    return GoldenCase(
        id=case_id,
        query=query,
        expected_keywords=expected_keywords,
        expected_chunk_ids=expected_chunk_ids,
        expected_answer_contains=expected_answer_contains,
        must_abstain=must_abstain,
    )


def normalize_golden_cases(golden_cases: list[dict[str, Any]]) -> list[GoldenCase]:
    return [normalize_golden_case(case, index) for index, case in enumerate(golden_cases)]


def _match_any(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def _keyword_hit_count(text: str, expected_keywords: list[str]) -> int:
    lowered = text.lower()
    return sum(1 for kw in expected_keywords if kw.lower() in lowered)


def _citation_hit_count(citations: list[dict[str, Any]], expected_chunk_ids: list[str]) -> int:
    expected = {str(item) for item in expected_chunk_ids}
    return sum(1 for citation in citations if str(citation.get("chunk_id", "")) in expected)


def evaluate_retrieval(
    engine: AdvancedRAGEngine,
    golden_cases: list[dict[str, Any]],
    k: int = 5,
) -> tuple[pd.DataFrame, dict[str, float]]:
    rows: list[dict[str, Any]] = []
    normalized_cases = normalize_golden_cases(golden_cases)

    for case in normalized_cases:
        expected_chunk_ids = set(case.expected_chunk_ids)
        expected_keywords = case.expected_keywords

        retrieved = engine.retrieve(case.query, top_k=k)
        results = retrieved.get("results", [])

        hit_positions: list[int] = []
        keyword_hit_positions: list[int] = []

        for rank, item in enumerate(results, start=1):
            chunk_text = str(item.get("text", ""))
            chunk_id = str(item.get("chunk_id", ""))

            if expected_chunk_ids and chunk_id in expected_chunk_ids:
                hit_positions.append(rank)
            if expected_keywords:
                if _keyword_hit_count(chunk_text, expected_keywords) > 0:
                    keyword_hit_positions.append(rank)

        recall_at_k = 0.0
        mrr = 0.0

        if expected_chunk_ids:
            recall_at_k = 1.0 if hit_positions else 0.0
            mrr = 1.0 / min(hit_positions) if hit_positions else 0.0
        elif expected_keywords:
            recall_at_k = 1.0 if keyword_hit_positions else 0.0
            mrr = 1.0 / min(keyword_hit_positions) if keyword_hit_positions else 0.0

        rows.append(
            {
                "case_id": case.id,
                "query": case.query,
                "recall_at_k": recall_at_k,
                "mrr": mrr,
                "retrieval_confidence": retrieved.get("confidence", 0.0),
                "retrieved_count": len(results),
                "top_chunk_ids": [str(item.get("chunk_id", "")) for item in results],
            }
        )

    df = pd.DataFrame(rows)
    summary = {
        "mean_recall_at_k": float(df["recall_at_k"].mean()) if not df.empty else 0.0,
        "mean_mrr": float(df["mrr"].mean()) if not df.empty else 0.0,
        "mean_retrieval_confidence": float(df["retrieval_confidence"].mean()) if not df.empty else 0.0,
    }
    return df, summary


def evaluate_answers(
    engine: AdvancedRAGEngine,
    golden_cases: list[dict[str, Any]],
    llm_callable,
    k: int = 5,
) -> tuple[pd.DataFrame, dict[str, float]]:
    rows: list[dict[str, Any]] = []
    normalized_cases = normalize_golden_cases(golden_cases)

    for case in normalized_cases:
        expected_keywords = case.expected_keywords

        response = engine.answer(query=case.query, llm_callable=llm_callable, top_k=k)
        answer = str(response.get("answer", ""))
        abstained = bool(response.get("abstained", False))
        citations = response.get("citations", [])

        keyword_support = _keyword_hit_count(answer, expected_keywords) if expected_keywords else 0
        precision_proxy = 0.0
        if expected_keywords:
            precision_proxy = keyword_support / max(len(expected_keywords), 1)

        citation_hit_count = _citation_hit_count(citations, case.expected_chunk_ids)
        has_expected_text = _match_any(answer, case.expected_answer_contains)
        abstain_expected = case.must_abstain
        abstain_match = bool(abstained == abstain_expected)

        rows.append(
            {
                "case_id": case.id,
                "query": case.query,
                "abstained": abstained,
                "abstain_expected": abstain_expected,
                "abstain_match": abstain_match,
                "confidence": response.get("confidence", 0.0),
                "citation_count": len(citations),
                "citation_hit_count": citation_hit_count,
                "faithfulness_proxy": float(precision_proxy),
                "answer_contains_expected_text": has_expected_text,
            }
        )

    df = pd.DataFrame(rows)
    summary = {
        "abstain_rate": float(df["abstained"].mean()) if not df.empty else 0.0,
        "abstain_match_rate": float(df["abstain_match"].mean()) if not df.empty else 0.0,
        "mean_confidence": float(df["confidence"].mean()) if not df.empty else 0.0,
        "mean_faithfulness_proxy": float(df["faithfulness_proxy"].mean()) if not df.empty else 0.0,
        "mean_citation_count": float(df["citation_count"].mean()) if not df.empty else 0.0,
        "mean_citation_hit_count": float(df["citation_hit_count"].mean()) if not df.empty else 0.0,
        "answer_contains_expected_text_rate": float(df["answer_contains_expected_text"].mean()) if not df.empty else 0.0,
    }
    return df, summary


def build_dashboard(
    retrieval_df: pd.DataFrame,
    answer_df: pd.DataFrame,
    output_dir: str | Path = "reports",
) -> dict[str, str]:
    import matplotlib.pyplot as plt

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    files: dict[str, str] = {}

    if not retrieval_df.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        retrieval_df[["recall_at_k", "mrr"]].mean().plot(kind="bar", ax=ax, color=["#2E86AB", "#F18F01"])
        ax.set_title("Retrieval Metrics")
        ax.set_ylim(0, 1)
        ax.set_ylabel("Score")
        fig.tight_layout()
        path = output / "retrieval_metrics.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        files["retrieval_chart"] = str(path)

    if not answer_df.empty:
        fig, ax = plt.subplots(figsize=(8, 4))
        cols = ["mean_confidence", "mean_faithfulness_proxy", "mean_citation_count"]
        values = [
            float(answer_df["confidence"].mean()),
            float(answer_df["faithfulness_proxy"].mean()),
            float(answer_df["citation_count"].mean()),
        ]
        scaled_citation = min(values[2] / max(answer_df["citation_count"].max(), 1), 1.0)
        y_vals = [values[0], values[1], scaled_citation]
        ax.bar(cols, y_vals, color=["#5C4B8A", "#2A9D8F", "#E76F51"])
        ax.set_ylim(0, 1)
        ax.set_title("Answer Quality Dashboard (normalized)")
        fig.tight_layout()
        path = output / "answer_metrics.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        files["answer_chart"] = str(path)

    retrieval_csv = output / "retrieval_eval.csv"
    answer_csv = output / "answer_eval.csv"
    retrieval_df.to_csv(retrieval_csv, index=False)
    answer_df.to_csv(answer_csv, index=False)
    files["retrieval_csv"] = str(retrieval_csv)
    files["answer_csv"] = str(answer_csv)

    return files


def write_summary_report(
    retrieval_summary: dict[str, float],
    answer_summary: dict[str, float],
    output_dir: str | Path = "reports",
) -> str:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / "evaluation_summary.md"

    lines = [
        "# RAG Evaluation Summary",
        "",
        "## Retrieval",
    ]
    for key, value in retrieval_summary.items():
        lines.append(f"- {key}: {value:.4f}")

    lines.extend(["", "## Answers"])
    for key, value in answer_summary.items():
        lines.append(f"- {key}: {value:.4f}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def run_eval_suite(
    engine: AdvancedRAGEngine,
    golden_cases: list[dict[str, Any]],
    llm_callable,
    k: int = 5,
    output_dir: str | Path = "reports",
) -> dict[str, Any]:
    retrieval_df, retrieval_summary = evaluate_retrieval(engine, golden_cases, k=k)
    answer_df, answer_summary = evaluate_answers(engine, golden_cases, llm_callable=llm_callable, k=k)
    artifacts = build_dashboard(retrieval_df, answer_df, output_dir=output_dir)
    summary_report = write_summary_report(retrieval_summary, answer_summary, output_dir=output_dir)

    return {
        "retrieval_df": retrieval_df,
        "answer_df": answer_df,
        "retrieval_summary": retrieval_summary,
        "answer_summary": answer_summary,
        "artifacts": artifacts,
        "summary_report": summary_report,
    }


def _build_default_llm_callable(model_name: str = "google/flan-t5-small"):
    try:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        import torch

        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

        def _call(prompt: str) -> str:
            inputs = tokenizer(prompt, return_tensors="pt", max_length=1024, truncation=True)
            with torch.no_grad():
                outputs = model.generate(**inputs, max_new_tokens=220, do_sample=False)
            return tokenizer.decode(outputs[0], skip_special_tokens=True)

        return _call
    except Exception:
        from transformers import pipeline

        try:
            generator = pipeline("text2text-generation", model=model_name)
        except Exception:
            generator = pipeline("text-generation", model=model_name)

        def _call(prompt: str) -> str:
            output = generator(prompt, max_new_tokens=220, do_sample=False)
            if isinstance(output, list) and output:
                return output[0].get("generated_text", "")
            return str(output)

        return _call


def main() -> int:
    from advanced_rag import AdvancedRAGEngine

    parser = argparse.ArgumentParser(description="Run golden-set evaluation for the RAG pipeline.")
    parser.add_argument("--index", required=True, help="Path to text_chunks_and_embeddings_df.csv")
    parser.add_argument("--golden", required=True, help="Path to golden_test_set.json")
    parser.add_argument("--output", default="reports", help="Directory for metrics and charts")
    parser.add_argument("--top-k", type=int, default=5, help="Number of chunks to retrieve")
    parser.add_argument(
        "--model",
        default="google/flan-t5-small",
        help="Text-to-text model used for answer evaluation",
    )
    args = parser.parse_args()

    engine = AdvancedRAGEngine()
    engine.load_index_from_csv(args.index)
    golden_cases = load_golden_set(args.golden)
    llm_callable = _build_default_llm_callable(args.model)

    results = run_eval_suite(engine, golden_cases, llm_callable=llm_callable, k=args.top_k, output_dir=args.output)
    print(json.dumps({
        "retrieval_summary": results["retrieval_summary"],
        "answer_summary": results["answer_summary"],
        "summary_report": results["summary_report"],
        "artifacts": results["artifacts"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

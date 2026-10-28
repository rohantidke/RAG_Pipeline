from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Callable

import requests

from .config import ServiceSettings


_CONTEXT_RE = re.compile(r"CITED CONTEXT:\n(?P<context>.*?)(?:\n\nReturn Markdown|\n\nReturn:|\Z)", re.DOTALL)
_SOURCE_RE = re.compile(r"\[(?P<chunk>[^\]|]+)(?:\s*\|\s*page=(?P<page>[^\]]+))?\]")


def _extractive_answer(prompt: str) -> str:
    match = _CONTEXT_RE.search(prompt)
    context = match.group("context").strip() if match else ""
    if not context:
        return "I do not have enough grounded evidence in the retrieved context to answer reliably."

    snippets = []
    for block in context.split("\n\n"):
        cleaned = " ".join(block.split())
        if cleaned:
            cleaned = _SOURCE_RE.sub("", cleaned).strip()
            snippets.append(cleaned)
        if len(snippets) == 3:
            break

    first = snippets[0] if snippets else "The retrieved context contains relevant evidence."
    evidence = "\n".join(f"- {snippet}" for snippet in snippets)
    return (
        f"{first}\n\n"
        "Based on the retrieved document context, the most relevant points are:\n\n"
        f"{evidence}\n\n"
        "This is an extractive answer because no external generation provider is configured. "
        "For more natural generated answers, set `RAG_LLM_PROVIDER=ollama`."
    )


def _ollama_answer(prompt: str, settings: ServiceSettings) -> str:
    response = requests.post(
        f"{settings.ollama_base_url}/api/generate",
        json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
        timeout=settings.request_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    return str(payload.get("response", "")).strip()


def _ollama_answer_stream(prompt: str, settings: ServiceSettings) -> Iterator[str]:
    response = requests.post(
        f"{settings.ollama_base_url}/api/generate",
        json={"model": settings.ollama_model, "prompt": prompt, "stream": True},
        timeout=settings.request_timeout_seconds,
        stream=True,
    )
    response.raise_for_status()
    for line in response.iter_lines():
        if line:
            payload = json.loads(line)
            yield str(payload.get("response", ""))


def _extractive_answer_stream(prompt: str) -> Iterator[str]:
    answer = _extractive_answer(prompt)
    for word in answer.split(" "):
        yield word + " "


def build_llm_callable(settings: ServiceSettings) -> Callable[[str], str]:
    if settings.llm_provider == "ollama":
        return lambda prompt: _ollama_answer(prompt, settings)
    if settings.llm_provider == "extractive":
        return _extractive_answer
    raise ValueError(f"Unsupported RAG_LLM_PROVIDER: {settings.llm_provider}")


def build_llm_stream_callable(settings: ServiceSettings) -> Callable[[str], Iterator[str]]:
    if settings.llm_provider == "ollama":
        return lambda prompt: _ollama_answer_stream(prompt, settings)
    if settings.llm_provider == "extractive":
        return _extractive_answer_stream
    raise ValueError(f"Unsupported RAG_LLM_PROVIDER: {settings.llm_provider}")
from __future__ import annotations

import importlib
from typing import Any
from typing import Protocol

from backend.app.rag.qdrant_client import VectorIndex
from backend.app.rag.retriever import Retriever


class RetrievalAdapter(Protocol):
    def retrieve(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...


class LlamaIndexRetriever:
    """Optional LlamaIndex-backed retrieval adapter.

    For metadata-filtered vector search, this adapter reuses the existing index interface.
    The adapter is enabled only when llama_index runtime is importable.
    """

    def __init__(self, index: VectorIndex, top_k: int = 12) -> None:
        try:
            importlib.import_module("llama_index.core")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("llamaindex runtime is unavailable") from exc
        self.index = index
        self.top_k = top_k

    def retrieve(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.index.search(query=query, top_k=self.top_k, filters=filters)


def build_retriever(
    requested_engine: str,
    index: VectorIndex,
    top_k: int,
    *,
    fail_closed: bool = False,
) -> tuple[RetrievalAdapter, str, str | None]:
    if requested_engine == "llamaindex":
        try:
            return LlamaIndexRetriever(index=index, top_k=top_k), "llamaindex", None
        except Exception as exc:  # noqa: BLE001
            if fail_closed:
                raise RuntimeError("llamaindex runtime is unavailable in fail-closed profile") from exc
            reason = f"llamaindex_unavailable:{type(exc).__name__}"
            return Retriever(index=index, top_k=top_k), "basic", reason
    return Retriever(index=index, top_k=top_k), "basic", None

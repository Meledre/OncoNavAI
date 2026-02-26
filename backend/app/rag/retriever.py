from __future__ import annotations

from typing import Any

from backend.app.rag.qdrant_client import VectorIndex


class Retriever:
    def __init__(self, index: VectorIndex, top_k: int = 12) -> None:
        self.index = index
        self.top_k = top_k

    def retrieve(self, query: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.index.search(query=query, top_k=self.top_k, filters=filters)

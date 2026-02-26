from __future__ import annotations

from typing import Any

from backend.app.llm.provider_router import LLMProviderRouter


def _overlap_score(query: str, text: str) -> float:
    query_tokens = {token for token in query.lower().split() if token}
    text_tokens = {token for token in text.lower().split() if token}
    if not query_tokens:
        return 0.0
    return len(query_tokens.intersection(text_tokens)) / len(query_tokens)


class Reranker:
    def __init__(
        self,
        top_n: int = 6,
        backend: str = "lexical",
        llm_router: LLMProviderRouter | None = None,
        *,
        fail_closed: bool = False,
    ) -> None:
        self.top_n = top_n
        self.backend = backend
        self.llm_router = llm_router
        self.fail_closed = bool(fail_closed)

    @staticmethod
    def _lexical_sort(query: str, retrieved: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            retrieved,
            key=lambda chunk: (chunk.get("score", 0.0) + _overlap_score(query, chunk.get("text", ""))),
            reverse=True,
        )

    @staticmethod
    def _apply_ranking(chunk_ids: list[str], retrieved: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id = {str(item.get("chunk_id")): item for item in retrieved}
        ordered: list[dict[str, Any]] = []
        used: set[str] = set()
        for chunk_id in chunk_ids:
            if chunk_id in by_id and chunk_id not in used:
                ordered.append(by_id[chunk_id])
                used.add(chunk_id)
        for item in retrieved:
            chunk_id = str(item.get("chunk_id"))
            if chunk_id not in used:
                ordered.append(item)
        return ordered

    def _rank_from_payload(self, payload: dict | None, retrieved: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if not isinstance(payload, dict):
            return None

        def _normalize_ranking_list(value: Any) -> list[str]:
            normalized: list[str] = []
            if not isinstance(value, list):
                return normalized
            for item in value:
                if isinstance(item, str):
                    token = item.strip()
                    if token:
                        normalized.append(token)
                    continue
                if isinstance(item, dict):
                    candidate = item.get("chunk_id")
                    if not isinstance(candidate, str):
                        candidate = item.get("id")
                    if isinstance(candidate, str) and candidate.strip():
                        normalized.append(candidate.strip())
            return normalized

        for key in ("ranking", "chunks", "ranked_chunks"):
            ranking = _normalize_ranking_list(payload.get(key))
            if ranking:
                return self._apply_ranking(chunk_ids=ranking, retrieved=retrieved)

        scores = payload.get("scores")
        if isinstance(scores, list):
            parsed_scores: list[tuple[str, float]] = []
            for item in scores:
                if not isinstance(item, dict):
                    continue
                chunk_id = item.get("chunk_id")
                score = item.get("score")
                if isinstance(chunk_id, str) and isinstance(score, (int, float)):
                    parsed_scores.append((chunk_id, float(score)))
            if parsed_scores:
                parsed_scores.sort(key=lambda value: value[1], reverse=True)
                return self._apply_ranking(chunk_ids=[item[0] for item in parsed_scores], retrieved=retrieved)

        return None

    def _llm_rerank(self, query: str, retrieved: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if self.llm_router is None or not retrieved:
            return None

        chunk_attempts: list[tuple[str, list[str]]] = []
        for limit, excerpt_len in ((20, 180), (12, 120)):
            subset = retrieved[:limit]
            chunk_ids: list[str] = []
            for item in subset:
                token = str(item.get("chunk_id") or "").strip()
                if token and token not in chunk_ids:
                    chunk_ids.append(token)
            chunks = "\n".join(
                f"- {item.get('chunk_id')}: {str(item.get('text', '')).replace(chr(10), ' ')[:excerpt_len]}"
                for item in subset
            )
            chunk_attempts.append((chunks, chunk_ids))

        for chunks, chunk_ids in chunk_attempts:
            if not chunk_ids:
                continue
            ranking_schema = {
                "type": "object",
                "properties": {
                    "ranking": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["ranking"],
                "additionalProperties": False,
            }
            prompt = (
                "Rank retrieved chunks by relevance for oncology treatment plan verification. "
                "Use only chunk IDs from the provided list and return strict JSON only: "
                "{\"ranking\": [\"chunk_id\", ...]}.\n"
                f"Query: {query}\n"
                f"Chunks:\n{chunks}"
            )
            payload, _path = self.llm_router.generate_json(
                prompt,
                output_schema=ranking_schema,
                schema_name="chunk_ranking",
            )
            ranked = self._rank_from_payload(payload=payload, retrieved=retrieved)
            if ranked is not None:
                return ranked

        return None

    def rerank(self, query: str, retrieved: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # For 0-2 chunks the retriever ordering is already sufficient; avoid an extra LLM hop.
        if len(retrieved) <= 2:
            return retrieved[: self.top_n]
        if self.backend == "llm":
            llm_ranked = self._llm_rerank(query=query, retrieved=retrieved)
            if llm_ranked is not None:
                return llm_ranked[: self.top_n]
            if self.fail_closed:
                sample_chunk_ids = [
                    str(item.get("chunk_id") or "").strip()
                    for item in retrieved[:3]
                    if str(item.get("chunk_id") or "").strip()
                ]
                raise RuntimeError(
                    "LLM reranker failed in fail-closed mode "
                    f"(retrieved={len(retrieved)}, sample_chunk_ids={sample_chunk_ids})"
                )
        return self._lexical_sort(query=query, retrieved=retrieved)[: self.top_n]

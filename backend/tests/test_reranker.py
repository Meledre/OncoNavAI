from __future__ import annotations

import pytest

from backend.app.rag.reranker import Reranker


class _StubRouter:
    def __init__(self, payload: dict | None, path: str = "primary") -> None:
        self.payload = payload
        self.path = path
        self.calls = 0

    def generate_json(self, prompt: str, **kwargs) -> tuple[dict | None, str]:
        self.calls += 1
        assert "query:" in prompt.lower()
        assert kwargs.get("schema_name") == "chunk_ranking"
        schema = kwargs.get("output_schema")
        assert isinstance(schema, dict)
        assert schema.get("additionalProperties") is False
        scores_items = (
            ((schema.get("properties") or {}).get("scores") or {}).get("items")
            if isinstance(schema.get("properties"), dict)
            else None
        )
        if isinstance(scores_items, dict):
            assert scores_items.get("additionalProperties") is False
        return self.payload, self.path


class _SequenceStubRouter:
    def __init__(self, payloads: list[dict | None], path: str = "primary") -> None:
        self.payloads = payloads
        self.path = path
        self.calls = 0

    def generate_json(self, prompt: str, **kwargs) -> tuple[dict | None, str]:
        self.calls += 1
        assert "query:" in prompt.lower()
        assert kwargs.get("schema_name") == "chunk_ranking"
        schema = kwargs.get("output_schema")
        assert isinstance(schema, dict)
        assert schema.get("additionalProperties") is False
        scores_items = (
            ((schema.get("properties") or {}).get("scores") or {}).get("items")
            if isinstance(schema.get("properties"), dict)
            else None
        )
        if isinstance(scores_items, dict):
            assert scores_items.get("additionalProperties") is False
        if self.calls <= len(self.payloads):
            return self.payloads[self.calls - 1], self.path
        return self.payloads[-1], self.path


def test_reranker_llm_backend_respects_ranking_payload():
    reranker = Reranker(
        top_n=3,
        backend="llm",
        llm_router=_StubRouter({"ranking": ["c-2", "c-1", "c-3"]}),
    )
    retrieved = [
        {"chunk_id": "c-1", "text": "osimertinib mention", "score": 0.4},
        {"chunk_id": "c-2", "text": "diagnostic confirmation", "score": 0.2},
        {"chunk_id": "c-3", "text": "other context", "score": 0.1},
    ]

    ranked = reranker.rerank(query="osimertinib", retrieved=retrieved)
    assert [item["chunk_id"] for item in ranked] == ["c-2", "c-1", "c-3"]


def test_reranker_llm_backend_falls_back_to_lexical_when_ranking_missing():
    reranker = Reranker(
        top_n=3,
        backend="llm",
        llm_router=_StubRouter({"unexpected": "payload"}),
    )
    retrieved = [
        {"chunk_id": "c-1", "text": "querytoken strongly relevant", "score": 0.1},
        {"chunk_id": "c-2", "text": "other content", "score": 0.9},
        {"chunk_id": "c-3", "text": "querytoken moderate", "score": 0.2},
    ]

    ranked = reranker.rerank(query="querytoken", retrieved=retrieved)
    assert [item["chunk_id"] for item in ranked] == ["c-3", "c-1", "c-2"]


def test_reranker_fail_closed_raises_when_llm_ranking_is_missing():
    reranker = Reranker(
        top_n=3,
        backend="llm",
        llm_router=_StubRouter({"unexpected": "payload"}),
        fail_closed=True,
    )
    retrieved = [
        {"chunk_id": "c-1", "text": "querytoken strongly relevant", "score": 0.1},
        {"chunk_id": "c-2", "text": "other content", "score": 0.9},
        {"chunk_id": "c-3", "text": "querytoken moderate", "score": 0.2},
    ]
    with pytest.raises(RuntimeError, match="fail-closed"):
        reranker.rerank(query="querytoken", retrieved=retrieved)


def test_reranker_llm_backend_retries_with_compact_prompt_when_first_payload_invalid():
    router = _SequenceStubRouter(payloads=[None, {"ranking": ["c-2", "c-1", "c-3"]}])
    reranker = Reranker(
        top_n=3,
        backend="llm",
        llm_router=router,
        fail_closed=True,
    )
    retrieved = [
        {"chunk_id": "c-1", "text": "querytoken strongly relevant", "score": 0.1},
        {"chunk_id": "c-2", "text": "other content", "score": 0.9},
        {"chunk_id": "c-3", "text": "querytoken moderate", "score": 0.2},
    ]

    ranked = reranker.rerank(query="querytoken", retrieved=retrieved)
    assert [item["chunk_id"] for item in ranked] == ["c-2", "c-1", "c-3"]
    assert router.calls == 2


def test_reranker_accepts_chunks_alias_payload_shape():
    reranker = Reranker(
        top_n=3,
        backend="llm",
        llm_router=_StubRouter({"chunks": [{"id": "c-2"}, {"chunk_id": "c-1"}, {"chunk_id": "c-3"}]}),
        fail_closed=True,
    )
    retrieved = [
        {"chunk_id": "c-1", "text": "querytoken strongly relevant", "score": 0.1},
        {"chunk_id": "c-2", "text": "other content", "score": 0.9},
        {"chunk_id": "c-3", "text": "querytoken moderate", "score": 0.2},
    ]

    ranked = reranker.rerank(query="querytoken", retrieved=retrieved)
    assert [item["chunk_id"] for item in ranked] == ["c-2", "c-1", "c-3"]


def test_reranker_fail_closed_returns_empty_for_empty_retrieval():
    router = _StubRouter({"ranking": ["c-1"]})
    reranker = Reranker(
        top_n=2,
        backend="llm",
        llm_router=router,
        fail_closed=True,
    )

    ranked = reranker.rerank(query="querytoken", retrieved=[])
    assert ranked == []
    assert router.calls == 0


def test_reranker_fail_closed_skips_llm_for_single_chunk():
    router = _StubRouter({"ranking": []})
    reranker = Reranker(
        top_n=2,
        backend="llm",
        llm_router=router,
        fail_closed=True,
    )
    retrieved = [{"chunk_id": "c-1", "text": "single chunk", "score": 0.7}]

    ranked = reranker.rerank(query="querytoken", retrieved=retrieved)
    assert [item["chunk_id"] for item in ranked] == ["c-1"]
    assert router.calls == 0


def test_reranker_fail_closed_skips_llm_for_two_chunks():
    router = _StubRouter({"ranking": ["c-2", "c-1"]})
    reranker = Reranker(
        top_n=2,
        backend="llm",
        llm_router=router,
        fail_closed=True,
    )
    retrieved = [
        {"chunk_id": "c-1", "text": "chunk one", "score": 0.9},
        {"chunk_id": "c-2", "text": "chunk two", "score": 0.8},
    ]

    ranked = reranker.rerank(query="querytoken", retrieved=retrieved)
    assert [item["chunk_id"] for item in ranked] == ["c-1", "c-2"]
    assert router.calls == 0

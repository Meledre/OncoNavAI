from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from backend.app.rag.engine import LlamaIndexRetriever, build_retriever
from backend.app.rag.qdrant_client import LocalQdrantLikeIndex
from backend.app.storage import SQLiteStore


def _build_local_index(tmp_path: Path) -> LocalQdrantLikeIndex:
    store = SQLiteStore(tmp_path / "oncoai.sqlite3")
    return LocalQdrantLikeIndex(store)


def test_build_retriever_returns_basic_engine_by_default(tmp_path: Path):
    index = _build_local_index(tmp_path)
    retriever, engine_name, fallback_reason = build_retriever(
        requested_engine="basic",
        index=index,
        top_k=5,
    )
    assert engine_name == "basic"
    assert fallback_reason is None
    assert hasattr(retriever, "retrieve")


def test_build_retriever_falls_back_when_llamaindex_is_unavailable(tmp_path: Path):
    index = _build_local_index(tmp_path)
    retriever, engine_name, fallback_reason = build_retriever(
        requested_engine="llamaindex",
        index=index,
        top_k=5,
    )
    assert engine_name == "basic"
    assert fallback_reason is not None
    assert fallback_reason.startswith("llamaindex_unavailable")
    assert hasattr(retriever, "retrieve")


def test_build_retriever_uses_llamaindex_when_runtime_is_available(
    tmp_path: Path,
    monkeypatch: Any,
):
    index = _build_local_index(tmp_path)
    monkeypatch.setitem(sys.modules, "llama_index", types.ModuleType("llama_index"))
    monkeypatch.setitem(sys.modules, "llama_index.core", types.ModuleType("llama_index.core"))

    retriever, engine_name, fallback_reason = build_retriever(
        requested_engine="llamaindex",
        index=index,
        top_k=5,
    )

    assert isinstance(retriever, LlamaIndexRetriever)
    assert engine_name == "llamaindex"
    assert fallback_reason is None


def test_build_retriever_fail_closed_raises_when_llamaindex_is_unavailable(tmp_path: Path):
    index = _build_local_index(tmp_path)
    with pytest.raises(RuntimeError, match="fail-closed"):
        build_retriever(
            requested_engine="llamaindex",
            index=index,
            top_k=5,
            fail_closed=True,
        )

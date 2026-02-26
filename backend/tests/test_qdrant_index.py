from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.app.rag.qdrant_client import LocalQdrantLikeIndex, QdrantRestIndex
from backend.app.storage import SQLiteStore


def _chunk(doc_id: str, doc_version: str) -> dict:
    return {
        "chunk_id": f"{doc_id}_{doc_version}_c0",
        "doc_id": doc_id,
        "doc_version": doc_version,
        "source_set": "mvp_guidelines_ru_2025",
        "cancer_type": "nsclc_egfr",
        "language": "ru",
        "pdf_page_index": 0,
        "page_label": "1",
        "section_title": "Guideline fragment",
        "text": "osimertinib systemic therapy guidance",
        "updated_at": "2026-02-16T00:00:00+00:00",
    }


def test_qdrant_rest_index_search_falls_back_to_local(tmp_path: Path):
    store = SQLiteStore(tmp_path / "oncoai.sqlite3")
    local = LocalQdrantLikeIndex(store)
    local.replace_doc_chunks(doc_id="g1", doc_version="v1", chunks=[_chunk("g1", "v1")])

    index = QdrantRestIndex(
        qdrant_url="http://127.0.0.1:65534",
        collection="oncoai_chunks",
        fallback_index=local,
    )
    results = index.search(query="osimertinib", top_k=5, filters={"cancer_type": "nsclc_egfr"})

    assert results
    assert results[0]["doc_id"] == "g1"


def test_qdrant_rest_index_replace_doc_chunks_keeps_local_synced(tmp_path: Path):
    store = SQLiteStore(tmp_path / "oncoai.sqlite3")
    local = LocalQdrantLikeIndex(store)
    index = QdrantRestIndex(
        qdrant_url="http://127.0.0.1:65534",
        collection="oncoai_chunks",
        fallback_index=local,
    )

    index.replace_doc_chunks(doc_id="g2", doc_version="v2", chunks=[_chunk("g2", "v2")])
    results = local.search(query="osimertinib", top_k=3, filters={"doc_id": "g2", "doc_version": "v2"})

    assert results
    assert results[0]["chunk_id"] == "g2_v2_c0"


def test_qdrant_rest_index_replace_doc_chunks_uses_numeric_point_ids(
    tmp_path: Path, monkeypatch: Any
):
    store = SQLiteStore(tmp_path / "oncoai.sqlite3")
    local = LocalQdrantLikeIndex(store)
    index = QdrantRestIndex(
        qdrant_url="http://127.0.0.1:65534",
        collection="oncoai_chunks",
        fallback_index=local,
    )

    captured_points_payload: dict[str, Any] = {}

    def fake_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if path.endswith("/points?wait=true") and payload:
            captured_points_payload.update(payload)
        if path.endswith("/points/search"):
            return {"result": []}
        return {"result": {"status": "ok"}}

    monkeypatch.setattr(index, "_request", fake_request)
    index.replace_doc_chunks(doc_id="g3", doc_version="v3", chunks=[_chunk("g3", "v3")])

    points = captured_points_payload.get("points") or []
    assert points
    assert isinstance(points[0]["id"], int)


def test_qdrant_rest_index_existing_collection_conflict_is_not_fatal(
    tmp_path: Path, monkeypatch: Any
):
    store = SQLiteStore(tmp_path / "oncoai.sqlite3")
    local = LocalQdrantLikeIndex(store)
    index = QdrantRestIndex(
        qdrant_url="http://127.0.0.1:65534",
        collection="oncoai_chunks",
        fallback_index=local,
    )

    calls: list[tuple[str, str]] = []

    def fake_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        calls.append((method, path))
        if method == "PUT" and path.startswith("/collections/"):
            raise RuntimeError("Qdrant request failed: HTTP Error 409: Conflict")
        if method == "GET" and path.startswith("/collections/"):
            return {
                "result": {
                    "config": {
                        "params": {
                            "vectors": {"size": 64, "distance": "Cosine"},
                        }
                    }
                }
            }
        return {"result": {"status": "ok"}}

    monkeypatch.setattr(index, "_request", fake_request)
    index._ensure_collection(vector_size=64)

    assert index._collection_ready is True
    assert index._vector_size == 64
    assert ("GET", "/collections/oncoai_chunks") in calls


def test_qdrant_rest_index_creates_payload_indexes(tmp_path: Path, monkeypatch: Any):
    store = SQLiteStore(tmp_path / "oncoai.sqlite3")
    local = LocalQdrantLikeIndex(store)
    index = QdrantRestIndex(
        qdrant_url="http://127.0.0.1:65534",
        collection="oncoai_chunks",
        fallback_index=local,
    )

    payload_index_fields: list[str] = []

    def fake_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if method == "PUT" and path == "/collections/oncoai_chunks/index" and payload:
            field_name = payload.get("field_name")
            if isinstance(field_name, str):
                payload_index_fields.append(field_name)
        return {"result": {"status": "ok"}}

    monkeypatch.setattr(index, "_request", fake_request)
    index._ensure_collection(vector_size=64)

    assert set(payload_index_fields) >= {"cancer_type", "language", "source_set", "doc_version", "doc_id"}


def test_qdrant_filter_ignores_unknown_fields(tmp_path: Path):
    store = SQLiteStore(tmp_path / "oncoai.sqlite3")
    local = LocalQdrantLikeIndex(store)
    index = QdrantRestIndex(
        qdrant_url="http://127.0.0.1:65534",
        collection="oncoai_chunks",
        fallback_index=local,
    )

    built = index._build_qdrant_filter(
        {
            "cancer_type": "gastric_cancer",
            "language": "ru",
            "source_mode": "AUTO",
            "unsupported_field": "value",
        }
    )

    assert built == {
        "must": [
            {"key": "cancer_type", "match": {"value": "gastric_cancer"}},
            {"key": "language", "match": {"value": "ru"}},
        ]
    }


def test_qdrant_preflight_reports_vector_size_mismatch(tmp_path: Path, monkeypatch: Any):
    store = SQLiteStore(tmp_path / "oncoai.sqlite3")
    local = LocalQdrantLikeIndex(store)
    index = QdrantRestIndex(
        qdrant_url="http://127.0.0.1:65534",
        collection="oncoai_chunks",
        fallback_index=local,
    )

    def fake_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        assert method == "GET"
        assert path == "/collections/oncoai_chunks"
        return {
            "result": {
                "config": {
                    "params": {
                        "vectors": {"size": 1536, "distance": "Cosine"},
                    }
                }
            }
        }

    monkeypatch.setattr(index, "_request", fake_request)
    snapshot = index.preflight_vector_alignment(expected_vector_size=64)

    assert snapshot["status"] == "vector_size_mismatch"
    assert snapshot["expected_vector_size"] == 64
    assert snapshot["actual_vector_size"] == 1536


def test_qdrant_preflight_reports_collection_unavailable(tmp_path: Path, monkeypatch: Any):
    store = SQLiteStore(tmp_path / "oncoai.sqlite3")
    local = LocalQdrantLikeIndex(store)
    index = QdrantRestIndex(
        qdrant_url="http://127.0.0.1:65534",
        collection="oncoai_chunks",
        fallback_index=local,
    )

    def fake_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        raise RuntimeError("Qdrant request failed: timeout")

    monkeypatch.setattr(index, "_request", fake_request)
    snapshot = index.preflight_vector_alignment(expected_vector_size=64)

    assert snapshot["status"] == "collection_unavailable"
    assert "timeout" in str(snapshot.get("error") or "")


def test_qdrant_rest_index_fail_closed_raises_on_search_error(tmp_path: Path):
    store = SQLiteStore(tmp_path / "oncoai.sqlite3")
    local = LocalQdrantLikeIndex(store)
    index = QdrantRestIndex(
        qdrant_url="http://127.0.0.1:65534",
        collection="oncoai_chunks",
        fallback_index=local,
        fail_closed=True,
    )

    with pytest.raises(RuntimeError, match="fail-closed mode"):
        index.search(query="osimertinib", top_k=5, filters={"cancer_type": "nsclc_egfr"})

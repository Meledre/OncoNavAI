from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.request
from typing import Any
from typing import Protocol

from backend.app.rag.embedder import Embedder, HashEmbedder, cosine_similarity
from backend.app.storage import SQLiteStore

logger = logging.getLogger(__name__)


class VectorIndex(Protocol):
    def replace_doc_chunks(self, doc_id: str, doc_version: str, chunks: list[dict[str, Any]]) -> None: ...
    def search(self, query: str, top_k: int, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...
    def count_doc_points(self, doc_id: str, doc_version: str) -> int: ...


class LocalQdrantLikeIndex:
    """Local payload-filtered vector index that mimics required MVP operations."""

    def __init__(self, store: SQLiteStore, embedder: Embedder | None = None) -> None:
        self.store = store
        self.embedder = embedder or HashEmbedder()

    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        for chunk in chunks:
            chunk["vector_json"] = chunk.pop("vector_json", None)
            chunk["vector"] = self.embedder.embed(chunk["text"])

    def replace_doc_chunks(self, doc_id: str, doc_version: str, chunks: list[dict[str, Any]]) -> None:
        for chunk in chunks:
            chunk["vector_json"] = None
            chunk["vector"] = self.embedder.embed(chunk["text"])

        serializable = []
        for chunk in chunks:
            item = dict(chunk)
            item["vector_json"] = __import__("json").dumps(item.pop("vector"), ensure_ascii=False)
            serializable.append(item)

        self.store.replace_doc_chunks(doc_id=doc_id, doc_version=doc_version, chunks=serializable)

    def search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        query_vector = self.embedder.embed(query)
        chunks = self.store.list_chunks(filters=filters)
        scored = []
        for chunk in chunks:
            score = cosine_similarity(query_vector, chunk["vector"])
            scored.append((score, chunk))
        scored.sort(key=lambda item: item[0], reverse=True)

        results = []
        for score, chunk in scored[:top_k]:
            payload = dict(chunk)
            payload["score"] = score
            results.append(payload)
        return results

    def count_doc_points(self, doc_id: str, doc_version: str) -> int:
        return self.store.count_doc_chunks(doc_id=doc_id, doc_version=doc_version)


class QdrantRestIndex:
    """Qdrant REST backend with deterministic local fallback."""
    _ALLOWED_FILTER_FIELDS = {"cancer_type", "language", "source_set", "doc_version", "doc_id"}

    def __init__(
        self,
        qdrant_url: str,
        collection: str,
        fallback_index: LocalQdrantLikeIndex,
        embedder: Embedder | None = None,
        *,
        fail_closed: bool = False,
    ) -> None:
        self.qdrant_url = qdrant_url.rstrip("/")
        self.collection = collection
        self.fallback_index = fallback_index
        self.embedder = embedder or fallback_index.embedder
        self.fail_closed = bool(fail_closed)
        self._collection_ready = False
        self._vector_size: int | None = None
        self._payload_indexes_ready = False

    @staticmethod
    def _point_id_from_chunk_id(chunk_id: str) -> int:
        digest = hashlib.blake2b(chunk_id.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, byteorder="big", signed=False)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        request = urllib.request.Request(
            self.qdrant_url + path,
            method=method,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={"content-type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = response.read().decode("utf-8").strip()
                if not raw:
                    return {}
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Qdrant request failed: {exc}") from exc

    @staticmethod
    def _extract_collection_vector_size(response: dict[str, Any]) -> int | None:
        result = response.get("result")
        if not isinstance(result, dict):
            return None
        config = result.get("config")
        if not isinstance(config, dict):
            return None
        params = config.get("params")
        if not isinstance(params, dict):
            return None
        vectors = params.get("vectors")
        if isinstance(vectors, dict):
            size = vectors.get("size")
            if isinstance(size, int):
                return size
            # Named vectors format.
            for value in vectors.values():
                if isinstance(value, dict) and isinstance(value.get("size"), int):
                    return int(value["size"])
        return None

    def _ensure_collection(self, vector_size: int) -> None:
        if self._collection_ready and self._vector_size == vector_size and self._payload_indexes_ready:
            return
        try:
            self._request(
                "PUT",
                f"/collections/{self.collection}",
                {"vectors": {"size": vector_size, "distance": "Cosine"}},
            )
        except RuntimeError as exc:
            if "HTTP Error 409" not in str(exc):
                raise
            details = self._request("GET", f"/collections/{self.collection}")
            existing_size = self._extract_collection_vector_size(details)
            if existing_size != vector_size:
                raise RuntimeError(
                    f"Qdrant collection vector size mismatch: expected={vector_size}, actual={existing_size}"
                ) from exc
        self._vector_size = vector_size
        self._collection_ready = True
        self._ensure_payload_indexes()

    def _ensure_payload_indexes(self) -> None:
        fields = ("cancer_type", "language", "source_set", "doc_version", "doc_id")
        for field_name in fields:
            try:
                self._request(
                    "PUT",
                    f"/collections/{self.collection}/index",
                    {"field_name": field_name, "field_schema": "keyword"},
                )
            except RuntimeError as exc:
                # Ignore already existing indexes.
                if "HTTP Error 409" not in str(exc):
                    raise
        self._payload_indexes_ready = True

    def replace_doc_chunks(self, doc_id: str, doc_version: str, chunks: list[dict[str, Any]]) -> None:
        if not self.fail_closed:
            # Keep local index in sync for deterministic fallback behavior.
            self.fallback_index.replace_doc_chunks(doc_id=doc_id, doc_version=doc_version, chunks=chunks)

        try:
            if chunks:
                vectors_by_chunk = {chunk["chunk_id"]: self.embedder.embed(chunk["text"]) for chunk in chunks}
                sample_vector = next(iter(vectors_by_chunk.values()))
                self._ensure_collection(vector_size=len(sample_vector))
            elif not self._collection_ready:
                return
            self._request(
                "POST",
                f"/collections/{self.collection}/points/delete?wait=true",
                {
                    "filter": {
                        "must": [
                            {"key": "doc_id", "match": {"value": doc_id}},
                            {"key": "doc_version", "match": {"value": doc_version}},
                        ]
                    }
                },
            )

            if not chunks:
                return

            points = []
            for chunk in chunks:
                vector = vectors_by_chunk[chunk["chunk_id"]]
                payload = dict(chunk)
                points.append(
                    {
                        "id": self._point_id_from_chunk_id(chunk["chunk_id"]),
                        "vector": vector,
                        "payload": payload,
                    }
                )

            self._request(
                "PUT",
                f"/collections/{self.collection}/points?wait=true",
                {"points": points},
            )
        except Exception as exc:  # noqa: BLE001
            if self.fail_closed:
                raise RuntimeError(f"Qdrant upsert failed in fail-closed mode: {exc}") from exc
            logger.warning("Qdrant upsert failed, using local fallback: %s", exc)
            return

    @staticmethod
    def _build_qdrant_filter(filters: dict[str, Any] | None) -> dict[str, Any] | None:
        if not filters:
            return None
        must = [
            {"key": key, "match": {"value": value}}
            for key, value in filters.items()
            if key in QdrantRestIndex._ALLOWED_FILTER_FIELDS and value
        ]
        return {"must": must} if must else None

    def search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        query_vector = self.embedder.embed(query)
        try:
            self._ensure_collection(vector_size=len(query_vector))
            payload: dict[str, Any] = {
                "vector": query_vector,
                "limit": top_k,
                "with_payload": True,
            }
            qdrant_filter = self._build_qdrant_filter(filters)
            if qdrant_filter:
                payload["filter"] = qdrant_filter

            response = self._request(
                "POST",
                f"/collections/{self.collection}/points/search",
                payload,
            )
            raw_items = response.get("result")
            if not isinstance(raw_items, list):
                raise RuntimeError("Invalid Qdrant search response")

            parsed: list[dict[str, Any]] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                payload_row = item.get("payload")
                if not isinstance(payload_row, dict):
                    continue
                row = dict(payload_row)
                row["score"] = float(item.get("score", 0.0))
                parsed.append(row)
            return parsed
        except Exception as exc:  # noqa: BLE001
            if self.fail_closed:
                raise RuntimeError(f"Qdrant search failed in fail-closed mode: {exc}") from exc
            logger.warning("Qdrant search failed, using local fallback: %s", exc)
            return self.fallback_index.search(query=query, top_k=top_k, filters=filters)

    def count_doc_points(self, doc_id: str, doc_version: str) -> int:
        try:
            self._ensure_collection(vector_size=len(self.embedder.embed("health-check")))
            response = self._request(
                "POST",
                f"/collections/{self.collection}/points/count",
                {
                    "exact": True,
                    "filter": {
                        "must": [
                            {"key": "doc_id", "match": {"value": doc_id}},
                            {"key": "doc_version", "match": {"value": doc_version}},
                        ]
                    },
                },
            )
            result = response.get("result")
            if isinstance(result, dict):
                count = result.get("count")
                if isinstance(count, int):
                    return count
        except Exception as exc:  # noqa: BLE001
            logger.warning("Qdrant count failed: %s", exc)
        return 0

    def preflight_vector_alignment(self, expected_vector_size: int | None) -> dict[str, Any]:
        snapshot: dict[str, Any] = {
            "backend": "qdrant",
            "collection": self.collection,
            "expected_vector_size": expected_vector_size,
            "actual_vector_size": None,
            "status": "unknown",
            "error": "",
        }
        if expected_vector_size is None:
            snapshot["status"] = "expected_vector_size_unknown"
            return snapshot
        try:
            response = self._request("GET", f"/collections/{self.collection}")
            actual_size = self._extract_collection_vector_size(response)
            snapshot["actual_vector_size"] = actual_size
            if actual_size is None:
                snapshot["status"] = "collection_unavailable"
            elif int(actual_size) == int(expected_vector_size):
                snapshot["status"] = "ok"
            else:
                snapshot["status"] = "vector_size_mismatch"
        except Exception as exc:  # noqa: BLE001
            snapshot["status"] = "collection_unavailable"
            snapshot["error"] = str(exc)
        return snapshot

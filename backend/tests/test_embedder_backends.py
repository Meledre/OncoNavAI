from __future__ import annotations

import http.client
import json
import ssl
import urllib.error

import pytest

from backend.app.rag import embedder as embedder_module


class _FailingEmbedder:
    def embed(self, text: str) -> list[float]:  # noqa: ARG002
        raise RuntimeError("primary down")


class _StaticEmbedder:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector

    def embed(self, text: str) -> list[float]:  # noqa: ARG002
        return list(self.vector)


class _StubHttpResponse:
    def __init__(self, body: dict) -> None:
        self._raw = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_resilient_embedder_falls_back_when_primary_unavailable():
    embedder = embedder_module.ResilientEmbedder(
        primary=_FailingEmbedder(),
        fallback=_StaticEmbedder([0.11, 0.22, 0.33]),
    )
    assert embedder.embed("hello") == [0.11, 0.22, 0.33]


def test_build_embedder_returns_hash_backend_by_default():
    embedder = embedder_module.build_embedder(
        backend="hash",
        url="",
        model="",
        api_key="",
    )
    vector = embedder.embed("osimertinib")
    assert len(vector) == 64
    assert any(value != 0.0 for value in vector)


def test_build_embedder_openai_compatible_uses_remote_response(monkeypatch):
    def fake_urlopen(request, timeout=8):  # noqa: ARG001
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["model"] == "text-embedding-3-small"
        assert payload["input"] == "query text"
        assert request.full_url == "http://embedding.local/v1/embeddings"
        return _StubHttpResponse({"data": [{"embedding": [0.1, -0.2, 0.3]}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    embedder = embedder_module.build_embedder(
        backend="openai",
        url="http://embedding.local",
        model="text-embedding-3-small",
        api_key="",
    )
    assert embedder.embed("query text") == [0.1, -0.2, 0.3]


def test_build_embedder_openai_without_api_key_uses_hash_for_public_openai(monkeypatch):
    called = {"count": 0}

    def fake_urlopen(request, timeout=8):  # noqa: ARG001
        called["count"] += 1
        raise AssertionError("remote embedding call should not happen without API key")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    embedder = embedder_module.build_embedder(
        backend="openai",
        url="https://api.openai.com",
        model="text-embedding-3-small",
        api_key="",
    )
    vector = embedder.embed("query text")
    assert len(vector) == 64
    assert called["count"] == 0


def test_build_embedder_openai_retries_transient_timeout(monkeypatch):
    state = {"calls": 0}

    def fake_urlopen(request, timeout=8):  # noqa: ARG001
        state["calls"] += 1
        if state["calls"] < 3:
            raise urllib.error.URLError(TimeoutError("handshake timed out"))
        return _StubHttpResponse({"data": [{"embedding": [0.4, 0.5, 0.6]}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    embedder = embedder_module.build_embedder(
        backend="openai",
        url="https://api.openai.com",
        model="text-embedding-3-small",
        api_key="test-key",
        fail_closed=True,
    )
    assert embedder.embed("query text") == [0.4, 0.5, 0.6]
    assert state["calls"] == 3


def test_build_embedder_openai_retries_ssl_eof(monkeypatch):
    state = {"calls": 0}

    def fake_urlopen(request, timeout=8):  # noqa: ARG001
        state["calls"] += 1
        if state["calls"] == 1:
            raise urllib.error.URLError(ssl.SSLEOFError("UNEXPECTED_EOF_WHILE_READING"))
        return _StubHttpResponse({"data": [{"embedding": [0.7, 0.8, 0.9]}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    embedder = embedder_module.build_embedder(
        backend="openai",
        url="https://api.openai.com",
        model="text-embedding-3-small",
        api_key="test-key",
        fail_closed=True,
    )
    assert embedder.embed("query text") == [0.7, 0.8, 0.9]
    assert state["calls"] == 2


def test_build_embedder_openai_retries_remote_disconnected(monkeypatch):
    state = {"calls": 0}

    def fake_urlopen(request, timeout=8):  # noqa: ARG001
        state["calls"] += 1
        if state["calls"] == 1:
            raise http.client.RemoteDisconnected("Remote end closed connection without response")
        return _StubHttpResponse({"data": [{"embedding": [0.15, 0.25, 0.35]}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    embedder = embedder_module.build_embedder(
        backend="openai",
        url="https://api.openai.com",
        model="text-embedding-3-small",
        api_key="test-key",
        fail_closed=True,
    )
    assert embedder.embed("query text") == [0.15, 0.25, 0.35]
    assert state["calls"] == 2


def test_build_embedder_fail_closed_requires_openai_credentials():
    with pytest.raises(RuntimeError, match="EMBEDDING_API_KEY"):
        embedder_module.build_embedder(
            backend="openai",
            url="https://api.openai.com",
            model="text-embedding-3-small",
            api_key="",
            fail_closed=True,
        )
